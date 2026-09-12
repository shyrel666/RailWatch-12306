"""Verify the built runtime restores SQLite orders without opening Chrome."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_orders import OrderIntent, OrderJournal, OrderResult


def main():
    executable = ROOT / "dist-runtime" / "railwatch_runtime.exe"
    if not executable.is_file():
        raise RuntimeError("Build the runtime with npm run build:runtime first")
    with tempfile.TemporaryDirectory(prefix="railwatch-runtime-orders-") as temporary:
        directory = Path(temporary) / "railwatch-12306"
        journal = OrderJournal(directory / "orders.sqlite3")
        config = {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-09-10",
                  "train_code": "G101", "seat_keyword": "二等座", "passengers": "测试乘客"}
        intent = OrderIntent.from_config(config, "G101", "二等座", "alternate")
        journal.begin("offline-test", intent, config)
        journal.record(intent, OrderResult("pending_payment", order_id="TEST123", evidence={"matched": True}))
        requests = [
            {"id": "state", "command": "stopMonitor"},
            {"id": "config", "command": "loadConfig"},
            {"id": "start", "command": "startMonitor", "payload": {"config": config, "confirmed": True}},
            {"id": "clear", "command": "clearLocalData", "payload": {"confirmed": True}},
        ]
        stdin = "".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests)
        environment = dict(os.environ, LOCALAPPDATA=temporary, APPDATA=temporary)
        for _ in range(2):
            completed = subprocess.run([str(executable)], input=stdin, text=True, encoding="utf-8",
                                       capture_output=True, timeout=40, env=environment,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode:
                raise RuntimeError(completed.stderr)
            messages = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
            responses = {message["id"]: message for message in messages if message.get("type") == "response"}
            assert responses["state"]["ok"] is True
            order = responses["state"]["result"]["order"]
            assert order["stage"] == "alternate_pending_payment" and order["order_id"] == "TEST123"
            assert order["recovery_required"] is True
            assert responses["config"]["ok"] is True
            assert responses["config"]["result"]["request_mode"] == "conservative"
            assert responses["config"]["result"]["query_priority"] == "reliability"
            assert responses["start"]["ok"] is False and responses["clear"]["ok"] is False
            assert not (directory / "chrome_profile_12306").exists()
            assert journal.pending()["result"]["order_id"] == "TEST123"
    print("Packaged runtime: two restarts, SQLite recovery, duplicate-start and clear-data guards passed; no browser/network actions.")


if __name__ == "__main__":
    main()
