"""Verify frozen-runtime multi-choice recovery in an isolated data directory."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_alternate_plan import AlternateChoice
from railwatch_config_contract import default_config
from railwatch_orders import OrderIntent, OrderJournal, OrderResult


def main():
    executable = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build/qa/efficiency-phase2/runtime/railwatch_runtime.exe"
    if not executable.is_file():
        raise RuntimeError("Build the phase-two runtime first, or pass its path")
    with tempfile.TemporaryDirectory(prefix="railwatch-multi-runtime-") as temporary:
        directory = Path(temporary) / "railwatch-12306"
        journal = OrderJournal(directory / "orders.sqlite3")
        config = {**default_config(), "from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-10-10",
                  "train_code": "G101,G102", "seat_keyword": "二等座", "passengers": "测试乘客",
                  "alternate_mode": "multiple", "alternate_max_combinations": 8,
                  "order_watch_enabled": True, "order_watch_interval_seconds": 120}
        intent = OrderIntent.from_config(config, "G101", "二等座", "alternate")
        primary = AlternateChoice.from_intent(intent)
        journal.begin("offline-runtime", intent, config)
        intent = replace(intent, choices=(primary, replace(primary, train_code="G102"), replace(primary, date="2026-10-09")))
        journal.bind_alternatives(intent)
        journal.mark("offline-runtime", "alternate_submit", intent.intent_id)
        journal.record(intent, OrderResult("active", order_id="OFFLINE123", evidence={"matched": True}))
        requests = [
            {"id": "state", "command": "stopMonitor"},
            {"id": "defaults", "command": "loadConfig"},
            {"id": "save", "command": "saveConfig", "payload": {"config": config}},
            {"id": "history", "command": "orderHistory"},
            {"id": "detail", "command": "orderDetail", "payload": {"intent_id": intent.intent_id}},
            {"id": "start", "command": "startMonitor", "payload": {"config": config, "confirmed": True}},
            {"id": "clear", "command": "clearLocalData", "payload": {"confirmed": True}},
        ]
        stdin = "".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests)
        environment = dict(os.environ, LOCALAPPDATA=temporary, APPDATA=temporary)
        for boot in range(2):
            completed = subprocess.run([str(executable)], input=stdin, text=True, encoding="utf-8",
                                       capture_output=True, timeout=40, env=environment,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert completed.returncode == 0, completed.stderr
            messages = [json.loads(line) for line in completed.stdout.splitlines() if line.strip().startswith("{")]
            responses = {message["id"]: message for message in messages if message.get("type") == "response"}
            for name in ("state", "defaults", "save", "history", "detail"):
                assert responses[name]["ok"], responses[name]
            state = responses["state"]["result"]
            assert not state["monitoring"] and state["order"]["recovery_required"]
            assert state["order"]["order_id"] == "OFFLINE123"
            assert state["order"]["intent"]["choices"] == [asdict(choice) for choice in intent.choices]
            defaults = responses["defaults"]["result"]
            assert defaults["alternate_mode"] == ("single" if boot == 0 else "multiple")
            assert defaults["order_watch_interval_seconds"] == (60 if boot == 0 else 120)
            assert defaults["order_watch_enabled"]
            history = responses["history"]["result"]["items"][0]
            assert history["choices"] == state["order"]["intent"]["choices"]
            assert history["status"] == "active" and not history["observing"] and history["next_check_at"] is None
            assert responses["detail"]["result"]["summary"]["choices"] == history["choices"]
            assert responses["start"]["ok"] is False and responses["clear"]["ok"] is False
            assert not (directory / "chrome_profile_12306").exists()
            assert OrderIntent.from_dict(journal.pending()["intent"]) == intent
    print("Frozen runtime passed: policy resources, saved settings, exact multi-choice recovery across two boots, no automatic browser/start/replay.")


if __name__ == "__main__":
    main()
