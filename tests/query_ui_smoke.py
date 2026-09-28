"""Render M1 production UI with local synthetic events; no account or railway traffic."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from railwatch_bridge import CHROMEDRIVER_PATH, state_to_payload
from railwatch_config_contract import default_config
from railwatch_dates import expand_travel_dates
from railwatch_query import query_snapshot
from railwatch_row_parser import RowParser
from railwatch_state import RailWatchState

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "qa" / "m1"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = {**default_config(), "train_code": "G101", "seat_keyword": "二等座,一等座", "date_range": "±1天"}
    state = state_to_payload(RailWatchState.initial())
    runtime = {"app_display_name": "RailWatch 12306", "app_version": "0.4.2", "pages": [], "state": state,
               "data_dir": "演示目录", "data_dir_writable": True, "chrome_version": "离线演示", "core_available": True}
    bootstrap = """
      const config = CONFIG, runtime = RUNTIME;
      window.testEvents = [];
      window.railwatch = {
        command: async (command, payload) => {
          if (command === 'loadConfig') return config;
          if (command === 'loadTripState') return {saved_config:config,saved_at:Date.now()/1000,draft:{status:'missing',draft:null,warning:null}};
          if (command === 'loadTripChoices') return {recent_routes:[],favorites:[]};
          if (command === 'searchStations') return {items:[],warning:null};
          if (command === 'getRuntimeInfo') return runtime;
          if (command === 'loadPreferences') return {theme:'light'};
          if (command === 'savePreferences') return {theme:payload.theme};
          return {};
        },
        onEvent: listener => { window.testEvents.push(listener); return () => {}; },
        stageDraft: () => {},
        onConfirmRequest: () => () => {}, onUpdateState: () => () => {},
        getUpdateState: async () => ({phase:'idle',currentVersion:'0.4.2'}),
        getAppInfo: async () => ({appVersion:'0.4.2'}), stopUrgentAlert: () => {},
        respondConfirmation: () => {}, openExternal: async () => ({ok:true})
      };
      window.emitTestEvent = (event, payload) => window.testEvents.forEach(fn => fn({event,payload}));
    """.replace("CONFIG", json.dumps(config, ensure_ascii=False)).replace("RUNTIME", json.dumps(runtime, ensure_ascii=False))
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = None
    try:
        with tempfile.TemporaryDirectory(prefix="railwatch-query-ui-") as profile:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-background-networking")
            options.add_argument(f"--user-data-dir={profile}")
            options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
            try:
                driver.execute_cdp_cmd("Network.enable", {})
                driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": bootstrap})
                driver.get(f"http://127.0.0.1:{server.server_port}/")
                wait = WebDriverWait(driver, 10)
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 6)
                wait.until(lambda d: d.execute_script("return window.testEvents.length > 0"))
                driver.find_element("css selector", '[aria-label="购票监控"]').click()
                wait.until(lambda d: "G101" in d.find_element("tag name", "body").text)
                now = time.time()
                active = {**state, "monitoring": True, "current_config": config,
                          "task": {"run_id": "ui-demo", "status": "backoff", "sequence": 1, "next_query_at": now + 120}}
                driver.execute_script("window.emitTestEvent('state',arguments[0])", active)
                snapshots = []
                for seq, date in enumerate(expand_travel_dates(config["date"], "±1天")[:2], 1):
                    rows = RowParser.structured_rows([{"train": "G101", "raw": "本地演示页面信息；不作为真实余票依据", "from_station": "北京南", "to_station": "上海虹桥",
                      "departure_time": "23:00", "arrival_time": "07:00", "arrival_day_offset": 1,
                      "seats": {"二等座": "3", "一等座": "无", "商务座": "候补", "无座": "--",
                                "特等座": "--", "硬座": "不适用", "软座": "--", "硬卧": "--",
                                "软卧": "--", "高级软卧": "--", "动卧": "--"}}], date)
                    snapshot = query_snapshot({**config, "date": date}, rows, run_id="ui-demo", query_id=f"ui-{seq}", sequence=seq, fetched_at=now - seq)
                    snapshots.append(snapshot)
                    driver.execute_script("window.emitTestEvent('monitorTick',arguments[0])", {"run_id": "ui-demo", "loop": seq, "date": date, "rows": rows, "snapshot": snapshot})
                failed = query_snapshot({**config, "date": snapshots[0]["conditions"]["date"]}, [], run_id="ui-demo", query_id="ui-3", sequence=3, error="查询超时，保留上次成功结果")
                driver.execute_script("window.emitTestEvent('monitorTick',arguments[0])", {"run_id": "ui-demo", "loop": 3, "date": failed["conditions"]["date"], "rows": [], "snapshot": failed})
                wait.until(lambda d: len(d.find_elements("css selector", ".query-date-group")) == 2)
                assert len(driver.find_elements("css selector", ".query-seat--available")) == 2
                assert "本轮查询失败" in driver.find_element("css selector", ".st-results-panel").text
                measurements = []
                for theme in ("light", "dark"):
                    if theme == "dark":
                        # Exercise the real persisted-theme control.
                        driver.find_element("css selector", '[aria-label*="主题"]').click()
                        wait.until(lambda d: d.execute_script("return document.documentElement.dataset.theme") == "dark")
                    for width, height in ((1440, 900), (1180, 720)):
                        driver.set_window_size(width, height)
                        driver.execute_script("document.querySelector('.st-results-panel').scrollIntoView({block:'start'})")
                        time.sleep(0.2)
                        measure = driver.execute_script("""const p=document.querySelector('.st-results-panel');
                          return {innerWidth,innerHeight,panelWidth:p.clientWidth,panelScroll:p.scrollWidth,
                            pageWidth:document.documentElement.clientWidth,pageScroll:document.documentElement.scrollWidth};""")
                        assert measure["panelScroll"] <= measure["panelWidth"] + 1, measure
                        assert measure["pageScroll"] <= measure["pageWidth"] + 1, measure
                        measurements.append({"theme": theme, **measure})
                        driver.save_screenshot(str(OUTPUT / f"query-{theme}-{width}.png"))
                errors = [item for item in driver.get_log("browser") if item["level"] == "SEVERE" and "favicon.ico" not in item["message"]]
                assert not errors, errors
                (OUTPUT / "ui-report.json").write_text(json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8")
                print("M1 UI smoke passed: two dates, retained failed result, 4 theme/size combinations, no page overflow.")
            finally:
                driver.quit()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
