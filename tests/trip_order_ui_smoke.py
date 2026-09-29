"""Offline M4/M5 renderer smoke with synthetic draft and order evidence."""

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import sys

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_config_contract import default_config
from railwatch_state import RailWatchState
from railwatch_bridge import state_to_payload
from railwatch_seats import public_seat_capabilities

OUTPUT = ROOT / "build" / "qa" / "m4-m5"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = {**default_config(), "date_range": "单日", "train_code": "G101", "seat_keyword": "二等座",
              "passengers": "张三"}
    runtime = {"app_display_name": "RailWatch 12306", "app_version": "0.4.2", "pages": [],
               "state": state_to_payload(RailWatchState.initial()), "date_policy": {"presale_window_days": 15},
               "seat_capabilities": public_seat_capabilities(), "data_dir": "离线演示目录",
               "data_dir_writable": True, "chrome_version": "本地夹具", "core_available": True}
    summary = {"intent_id": "demo-intent", "order_id": "E123", "kind": "alternate", "train_code": "G101",
               "date": config["date"], "from_station": "北京", "to_station": "上海", "seat": "二等座",
               "status": "active", "official_status": "active", "official_verified_at": 1790200000,
               "updated_at": 1790200001, "last_checked_at": 1790200000, "observing": False,
               "recovery_required": True}
    script = """
      const config=CONFIG, runtime=RUNTIME, summary=SUMMARY;
      window.railwatch={
        command: async (name,payload={})=>{
          if(name==='getRuntimeInfo')return runtime;
          if(name==='loadTripState')return {saved_config:config,saved_at:100,
            draft:{status:'available',draft:{schema_version:1,revision:2,saved_at:1790200000,
              config:{from_station_cn:'北京南',train_code:'G102',auto_submit:false}},warning:null}};
          if(name==='loadTripChoices')return {recent_routes:[{from_station:'北京',to_station:'上海'}],
            favorites:[{from_station:'北京',to_station:'上海',trains:['G101','G103']}]};
          if(name==='searchStations')return {items:[],warning:null};
          if(name==='loadPreferences')return {theme:'light',close_to_tray:false,notification_settings:{}};
          if(name==='savePreferences')return {theme:payload.theme||'light',close_to_tray:false,notification_settings:{}};
          if(name==='orderHistory')return {items:[summary],next_cursor:null};
          if(name==='orderDetail')return {summary,history_complete:false,events:[]};
          if(name==='saveTripDraft')return {schema_version:1,revision:payload.revision,saved_at:Date.now()/1000,config:payload.config};
          return {};
        },
        stageDraft:()=>{},onEvent:()=>()=>{},onConfirmRequest:()=>()=>{},onUpdateState:()=>()=>{},
        getUpdateState:async()=>({phase:'idle',currentVersion:'0.4.2'}),
        getAppInfo:async()=>({appVersion:'0.4.2'}),stopUrgentAlert:()=>{},
        respondConfirmation:()=>{},openExternal:async()=>({ok:true})
      };
    """.replace("CONFIG", json.dumps(config, ensure_ascii=False)).replace("RUNTIME", json.dumps(runtime, ensure_ascii=False)).replace("SUMMARY", json.dumps(summary, ensure_ascii=False))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    driver = None
    try:
        with tempfile.TemporaryDirectory(prefix="railwatch-m4m5-ui-", ignore_cleanup_errors=True) as profile:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-background-networking")
            options.add_argument(f"--user-data-dir={profile}")
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
            for width, height in ((1440, 900), (1180, 720)):
                driver.set_window_size(width, height)
                driver.get(f"http://127.0.0.1:{server.server_port}/")
                wait = WebDriverWait(driver, 12)
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 6)
                driver.find_element("css selector", '[aria-label="行程设置"]').click()
                wait.until(lambda d: "恢复草稿" in d.find_element("tag name", "body").text)
                assert "本路线收藏" in driver.find_element("tag name", "body").text
                driver.save_screenshot(str(OUTPUT / f"trip-{width}.png"))
                driver.find_element("css selector", "#trip-automation summary").click()
                deadline = driver.find_element("css selector", '[aria-label="候补截止"]')
                deadline.click()
                option = wait.until(lambda d: d.find_element("xpath", "//div[contains(@class,'ant-select-item-option-content') and text()='开车前20分钟']"))
                driver.save_screenshot(str(OUTPUT / f"deadline-options-{width}.png"))
                option.click()
                assert deadline.get_attribute("value") == "开车前20分钟"
                driver.find_element("css selector", '[aria-label="订单中心"]').click()
                wait.until(lambda d: "E123" in d.find_element("tag name", "body").text)
                assert "当前不会周期性自动复查" in driver.find_element("tag name", "body").text
                assert driver.execute_script("return document.querySelector('.page-surface').scrollWidth <= document.querySelector('.page-surface').clientWidth + 1")
                driver.save_screenshot(str(OUTPUT / f"orders-{width}.png"))
    finally:
        if driver:
            driver.quit()
        server.shutdown()
    print("M4/M5 offline UI smoke passed: draft recovery, route favorites, order history, two window sizes.")


if __name__ == "__main__":
    main()
