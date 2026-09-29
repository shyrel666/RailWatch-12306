"""Capture current production UI with synthetic data; never contact 12306."""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from railwatch_bridge import CHROMEDRIVER_PATH, state_to_payload
from railwatch_config_contract import default_config
from railwatch_query import query_snapshot
from railwatch_row_parser import RowParser
from railwatch_seats import public_seat_capabilities
from railwatch_state import RailWatchState


def main():
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    now = time.time()
    config = {**default_config(), "date_range": "单日", "train_code": "G101,G103",
              "seat_keyword": "二等座,一等座", "passengers": "演示乘客"}
    state = state_to_payload(RailWatchState.initial())
    runtime = {"app_display_name": "RailWatch 12306", "app_version": version, "state": state,
               "date_policy": {"presale_window_days": 15}, "seat_capabilities": public_seat_capabilities(),
               "data_dir": "离线演示目录", "data_dir_writable": True, "chrome_version": "离线演示",
               "core_available": True}
    summary = {"intent_id": "demo-order", "order_id": "DEMO123", "kind": "alternate",
               "train_code": "G101", "date": config["date"], "from_station": "北京", "to_station": "上海",
               "seat": "二等座", "status": "active", "official_status": "active",
               "official_verified_at": now - 300, "updated_at": now - 300,
               "last_checked_at": now - 300, "observing": False, "recovery_required": True}
    data = json.dumps({"config": config, "runtime": runtime, "summary": summary, "now": now}, ensure_ascii=False)
    bootstrap = "const {config,runtime,summary,now}=" + data + ";" + """
      let theme='light'; window.demoListeners=[];
      window.railwatch={command:async(name,payload={})=>{
        if(name==='getRuntimeInfo') return runtime;
        if(name==='loadTripState') return {saved_config:config,saved_at:now-600,
          draft:{status:'available',draft:{schema_version:1,revision:2,saved_at:now-120,
            config:{from_station_cn:'北京南',train_code:'G103',auto_submit:false}},warning:null}};
        if(name==='loadTripChoices') return {recent_routes:[{from_station:'北京',to_station:'上海'}],
          favorites:[{from_station:'北京',to_station:'上海',trains:['G101','G103']}]};
        if(name==='loadPreferences') return {theme,close_to_tray:false,notification_settings:{}};
        if(name==='savePreferences') {theme=payload.theme||theme;return {theme,notification_settings:{}};}
        if(name==='searchStations') return {items:[],warning:null};
        if(name==='orderHistory') return {items:[summary],next_cursor:null};
        if(name==='orderDetail') return {summary,history_complete:false,events:[]};
        if(name==='saveTripDraft') return {schema_version:1,revision:payload.revision,saved_at:now,config:payload.config};
        return {};
      },stageDraft:()=>{},onEvent:fn=>{window.demoListeners.push(fn);return ()=>{};},
      onConfirmRequest:()=>()=>{},onUpdateState:()=>()=>{},stopUrgentAlert:()=>{},
      respondConfirmation:()=>{},openExternal:async()=>({ok:true}),
      getUpdateState:async()=>({phase:'idle',currentVersion:runtime.app_version}),getAppInfo:async()=>({appVersion:runtime.app_version})};
      window.demoEmit=(event,payload)=>window.demoListeners.forEach(fn=>fn({event,payload}));
    """

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="railwatch-readme-", ignore_cleanup_errors=True) as profile:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-background-networking")
            options.add_argument(f"--user-data-dir={profile}")
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
            try:
                driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                    "width": 1600, "height": 1100, "deviceScaleFactor": 1, "mobile": False})
                driver.execute_cdp_cmd("Network.enable", {})
                driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": bootstrap})
                driver.get(f"http://127.0.0.1:{server.server_port}/")
                wait = WebDriverWait(driver, 15)
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 6)

                def capture(name):
                    driver.execute_script("document.querySelector('.page-surface').scrollTop=0")
                    time.sleep(0.3)
                    assert driver.execute_script("return document.documentElement.scrollWidth<=innerWidth")
                    driver.save_screenshot(str(ROOT / "docs/images" / f"{name}-v{version}.png"))

                driver.find_element("css selector", '[aria-label="行程设置"]').click()
                wait.until(lambda d: "恢复草稿" in d.find_element("tag name", "body").text)
                capture("trip-setup")
                driver.find_element("css selector", '[aria-label="订单中心"]').click()
                wait.until(lambda d: "DEMO123" in d.find_element("tag name", "body").text)
                capture("order-center")
                driver.find_element("css selector", '[aria-label="购票监控"]').click()
                driver.find_element("css selector", '[aria-label*="主题"]').click()
                wait.until(lambda d: d.execute_script("return document.documentElement.dataset.theme") == "dark")
                active = {**state, "monitoring": True, "current_config": config,
                          "task": {"run_id": "readme-demo", "status": "backoff", "sequence": 1,
                                   "started_at": now-90, "next_query_at": time.time()+120}}
                driver.execute_script("window.demoEmit('state',arguments[0])", active)
                rows = RowParser.structured_rows([
                    {"train": train, "raw": "离线演示数据，不作为真实余票依据", "from_station": "北京南",
                     "to_station": "上海虹桥", "departure_time": departure, "arrival_time": arrival,
                     "arrival_day_offset": 0, "seats": {"二等座": seats, "一等座": "候补", "商务座": "无"}}
                    for train, departure, arrival, seats in [("G101", "06:43", "12:40", "3"), ("G103", "07:12", "13:10", "候补")]
                ], config["date"])
                snapshot = query_snapshot(config, rows, run_id="readme-demo", query_id="demo-query", sequence=1)
                driver.execute_script("window.demoEmit('monitorTick',arguments[0])", {
                    "run_id": "readme-demo", "loop": 1, "date": config["date"], "rows": rows, "snapshot": snapshot})
                wait.until(lambda d: len(d.find_elements("css selector", ".query-date-group")) == 1)
                capture("monitor")
            finally:
                driver.quit()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print("README screenshots captured from production UI with isolated synthetic data.")


if __name__ == "__main__":
    main()
