import json
import unittest
from unittest.mock import Mock

from railwatch_runtime import RailWatchRuntime


class RailWatchRuntimeTests(unittest.TestCase):
    def test_handle_line_emits_runtime_error_for_invalid_json(self):
        events = []
        runtime = RailWatchRuntime(bridge=Mock(), writer=lambda payload: events.append(payload))
        runtime.handle_line("not-json").result()
        self.assertTrue(any(item.get("event") == "runtimeError" for item in events))

    def test_sync_server_time_command_is_registered(self):
        bridge = Mock()
        bridge.sync_server_time.return_value = {"offset_seconds": 0.1}
        runtime = RailWatchRuntime(bridge=bridge, writer=lambda _payload: None)
        result = runtime._dispatch("syncServerTime", {})
        self.assertEqual(result["offset_seconds"], 0.1)


if __name__ == "__main__":
    unittest.main()
