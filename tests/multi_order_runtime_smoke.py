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
                  "train_code": "K101,K102", "seat_keyword": "硬卧,软卧", "passengers": "测试乘客",
                  "alternate_mode": "multiple", "alternate_max_combinations": 8,
                  "alternate_deadline": "开车前1小时", "alternate_accept_new_trains": True,
                  "alternate_new_train_windows": [{"date": "2026-10-10", "start_hour": 8, "end_hour": 22}],
                  "order_watch_enabled": True, "order_watch_interval_seconds": 120}
        intent = OrderIntent.from_config(config, "K101", "硬卧", "alternate")
        primary = AlternateChoice.from_intent(intent)
        journal.begin("offline-runtime", intent, config)
        intent = replace(intent, choices=(primary, replace(primary, train_code="K102", seat="软卧"), replace(primary, date="2026-10-09")))
        journal.bind_alternatives(intent)
        journal.mark("offline-runtime", "alternate_submit", intent.intent_id)
        review = {"source": "official_page", "success_rate": 0, "success_rate_status": "available",
                  "success_rate_observed_at": 1791500000, "prepay_amount": "661.00", "amount_observed_at": 1791500000}
        options = {"source": "official_page", "observed_at": 1791500000, "from_station": "北京", "to_station": "上海",
                   "dates": [config["date"]], "deadline_options": ["开车前20分钟", "开车前1小时", "开车前3天"]}
        journal.mark("offline-runtime", "alternate_options", intent.intent_id, options)
        journal.record(intent, OrderResult("active", order_id="OFFLINE123", evidence={"matched": True}, review=review))
        requests = [
            {"id": "runtime", "command": "getRuntimeInfo"},
            {"id": "state", "command": "stopMonitor"},
            {"id": "defaults", "command": "loadConfig"},
            {"id": "save", "command": "saveConfig", "payload": {"config": config}},
            {"id": "history", "command": "orderHistory"},
            {"id": "detail", "command": "orderDetail", "payload": {"intent_id": intent.intent_id}},
            {"id": "options", "command": "readAlternateOptions"},
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
            for name in ("runtime", "state", "defaults", "save", "history", "detail", "options"):
                assert responses[name]["ok"], responses[name]
            assert [seat["name"] for seat in responses["runtime"]["result"]["seat_capabilities"] if seat["alternate"]] == [
                "二等座", "一等座", "硬座", "软座", "硬卧", "软卧"]
            state = responses["state"]["result"]
            assert not state["monitoring"] and state["order"]["recovery_required"]
            assert state["order"]["order_id"] == "OFFLINE123"
            assert state["order"]["intent"]["choices"] == [asdict(choice) for choice in intent.choices]
            assert state["order"]["intent"]["new_train_windows"] == config["alternate_new_train_windows"]
            assert state["order"]["intent"]["deadline"] == config["alternate_deadline"]
            assert state["order"]["review"] == review
            assert responses["options"]["result"]["snapshot"] == options
            defaults = responses["defaults"]["result"]
            assert defaults["alternate_mode"] == ("single" if boot == 0 else "multiple")
            assert defaults["order_watch_interval_seconds"] == (60 if boot == 0 else 120)
            assert defaults["order_watch_enabled"]
            assert defaults["alternate_accept_new_trains"] == (boot > 0)
            assert defaults["alternate_new_train_windows"] == ([] if boot == 0 else config["alternate_new_train_windows"])
            history = responses["history"]["result"]["items"][0]
            assert history["choices"] == state["order"]["intent"]["choices"]
            assert history["new_train_windows"] == config["alternate_new_train_windows"]
            assert history["review"] == review
            assert history["status"] == "active" and not history["observing"] and history["next_check_at"] is None
            assert responses["detail"]["result"]["summary"]["choices"] == history["choices"]
            assert responses["start"]["ok"] is False and responses["clear"]["ok"] is False
            assert not (directory / "chrome_profile_12306").exists()
            assert OrderIntent.from_dict(journal.pending()["intent"]) == intent
    print("Frozen runtime passed: policy resources, saved cutoff/options/windows/rate, exact multi-choice recovery across two boots, no automatic browser/start/replay.")


if __name__ == "__main__":
    main()
