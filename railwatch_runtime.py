"""JSON Lines Python runtime entry for the Electron app."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
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
        self._maintenance_guard = threading.Lock()
        self._active_commands = 0
        self._clearing_data = False
        self.writer = writer or self._stdout_writer
        self.bridge = bridge or RailWatchBridge(event_callback=self.emit_event)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="railwatch-cmd")

    def emit_event(self, event: dict) -> None:
        self._write({"type": "event", **event})

    def _write(self, payload: dict) -> None:
        self.writer(payload)

    def _protocol_error(self, request_id=None) -> Future:
        error = {"message": "无效请求：需要 UTF-8 JSON 对象及有效的 id、command、payload", "class": "ProtocolError"}
        if isinstance(request_id, str) and 0 < len(request_id) <= 128:
            self._write({"type": "response", "id": request_id, "ok": False, "error": error})
        else:
            self.emit_event({"event": "protocolError", "payload": error})
        future = Future()
        future.set_result(None)
        return future

    def handle_line(self, line: str | bytes) -> "Future":
        try:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="strict")
            request = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError):
            return self._protocol_error()
        if not isinstance(request, dict):
            return self._protocol_error()
        request_id = request.get("id")
        command = request.get("command")
        payload = request.get("payload", {})
        if (not isinstance(request_id, str) or not 0 < len(request_id) <= 128
                or not isinstance(command, str) or not 0 < len(command) <= 80
                or not isinstance(payload, dict)):
            return self._protocol_error(request_id)
        return self._executor.submit(self._run_command, request_id, command, payload)

    def _run_command(self, request_id, command: str, payload: dict) -> None:
        try:
            with self._command_slot(command):
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

    @contextmanager
    def _command_slot(self, command):
        clearing = command == "clearLocalData"
        with self._maintenance_guard:
            if self._clearing_data:
                raise RuntimeError("正在清除本地数据，请等待清理完成。")
            if clearing and self._active_commands:
                raise RuntimeError("其他操作尚未结束，尚未清除数据，请稍后重试。")
            self._active_commands += 1
            if clearing:
                self._clearing_data = True
        try:
            yield
        finally:
            with self._maintenance_guard:
                self._active_commands -= 1
                if clearing:
                    self._clearing_data = False

    def _dispatch(self, command: str, payload: dict):
        handlers = {
            "getRuntimeInfo": lambda: self.bridge.get_runtime_info(),
            "loadConfig": lambda: self.bridge.load_config(),
            "saveConfig": lambda: self.bridge.save_config(payload.get("config") or payload),
            "loadTripState": lambda: self.bridge.load_trip_state(),
            "saveTripDraft": lambda: self.bridge.save_trip_draft(payload.get("config"), payload.get("revision")),
            "searchStations": lambda: self.bridge.search_stations(payload.get("query"), payload.get("limit", 12)),
            "refreshStations": lambda: self.bridge.refresh_stations(),
            "stationSaleTimes": lambda: self.bridge.station_sale_times(payload.get("station"), payload.get("force", False)),
            "loadTripChoices": lambda: self.bridge.load_trip_choices(),
            "saveTrainFavorites": lambda: self.bridge.save_train_favorites(payload.get("from_station"), payload.get("to_station"), payload.get("trains")),
            "readPassengers": lambda: self.bridge.read_passengers(),
            "checkEnvironment": lambda: self.bridge.check_environment(),
            "downloadChromeDriver": lambda: self.bridge.download_chromedriver(),
            "openLogin": lambda: self.bridge.open_login(),
            "checkLogin": lambda: self.bridge.check_login(),
            "runReviews": lambda: self.bridge.run_reviews(payload.get("limit", 20), payload.get("cursor")),
            "runReview": lambda: self.bridge.run_review(payload.get("run_id")),
            "rehearse": lambda: self.bridge.rehearse(payload.get("config") or payload, payload.get("options")),
            "cancelRehearsal": lambda: self.bridge.cancel_rehearsal(),
            "rehearsalHistory": lambda: self.bridge.rehearsal_history(payload.get("limit", 20)),
            "clearRehearsalHistory": lambda: self.bridge.clear_rehearsal_history(),
            "analyzeQuery": lambda: self.bridge.analyze_query(payload.get("config") or payload, request_id=payload.get("request_id")),
            "startMonitor": lambda: self.bridge.start_monitor(
                payload.get("config") or payload,
                confirmed=bool(payload.get("confirmed", False)),
                expected_dates=payload.get("expected_dates"),
            ),
            "continueOrder": lambda: self.bridge.continue_order(payload.get("intent_id")),
            "orderHistory": lambda: self.bridge.order_history(payload.get("limit", 20), payload.get("cursor"), payload.get("status")),
            "orderDetail": lambda: self.bridge.order_detail(payload.get("intent_id")),
            "dismissOrder": lambda: self.bridge.dismiss_order(str(payload.get("intent_id", "")), confirmed=payload.get("confirmed") is True),
            "systemResumed": lambda: self.bridge.system_resumed(),
            "stopMonitor": lambda: self.bridge.stop_monitor(),
            "taskActivity": lambda: self.bridge.task_activity(),
            "prepareShutdown": lambda: self.bridge.prepare_shutdown(payload.get("purpose")),
            "cancelShutdown": lambda: self.bridge.cancel_shutdown(),
            "closeBrowser": lambda: self.bridge.close_browser(confirmed=bool(payload.get("confirmed", False))),
            "clearLocalData": lambda: self.bridge.clear_local_data(confirmed=bool(payload.get("confirmed", False))),
            "exportLog": lambda: self.bridge.export_log(payload.get("path"), entries=payload.get("entries")),
            "clearLog": lambda: self.bridge.clear_log(),
            "loadPreferences": lambda: self.bridge.load_preferences(),
            "savePreferences": lambda: self.bridge.save_preferences(
                payload.get("theme"),
                payload.get("notification_settings"),
                close_to_tray=payload.get("close_to_tray"),
                auto_rehearsal=payload.get("auto_rehearsal"),
            ),
            "notificationStatus": lambda: self.bridge.notification_status(),
            "testNotification": lambda: self.bridge.test_notification(),
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
        for line in getattr(sys.stdin, "buffer", sys.stdin):
            line = line.strip()
            if not line:
                continue
            runtime.handle_line(line)
    finally:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
