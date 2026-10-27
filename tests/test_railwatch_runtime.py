import ast
import json
import re
import unittest
from pathlib import Path
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
