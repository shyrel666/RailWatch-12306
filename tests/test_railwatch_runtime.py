import ast
import io
import json
import re
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import railwatch_runtime
from railwatch_runtime import RailWatchRuntime

ROOT = Path(__file__).resolve().parents[1]
# The main process answers retryRuntime itself and is the only sender of the other three.
MAIN_PROCESS_ONLY = {"retryRuntime"}
SENT_BY_MAIN_PROCESS = {"prepareShutdown", "cancelShutdown", "systemResumed"}


def renderer_commands():
    source = (ROOT / "electron" / "ipcSecurity.ts").read_text(encoding="utf-8")
    block = re.search(r"export const RAILWATCH_COMMANDS = \[(.*?)\] as const", source, re.S).group(1)
    return re.findall(r'"(\w+)"', block)


def dispatched_commands():
    tree = ast.parse((ROOT / "railwatch_runtime.py").read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_dispatch")
    handlers = next(node.value for node in ast.walk(method) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "handlers" for target in node.targets))
    return [key.value for key in handlers.keys]


class RailWatchRuntimeTests(unittest.TestCase):
    def test_handle_line_emits_runtime_error_for_invalid_json(self):
        events = []
        runtime = RailWatchRuntime(bridge=Mock(), writer=lambda payload: events.append(payload))
        runtime.handle_line("not-json").result()
        self.assertTrue(any(item.get("event") == "protocolError" for item in events))
        runtime.shutdown()

    def test_sync_server_time_command_is_registered(self):
        bridge = Mock()
        bridge.sync_server_time.return_value = {"offset_seconds": 0.1}
        runtime = RailWatchRuntime(bridge=bridge, writer=lambda _payload: None)
        result = runtime._dispatch("syncServerTime", {})
        self.assertEqual(result["offset_seconds"], 0.1)

    def test_renderer_whitelist_matches_runtime_dispatch(self):
        """A whitelisted command the runtime cannot handle fails only when used; one missing from the whitelist cannot be sent."""
        renderer, dispatched = renderer_commands(), dispatched_commands()
        self.assertEqual(len(renderer), len(set(renderer)))
        # A repeated key in the dict literal would silently replace the earlier handler.
        self.assertEqual(len(dispatched), len(set(dispatched)))
        self.assertEqual(set(renderer) - set(dispatched), MAIN_PROCESS_ONLY)
        self.assertEqual(set(dispatched) - set(renderer), SENT_BY_MAIN_PROCESS)
        main = (ROOT / "electron" / "main.ts").read_text(encoding="utf-8")
        for command in MAIN_PROCESS_ONLY | SENT_BY_MAIN_PROCESS:
            self.assertIn(f'"{command}"', main)
        runtime = RailWatchRuntime(bridge=Mock(), writer=lambda _payload: None)
        try:
            for command in dispatched:
                runtime._dispatch(command, {})
            with self.assertRaisesRegex(ValueError, "未知命令"):
                runtime._dispatch("retryRuntime", {})
        finally:
            runtime.shutdown()


class RuntimeOutputShutdownTests(unittest.TestCase):
    """A background thread inside a stdout write at interpreter shutdown aborts the process."""

    def test_closed_output_drops_later_events(self):
        runtime = RailWatchRuntime(bridge=Mock())
        stream = io.StringIO()
        try:
            with patch("railwatch_runtime.sys.stdout", stream):
                runtime.emit_event({"event": "before"})
                runtime.close_output()
                runtime.emit_event({"event": "after"})
        finally:
            runtime.shutdown()
        self.assertEqual([json.loads(line)["event"] for line in stream.getvalue().splitlines()], ["before"])

    def test_close_output_waits_for_a_write_in_progress(self):
        runtime = RailWatchRuntime(bridge=Mock())
        entered, release = threading.Event(), threading.Event()

        class SlowStream(io.StringIO):
            def write(self, text):
                entered.set()
                release.wait(5)
                return super().write(text)

        stream = SlowStream()
        try:
            with patch("railwatch_runtime.sys.stdout", stream):
                writer = threading.Thread(target=runtime.emit_event, args=({"event": "slow"},))
                writer.start()
                self.assertTrue(entered.wait(5))
                closer = threading.Thread(target=runtime.close_output)
                closer.start()
                closer.join(0.2)
                self.assertTrue(closer.is_alive(), "close_output 不应在写入完成前返回")
                release.set()
                writer.join(5)
                closer.join(5)
        finally:
            release.set()
            runtime.shutdown()
        self.assertFalse(closer.is_alive())
        self.assertIn('"slow"', stream.getvalue())

    def test_close_output_does_not_wait_forever_for_a_stuck_writer(self):
        runtime = RailWatchRuntime(bridge=Mock())
        runtime._write_lock.acquire()
        try:
            started = time.monotonic()
            runtime.close_output(timeout=0.05)
            self.assertLess(time.monotonic() - started, 2)
        finally:
            runtime._write_lock.release()
            runtime.shutdown()

    def test_main_closes_output_after_every_command_has_answered(self):
        runtime = Mock()
        with patch("railwatch_runtime.RailWatchRuntime", return_value=runtime), \
                patch("railwatch_runtime.configure_stdio"), \
                patch("railwatch_runtime.sys.stdin", io.BytesIO(b"")):
            self.assertEqual(railwatch_runtime.main(), 0)
        self.assertEqual([call[0] for call in runtime.mock_calls][-3:],
                         ["bridge.stop_idle_watch", "shutdown", "close_output"])


if __name__ == "__main__":
    unittest.main()
