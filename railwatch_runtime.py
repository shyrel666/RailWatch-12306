"""JSON Lines Python runtime entry for the Electron app."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from railwatch_bridge import RailWatchBridge, dumps_json


def configure_stdio() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


class RailWatchRuntime:
    def __init__(
        self,
        bridge: Optional[RailWatchBridge] = None,
        writer: Optional[Callable[[dict], None]] = None,
        max_workers: int = 4,
    ):
        self._write_lock = threading.Lock()
        self.writer = writer or self._stdout_writer
        self.bridge = bridge or RailWatchBridge(event_callback=self.emit_event)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="railwatch-cmd")

    def emit_event(self, event: dict) -> None:
        self._write({"type": "event", **event})

    def _write(self, payload: dict) -> None:
        self.writer(payload)

    def handle_line(self, line: str) -> "Future":
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            self.emit_event(
                {
                    "event": "runtimeError",
                    "payload": {
                        "message": f"无效 JSON 输入：{exc}",
                        "class": exc.__class__.__name__,
                    },
                }
            )
            return self._executor.submit(lambda: None)
        request_id = request.get("id")
        command = request.get("command")
        payload = request.get("payload") or {}
        return self._executor.submit(self._run_command, request_id, command, payload)

    def _run_command(self, request_id, command: str, payload: dict) -> None:
        try:
            result = self._dispatch(command, payload)
            self._write({"type": "response", "id": request_id, "ok": True, "result": result})
        except Exception as exc:
            self._write(
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
            "savePreferences": lambda: self.bridge.save_preferences(
                str(payload.get("theme", "light")),
                payload.get("notification_settings"),
            ),
            "syncServerTime": lambda: self.bridge.sync_server_time(),
        }
        if command not in handlers:
            raise ValueError(f"未知命令: {command}")
        return handlers[command]()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _stdout_writer(self, payload: dict) -> None:
        with self._write_lock:
            sys.stdout.write(dumps_json(payload) + "\n")
            sys.stdout.flush()


def main() -> int:
    configure_stdio()
    runtime = RailWatchRuntime()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            runtime.handle_line(line)
    finally:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
