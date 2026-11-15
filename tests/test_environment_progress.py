"""The progress dialog follows the full command, not only its driver download."""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from scripts.keychain_isolation import isolate_system_keychain

setUpModule = isolate_system_keychain


class EnvironmentProgressTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        self.events = []
        self.bridge = RailWatchBridge(data_dir=directory.name, event_callback=self.events.append)
        self.bridge._start_connectivity_probe = lambda: None
        self.bridge.chromedriver_path = os.path.join(directory.name, "missing-driver")

    def progress(self):
        return [event["payload"] for event in self.events if event["event"] == "environmentProgress"]

    def test_browser_verification_failure_finishes_progress_and_retry_starts_fresh(self):
        self.bridge._ensure_driver = Mock(side_effect=RuntimeError("browser unavailable"))
        with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", False), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True):
            result = self.bridge.check_environment()
            failed = self.progress()[-1]
            self.assertEqual(result["phase"], "error")
            self.assertEqual(failed["status"], "error")
            self.assertEqual(failed["message"], result["error_message"])
            self.assertEqual(failed["operation"], "checkEnvironment")
            self.events.clear()
            self.bridge._ensure_driver = Mock(return_value=Mock())
            self.bridge.check_environment()
        progress = self.progress()
        self.assertEqual(progress[0]["stage"], "checking")
        self.assertGreaterEqual(progress[0]["started_at"], failed["updated_at"])
        self.assertEqual(progress[-1]["status"], "success")
        self.assertNotIn("downloading", [item["stage"] for item in progress])

    def test_existing_browser_reports_success_after_connection_verified(self):
        self.bridge.driver = Mock()
        with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", False), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True), \
                patch("railwatch_bridge.driver_session_alive", return_value=True):
            self.bridge.check_environment()
        self.bridge.driver.execute_script.assert_called_once_with("return document.readyState")
        self.assertEqual([item["stage"] for item in self.progress()], ["checking", "verifying", "complete"])
        self.assertEqual(self.progress()[-1]["status"], "success")

    def test_manual_download_forwards_unknown_size_and_finishes_only_after_install(self):
        def install(target_dir, major_version, log_callback, progress_callback):
            progress_callback({"stage": "downloading", "message": "下载中", "downloaded_bytes": 512,
                               "total_bytes": None, "bytes_per_second": 128, "eta_seconds": None})
            progress_callback({"stage": "complete", "message": "已安装"})
            self.assertEqual(self.progress()[-1]["status"], "running")
            return os.path.join(target_dir, "chromedriver.exe")

        with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", return_value="152"), \
                patch("railwatch_bridge.download_and_install_chromedriver", side_effect=install):
            result = self.bridge.download_chromedriver()
        progress = self.progress()
        self.assertIsNone(progress[1]["total_bytes"])
        self.assertIsNone(progress[1]["eta_seconds"])
        self.assertEqual(progress[-1]["status"], "success")
        self.assertTrue(all(item["operation"] == "downloadChromeDriver" for item in progress))
        self.assertEqual(result["chromedriver_path"], self.bridge.chromedriver_path)

    def test_manual_download_failure_and_missing_chrome_report_error(self):
        with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", return_value="152"), \
                patch("railwatch_bridge.download_and_install_chromedriver", side_effect=RuntimeError("network timeout")):
            with self.assertRaisesRegex(RuntimeError, "network timeout"):
                self.bridge.download_chromedriver()
        self.assertEqual(self.progress()[-1]["status"], "error")
        self.assertIn("network timeout", self.progress()[-1]["message"])
        self.events.clear()
        with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", return_value=None):
            self.assertEqual(self.bridge.download_chromedriver()["chrome_version"], "")
        self.assertEqual(self.progress()[-1]["status"], "error")
        self.assertIn("请先安装 Chrome", self.progress()[-1]["message"])


if __name__ == "__main__":
    unittest.main()
