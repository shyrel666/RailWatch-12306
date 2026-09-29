import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from railwatch_cleanup import (PENDING_FILE, WINDOWS_CLEANUP, checked_data_path,
                               check_files_released, release_orphan_browsers, reset_directory)
from railwatch_state import APP_SLUG


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name, APP_SLUG)
        self.target.mkdir()
        (self.target / "config.json").write_text('original', encoding="utf-8")

    def test_refuses_wrong_directory_and_external_cleanup_manifest(self):
        with self.assertRaisesRegex(RuntimeError, "异常数据目录"):
            checked_data_path(self.temp.name)
        outside = Path(self.temp.name, "keep")
        outside.mkdir()
        (outside / "important.txt").write_text("keep")
        (self.target / PENDING_FILE).write_text(json.dumps([str(outside)]))
        with self.assertRaisesRegex(RuntimeError, "路径异常"):
            reset_directory(self.target, lambda: None)
        self.assertTrue((outside / "important.txt").exists())
        self.assertEqual((self.target / "config.json").read_text(), "original")

    def test_success_resets_only_the_selected_directory(self):
        outside = Path(self.temp.name, "keep.txt")
        outside.write_text("keep")
        def initialize():
            (self.target / "new.db").write_text("new")
            return "ready"
        result, remaining = reset_directory(self.target, initialize)
        self.assertEqual(result, "ready")
        self.assertEqual(remaining, [])
        self.assertFalse((self.target / "config.json").exists())
        self.assertEqual((self.target / "new.db").read_text(), "new")
        self.assertEqual(outside.read_text(), "keep")
        self.assertFalse(list(Path(self.temp.name).glob(f".{APP_SLUG}-clearing-*")))

    def test_initialization_failure_restores_original_files(self):
        def fail():
            (self.target / "partial.db").write_text("partial")
            raise OSError("disk full")
        with self.assertRaisesRegex(RuntimeError, "已恢复原数据"):
            reset_directory(self.target, fail)
        self.assertEqual((self.target / "config.json").read_text(), "original")
        self.assertFalse((self.target / "partial.db").exists())

    def test_rename_failure_does_not_delete_anything(self):
        with patch("railwatch_cleanup.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaisesRegex(RuntimeError, "尚未删除数据"):
                reset_directory(self.target, lambda: None)
        self.assertEqual((self.target / "config.json").read_text(), "original")

    def test_incomplete_disposal_is_reported_and_retried(self):
        with patch("railwatch_cleanup._remove_tree", side_effect=PermissionError("locked")), patch("railwatch_cleanup.time.sleep"):
            _, remaining = reset_directory(self.target, lambda: "new")
        self.assertEqual(len(remaining), 1)
        self.assertEqual((Path(remaining[0]) / "config.json").read_text(), "original")
        self.assertTrue((self.target / PENDING_FILE).exists())
        _, remaining_after_retry = reset_directory(self.target, lambda: "new")
        self.assertEqual(remaining_after_retry, [])
        self.assertFalse(Path(remaining[0]).exists())
        self.assertFalse((self.target / PENDING_FILE).exists())

    @unittest.skipUnless(os.name == "nt", "Windows sharing modes")
    def test_locked_file_prevents_reset_without_partial_deletion(self):
        import win32con
        import win32file
        handle = win32file.CreateFile(str(self.target / "config.json"), win32con.GENERIC_READ,
                                      win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING, 0, None)
        try:
            with self.assertRaisesRegex(RuntimeError, "尚未删除数据"):
                reset_directory(self.target, lambda: self.fail("must not initialize"))
            self.assertEqual((self.target / "config.json").read_text(), "original")
        finally:
            handle.Close()
        check_files_released(self.target)

    def test_process_check_failure_stops_before_deletion(self):
        with patch("railwatch_cleanup.sys.platform", "win32"), patch("railwatch_cleanup.subprocess.run") as run:
            run.return_value = Mock(returncode=2, stdout="OTHER_OWNER")
            with self.assertRaisesRegex(RuntimeError, "另一个仍在运行"):
                release_orphan_browsers(self.target)
            command, options = run.call_args
            self.assertNotIn(str(self.target), command[0][-1])
            self.assertEqual(options["env"]["RAILWATCH_CLEANUP_DRIVER"], str(self.target / "chromedriver.exe"))
            run.side_effect = subprocess.TimeoutExpired("powershell", 25)
            with self.assertRaisesRegex(RuntimeError, "尚未删除数据"):
                release_orphan_browsers(self.target)

    @unittest.skipUnless(os.name == "nt", "PowerShell matching")
    def test_powershell_only_stops_identified_orphans_and_rechecks_identity(self):
        # Shadow every process command: this executes no real process termination.
        prefix = r'''
$script:rows = ConvertFrom-Json $env:RAILWATCH_TEST_PROCESSES
function Get-CimInstance {
    param($ClassName, $Filter)
    if ($Filter) { return @($script:rows | Where-Object { $_.ProcessId -eq [int]($Filter -replace 'ProcessId=', '') }) }
    return $script:rows
}
function Stop-Process {
    param($Id, [switch]$Force, $ErrorAction)
    Write-Output ('STOP:' + $Id)
    $script:rows = @($script:rows | Where-Object { $_.ProcessId -ne $Id })
}
'''
        profile = str(self.target / "chrome_profile_12306")
        driver = str(self.target / "chromedriver.exe")
        def row(pid, parent, name, exe="", cmd="", created=2):
            return dict(ProcessId=pid, ParentProcessId=parent, Name=name, ExecutablePath=exe, CommandLine=cmd, CreationDate=created)
        rows = [row(11, 999, "chromedriver.exe", driver),
                row(12, 11, "chrome.exe", cmd=f'chrome "--user-data-dir={profile}"'),
                row(13, 12, "chrome.exe"),
                row(21, 999, "chrome.exe", cmd=f'chrome "--user-data-dir={profile}-other"'),
                row(22, 999, "chromedriver.exe", driver + ".other")]
        env = {**os.environ, "RAILWATCH_TEST_PROCESSES": json.dumps(rows), "RAILWATCH_CLEANUP_PROFILE": profile,
               "RAILWATCH_CLEANUP_DRIVER": driver, "RAILWATCH_CLEANUP_OWNER": "1", "RAILWATCH_CLEANUP_OWNED_DRIVER": "0"}
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + WINDOWS_CLEANUP],
                                env=env, capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(line for line in result.stdout.splitlines() if line.startswith("STOP:")), {"STOP:11", "STOP:12", "STOP:13"})
        rows.append(row(999, 998, "python.exe", created=1))
        env["RAILWATCH_TEST_PROCESSES"] = json.dumps(rows)
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + WINDOWS_CLEANUP],
                                env=env, capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("STOP:", result.stdout)

    def test_bridge_reset_clears_cached_state_and_honors_order_guard(self):
        from railwatch_bridge import RailWatchBridge
        bridge = RailWatchBridge(str(self.target))
        self.addCleanup(lambda: bridge.notification_service.close())
        bridge.state = replace(bridge.state, login_ready=True, query_ready=True, environment_ready=True)
        bridge.query_results = [{"train_code": "G1"}]
        bridge._chromedriver_repair_failed = True
        bridge.save_preferences(auto_rehearsal=True)
        with patch.object(bridge.order_journal, "pending", return_value={"status": "unknown"}), patch("railwatch_bridge.release_orphan_browsers") as release:
            with self.assertRaisesRegex(RuntimeError, "未完成订单"):
                bridge.clear_local_data(confirmed=True)
            release.assert_not_called()
        with patch("railwatch_bridge.release_orphan_browsers"):
            result = bridge.clear_local_data(confirmed=True)
        self.assertTrue(result["cleared"])
        self.assertFalse(result["cleanup_pending"])
        self.assertFalse(bridge.state.login_ready)
        self.assertFalse(bridge.state.query_ready)
        self.assertFalse(bridge.state.environment_ready)
        self.assertEqual(bridge.query_results, [])
        self.assertFalse(bridge._chromedriver_repair_failed)
        self.assertFalse(bridge.load_preferences()["auto_rehearsal"])
        self.assertEqual(bridge.order_journal.recent_runs()["items"], [])

    def test_runtime_prevents_writes_during_clear_and_clear_during_other_commands(self):
        from railwatch_runtime import RailWatchRuntime
        runtime = RailWatchRuntime(bridge=Mock(), writer=lambda _: None)
        self.addCleanup(runtime._executor.shutdown)
        with runtime._command_slot("clearLocalData"):
            with self.assertRaisesRegex(RuntimeError, "正在清除"):
                with runtime._command_slot("saveTripDraft"):
                    self.fail("must not write")
        with runtime._command_slot("saveTripDraft"):
            with self.assertRaisesRegex(RuntimeError, "其他操作尚未结束"):
                with runtime._command_slot("clearLocalData"):
                    self.fail("must not clear")
        with runtime._command_slot("clearLocalData"):
            pass
