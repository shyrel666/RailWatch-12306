"""Verify the built runtime restores SQLite orders and protects notification secrets.

Windows protects secrets with DPAPI. macOS keeps them in the default keychain,
which CI points at a temporary keychain before running this script. No browser,
12306 login or network action is involved.

Usage: python tests/runtime_order_smoke.py [--exe PATH_TO_RUNTIME]
"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_orders import OrderIntent, OrderJournal, OrderResult

IS_MACOS = sys.platform == "darwin"
KEYCHAIN_SERVICE = "org.railwatch.railwatch12306"
KEYCHAIN_ACCOUNT = "notification-secrets"
CONFIG = {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-09-10",
          "train_code": "G101", "seat_keyword": "二等座", "passengers": "测试乘客"}


def default_executable() -> Path:
    if sys.platform == "win32":
        return ROOT / "dist-runtime" / "railwatch_runtime.exe"
    return ROOT / "dist-runtime" / "railwatch_runtime" / "railwatch_runtime"


def isolated_environment(home: str) -> dict:
    """Point the runtime's data directory at a temporary folder."""
    if sys.platform == "win32":
        return dict(os.environ, LOCALAPPDATA=home, APPDATA=home)
    return dict(os.environ, HOME=home)


def data_directory(home: str) -> Path:
    if sys.platform == "win32":
        return Path(home) / "railwatch-12306"
    if IS_MACOS:
        return Path(home) / "Library" / "Application Support" / "railwatch-12306"
    return Path(home) / ".local" / "share" / "railwatch-12306"


def keychain_item_exists() -> bool:
    found = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
                           capture_output=True, text=True)
    return found.returncode == 0


class RuntimeSession:
    """Drive the runtime over JSON lines, so restarts can wait for background events."""

    def __init__(self, executable: Path, environment: dict):
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8", env=environment,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.messages = []
        self._queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self._stderr = []
        threading.Thread(target=lambda: self._stderr.extend(self.process.stderr), daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            if line.strip().startswith("{"):
                self._queue.put(json.loads(line))
        self._queue.put(None)

    def _next(self, timeout: float) -> dict:
        try:
            message = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("runtime did not answer in time") from None
        if message is None:
            raise RuntimeError(f"runtime exited early: {''.join(self._stderr)}")
        self.messages.append(message)
        return message

    def request(self, request_id: str, command: str, payload=None, timeout: float = 40) -> dict:
        self.process.stdin.write(json.dumps({"id": request_id, "command": command, "payload": payload or {}},
                                            ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        for message in self.messages:
            if message.get("type") == "response" and message.get("id") == request_id:
                return message
        while True:
            message = self._next(timeout)
            if message.get("type") == "response" and message.get("id") == request_id:
                return message

    def wait_event(self, name: str, timeout: float = 40) -> dict:
        for message in self.messages:
            if message.get("event") == name:
                return message
        while True:
            message = self._next(timeout)
            if message.get("event") == name:
                return message

    def close(self):
        self.process.stdin.close()
        returncode = self.process.wait(timeout=40)
        while (message := self._queue.get(timeout=5)) is not None:
            self.messages.append(message)
        if returncode:
            raise RuntimeError(f"runtime exited with {returncode}: {''.join(self._stderr)}")


def assert_protected(directory: Path, secret: str):
    stored = (directory / "notification_settings.json").read_text(encoding="utf-8")
    assert secret not in stored
    if IS_MACOS:
        assert '"keychain:email_password"' in stored, stored
        assert keychain_item_exists(), "notification secret is missing from the keychain"
    else:
        assert "dpapi:" in stored


def check_recovery_and_secrets(executable: Path, home: str):
    directory = data_directory(home)
    journal = OrderJournal(directory / "orders.sqlite3")
    intent = OrderIntent.from_config(CONFIG, "G101", "二等座", "alternate")
    journal.begin("offline-test", intent, CONFIG)
    journal.record(intent, OrderResult("pending_payment", order_id="TEST123", evidence={"matched": True}))
    environment = isolated_environment(home)
    for restart in (False, True):
        session = RuntimeSession(executable, environment)
        if IS_MACOS and restart:
            # The stored secret is read from the keychain off the startup path.
            credentials = session.wait_event("notificationCredentials")
            assert credentials["payload"]["status"] == "ready", credentials
        state = session.request("state", "stopMonitor")
        assert state["ok"] is True
        order = state["result"]["order"]
        assert order["stage"] == "alternate_pending_payment" and order["order_id"] == "TEST123"
        assert order["recovery_required"] is True
        config = session.request("config", "loadConfig")
        assert config["ok"] is True
        assert config["result"]["request_mode"] == "conservative"
        assert config["result"]["query_priority"] == "reliability"
        prefs = session.request("prefs", "savePreferences",
                                {"theme": "dark", "notification_settings": {"email_password": "runtime-secret"}})
        assert prefs["ok"] is True, prefs
        assert prefs["result"]["notification_settings"]["email_password"] == ""
        assert prefs["result"]["notification_settings"]["email_password_configured"] is True
        assert_protected(directory, "runtime-secret")
        start = session.request("start", "startMonitor", {"config": CONFIG, "confirmed": True})
        clear = session.request("clear", "clearLocalData", {"confirmed": True})
        assert start["ok"] is False and clear["ok"] is False
        session.close()
        assert not (directory / "chrome_profile_12306").exists()
        assert journal.pending()["result"]["order_id"] == "TEST123"
    return directory, environment


def check_unreadable_secret(executable: Path, directory: Path, environment: dict):
    """An unreadable secret disables notifications without hiding the durable order."""
    preferences_path = directory / "notification_settings.json"
    damaged = json.loads(preferences_path.read_text(encoding="utf-8"))
    damaged.update(email_enabled=True)
    if IS_MACOS:
        # The file still names the keychain slot, but the item is gone.
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
                       check=True, capture_output=True)
    else:
        damaged.update(email_password="dpapi:YWJj")
    preferences_path.write_text(json.dumps(damaged), encoding="utf-8")
    session = RuntimeSession(executable, environment)
    if IS_MACOS:
        credentials = session.wait_event("notificationCredentials")
        assert credentials["payload"]["status"] == "missing", credentials
    state = session.request("state", "stopMonitor")
    prefs = session.request("prefs", "loadPreferences")
    session.close()
    assert state["ok"] is True and prefs["ok"] is True
    assert state["result"]["order"]["order_id"] == "TEST123"
    assert state["result"]["order"]["recovery_required"] is True
    assert prefs["result"]["notification_settings"]["email_enabled"] is False
    assert prefs["result"]["notification_settings"]["email_password_configured"] is False
    assert any(message.get("event") == "log" and message["payload"].get("level") == "WARN"
               and "通知设置无法读取" in message["payload"].get("message", "") for message in session.messages)
    assert json.loads(preferences_path.read_text(encoding="utf-8")) == damaged


def check_clear_removes_secrets(executable: Path):
    """Without an unfinished order, clearing local data also removes stored secrets."""
    with tempfile.TemporaryDirectory(prefix="railwatch-runtime-clear-") as temporary:
        home = os.path.realpath(temporary)  # The clear guard rejects aliased paths such as /var -> /private/var.
        directory = data_directory(home)
        session = RuntimeSession(executable, isolated_environment(home))
        prefs = session.request("prefs", "savePreferences", {"notification_settings": {"email_password": "clear-secret"}})
        assert prefs["ok"] is True, prefs
        assert_protected(directory, "clear-secret")
        clear = session.request("clear", "clearLocalData", {"confirmed": True})
        session.close()
        assert clear["ok"] is True and clear["result"]["cleared"] is True, clear
        assert clear["result"]["warning"] == "", clear
        assert not (directory / "notification_settings.json").exists()
        if IS_MACOS:
            assert not keychain_item_exists(), "clearing local data left the keychain item behind"


def main():
    parser = argparse.ArgumentParser(description="Smoke the packaged Python runtime.")
    parser.add_argument("--exe", type=Path, default=default_executable(), help="runtime executable to test")
    executable = parser.parse_args().exe.resolve()
    if not executable.is_file():
        raise RuntimeError(f"Runtime not found at {executable}; build it with npm run build:runtime first")
    with tempfile.TemporaryDirectory(prefix="railwatch-runtime-orders-") as temporary:
        directory, environment = check_recovery_and_secrets(executable, os.path.realpath(temporary))
        check_unreadable_secret(executable, directory, environment)
    check_clear_removes_secrets(executable)
    protection = "keychain" if IS_MACOS else "DPAPI"
    print(f"Packaged runtime {executable}: restart recovery, {protection} protection, unreadable-secret fallback, "
          "duplicate-start and clear-data guards, and secret cleanup passed; no browser/network actions.")


if __name__ == "__main__":
    main()
