"""Run a read-only rehearsal in a dedicated tab of the existing idle browser.

Uses a temporary journal/settings directory. Never sends external notifications,
submits an official order, writes account/config data, or closes existing tabs.
The caller must leave the desktop idle for the duration of this diagnostic.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import RailWatchBridge, CHROMEDRIVER_PATH
from railwatch_config_contract import validate_config, parse_passenger_names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    directory = Path(os.environ["LOCALAPPDATA"]) / "railwatch-12306"
    config = validate_config(json.loads((directory / "user_config.json").read_text(encoding="utf-8")))
    def counts():
        with sqlite3.connect((directory / "orders.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("SELECT count(*) FROM orders WHERE unresolved=1").fetchone()[0]:
                raise RuntimeError("Unresolved order; diagnostic refused")
            latest = db.execute("SELECT max(at) FROM order_events WHERE stage IN ('query_click','target_sale','regular_submit','alternate_submit')").fetchone()[0]
            if latest and time.time() - latest < 120:
                raise RuntimeError("Recent task activity; diagnostic refused")
            return [db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("orders", "order_events")]
    before = counts()
    port = args.port or int((directory / "chrome_profile_12306/DevToolsActivePort").read_text().splitlines()[0])
    service = Service(CHROMEDRIVER_PATH)
    options = webdriver.ChromeOptions()
    options.debugger_address = f"127.0.0.1:{port}"
    driver = webdriver.Chrome(service=service, options=options)
    original = driver.current_window_handle
    original_url = driver.current_url
    owned = None
    try:
        driver.switch_to.new_window("tab")
        owned = driver.current_window_handle
        with tempfile.TemporaryDirectory(prefix="railwatch-live-rehearsal-") as temporary:
            bridge = RailWatchBridge(temporary)
            bridge.driver = driver
            # Detach on a lost diagnostic session; this process does not own Chrome.
            bridge._release_driver = lambda: setattr(bridge, "driver", None)
            try:
                started = time.monotonic()
                report = bridge._run_rehearsal(config, threading.Event())
                serialized = json.dumps(report, ensure_ascii=False)
                if any(name in serialized for name in parse_passenger_names(config.get("passengers", ""))):
                    raise AssertionError("Report contains an unmasked passenger name")
                with bridge.order_journal.connection() as db:
                    local = [db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("orders", "order_events")]
                assert local == [0, 0]
                assert counts() == before
                print(json.dumps({"elapsed_s": round(time.monotonic() - started, 2), "verdict": report["verdict"],
                                  "checks": [{"id": c["id"], "status": c["status"], "summary": c["summary"], "duration_ms": c["duration_ms"]} for c in report["checks"]],
                                  "local_order_counts": local, "production_order_counts_unchanged": True}, ensure_ascii=False))
            finally:
                bridge.notification_service.close()
    finally:
        try:
            # Only diagnostic tabs created by this session may be closed.
            if owned is not None and owned in driver.window_handles:
                driver.switch_to.window(owned)
                driver.close()
            driver.switch_to.window(original)
            assert driver.current_url == original_url
        finally:
            service.stop()  # Do not call driver.quit() on an attached browser.


if __name__ == "__main__":
    main()
