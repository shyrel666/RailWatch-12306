"""JSON Lines Python runtime entry for the Electron app."""

from __future__ import annotations

import json
import sys
from typing import Callable, Optional

from railwatch_bridge import RailWatchBridge, dumps_json


def configure_stdio() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


class RailWatchRuntime:
    def __init__(self, bridge: Optional[RailWatchBridge] = None, writer: Optional[Callable[[dict], None]] = None):
        self.writer = writer or self._stdout_writer
        self.bridge = bridge or RailWatchBridge(event_callback=self.emit_event)

    def emit_event(self, event: dict) -> None:
        self.writer({"type": "event", **event})

    def handle_line(self, line: str) -> None:
        request = json.loads(line)
        request_id = request.get("id")
        command = request.get("command")
        payload = request.get("payload") or {}
        try:
            result = self._dispatch(command, payload)
            self.writer({"type": "response", "id": request_id, "ok": True, "result": result})
        except Exception as exc:
            self.writer(
                {
                    "type": "response",
                    "id": request_id,
                    "ok": False,
                    "error": {"message": str(exc), "class": exc.__class__.__name__},
                }
            )

    def _dispatch(self, command: str, payload: dict):
        handlers = {
            "getRuntimeInfo": lambda: self.bridge.get_runtime_info(),
            "loadConfig": lambda: self.bridge.load_config(),
            "saveConfig": lambda: self.bridge.save_config(payload.get("config") or payload),
            "checkEnvironment": lambda: self.bridge.check_environment(),
            "downloadChromeDriver": lambda: self.bridge.download_chromedriver(),
            "openLogin": lambda: self.bridge.open_login(),
            "checkLogin": lambda: self.bridge.check_login(),
            "analyzeQuery": lambda: self.bridge.analyze_query(payload.get("config") or payload),
            "startMonitor": lambda: self.bridge.start_monitor(
                payload.get("config") or payload,
                confirmed=bool(payload.get("confirmed", False)),
            ),
            "stopMonitor": lambda: self.bridge.stop_monitor(),
            "closeBrowser": lambda: self.bridge.close_browser(confirmed=bool(payload.get("confirmed", False))),
            "clearLocalData": lambda: self.bridge.clear_local_data(confirmed=bool(payload.get("confirmed", False))),
            "exportLog": lambda: self.bridge.export_log(payload.get("path")),
            "clearLog": lambda: self.bridge.clear_log(),
            "loadPreferences": lambda: self.bridge.load_preferences(),
            "savePreferences": lambda: self.bridge.save_preferences(str(payload.get("theme", "light"))),
        }
        if command not in handlers:
            raise ValueError(f"未知命令: {command}")
        return handlers[command]()

    @staticmethod
    def _stdout_writer(payload: dict) -> None:
        sys.stdout.write(dumps_json(payload) + "\n")
        sys.stdout.flush()


def main() -> int:
    configure_stdio()
    runtime = RailWatchRuntime()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        runtime.handle_line(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
