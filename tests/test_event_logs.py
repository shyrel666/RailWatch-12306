import json
import os
import tempfile
import unittest
from unittest.mock import patch

from railwatch_bridge import RailWatchBridge
from railwatch_runtime import RailWatchRuntime


class EventLogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.events = []
        self.bridge = RailWatchBridge(self.directory.name, event_callback=self.events.append)

    def test_environment_failure_emits_error_log_with_same_reason_as_state(self):
        with patch("railwatch_bridge.SELENIUM_AVAILABLE", False):
            state = self.bridge.check_environment()
        errors = [event["payload"] for event in self.events
                  if event["event"] == "log" and event["payload"]["level"] == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["message"], state["error_message"])
        self.assertIn("Selenium", errors[0]["message"])

    def test_runtime_exports_desktop_snapshot_including_stderr_and_paused_logs(self):
        self.bridge.log("backend-only record")
        responses = []
        runtime = RailWatchRuntime(bridge=self.bridge, writer=responses.append)
        self.addCleanup(runtime.shutdown)
        entries = [
            {"time": "10:00:00", "level": "WARN", "message": "stderr diagnostic"},
            {"time": "10:00:01", "level": "ERROR", "message": "暂停期间的错误"},
        ]
        path = os.path.join(self.directory.name, "events.txt")
        runtime.handle_line(json.dumps({"id": "export", "command": "exportLog",
                                       "payload": {"path": path, "entries": entries}})).result()
        self.assertTrue(responses[-1]["ok"])
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "[10:00:00] [WARN] stderr diagnostic\n[10:00:01] [ERROR] 暂停期间的错误\n")

    def test_empty_snapshot_does_not_fall_back_to_backend_logs(self):
        self.bridge.log("old record")
        path = os.path.join(self.directory.name, "empty.txt")
        self.bridge.export_log(path, entries=[])
        self.assertEqual(os.path.getsize(path), 0)

    def test_invalid_snapshot_does_not_overwrite_existing_file(self):
        path = os.path.join(self.directory.name, "existing.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("keep me")
        for entries in ({}, [{"time": "10:00:00"}], [{"time": 1, "level": "INFO", "message": "bad"}]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.bridge.export_log(path, entries=entries)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "keep me")

    def test_clear_emits_boundary_and_keeps_subsequent_logs(self):
        self.bridge.log("old record")
        self.assertEqual(self.bridge.clear_log(), {"cleared": True})
        self.assertEqual(self.bridge.log_entries, [])
        self.bridge.log("new record")
        self.assertEqual([event["event"] for event in self.events], ["log", "logsCleared", "log"])
        self.assertEqual([entry["message"] for entry in self.bridge.log_entries], ["new record"])
