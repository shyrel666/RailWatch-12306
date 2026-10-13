"""Offline M4/M5 renderer smoke with synthetic draft and order evidence."""

import json
import time
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
    # Alternate deadline options are only rendered once automatic alternate is enabled.
    config = {**default_config(), "date_range": "单日", "train_code": "K101", "seat_keyword": "硬卧，软卧",
              "passengers": "张三", "auto_alternate": True, "alternate_accept_new_trains": True,
              "alternate_new_train_windows": [{"date": default_config()["date"], "start_hour": 8, "end_hour": 22}]}
    runtime = {"app_display_name": "RailWatch 12306", "app_version": "0.4.2", "pages": [],
               "state": state_to_payload(RailWatchState.initial()), "date_policy": {"presale_window_days": 15},
               "seat_capabilities": public_seat_capabilities(), "data_dir": "离线演示目录",
               "data_dir_writable": True, "chrome_version": "本地夹具", "core_available": True}
    summary = {"intent_id": "demo-intent", "order_id": "E123", "kind": "alternate", "train_code": "K101",
               "date": config["date"], "from_station": "北京", "to_station": "上海", "seat": "硬卧",
               "choices": [{"train_code": "K101", "date": config["date"], "from_station": "北京", "to_station": "上海", "seat": seat}
                           for seat in ("硬卧", "软卧")],
               "status": "active", "official_status": "active", "official_verified_at": 1790200000,
               "updated_at": 1790200001, "last_checked_at": 1790200000, "observing": False,
               "recovery_required": True, "deadline": "开车前1小时", "new_train_windows": config["alternate_new_train_windows"],
               "review": {"success_rate": 40, "success_rate_status": "available", "success_rate_observed_at": time.time(),
                          "prepay_amount": "661.00", "amount_observed_at": time.time()}}
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
          if(name==='readAlternateOptions')return {snapshot:{source:'official_page',from_station:'北京',to_station:'上海',
            dates:[config.date],observed_at:Date.now()/1000,deadline_options:['开车前20分钟','开车前1小时','开车前3天']},warning:null};
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
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 7
                           and not d.find_elements("id", "startup-splash"))
                driver.find_element("css selector", '[aria-label="行程设置"]').click()
                wait.until(lambda d: "恢复草稿" in d.find_element("tag name", "body").text)
                assert driver.find_elements("xpath", "//button[normalize-space(.)='收藏']")
                seat_buttons = {button.text: button for button in driver.find_elements("css selector", '[aria-label="席别"] button')}
                # Seats without automation carry a "仅提醒" mark; automated seats show the bare name.
                for seat in ("二等座", "一等座", "硬座", "软座", "硬卧", "软卧"):
                    assert seat in seat_buttons
                assert any(text.startswith("商务座") and "仅提醒" in text for text in seat_buttons)
                driver.save_screenshot(str(OUTPUT / f"trip-{width}.png"))
                driver.find_element("css selector", "#trip-automation button[aria-haspopup='dialog']").click()
                wait.until(lambda d: any(e.is_displayed() for e in d.find_elements("css selector", ".automation-dialog")))
                assert "卧铺候补的上／中／下铺由官网分配" in driver.find_element("tag name", "body").text
                deadline = driver.find_element("css selector", '[aria-label="截止兑现时间"]')
                deadline.click()
                option = wait.until(lambda d: d.find_element("xpath", "//div[contains(@class,'ant-select-item-option-content') and text()='开车前20分钟']"))
                wait.until(lambda d: d.execute_script("return [...document.querySelectorAll('.ant-select-dropdown')].some(e=>e.getClientRects().length&&getComputedStyle(e).opacity==='1')"))
                driver.save_screenshot(str(OUTPUT / f"deadline-options-{width}.png"))
                option.click()
                wait.until(lambda d: not any(item.is_displayed() for item in d.find_elements(
                    "css selector", ".ant-select-dropdown")))
                assert "开车前20分钟" in driver.find_element("css selector", ".alternate-settings").text
                assert deadline.get_attribute("readonly")
                driver.execute_script("document.querySelector('.alternate-window').scrollIntoView({block:'center'})")
                driver.save_screenshot(str(OUTPUT / f"new-trains-{width}.png"))
                driver.find_element("css selector", ".automation-dialog .ant-modal-footer .ant-btn-primary").click()
                wait.until(lambda d: not any(e.is_displayed() for e in d.find_elements("css selector", ".automation-dialog")))
                driver.find_element("css selector", '[aria-label="订单中心"]').click()
                wait.until(lambda d: "E123" in d.find_element("tag name", "body").text)
                assert "当前未持续核对" in driver.find_element("tag name", "body").text
                review = driver.find_element("css selector", ".order-history-item .alternate-review").text
                assert "预估成功率\n40%" in review and "预付款\n661.00 元" in review
                assert driver.execute_script("return document.querySelector('.page-surface').scrollWidth <= document.querySelector('.page-surface').clientWidth + 1")
                driver.save_screenshot(str(OUTPUT / f"orders-{width}.png"))
    finally:
        if driver:
            driver.quit()
        server.shutdown()
    print("Offline UI smoke passed: draft recovery, route favorites, official cutoff options, new-train windows, official rate/amount, order history, two window sizes.")


if __name__ == "__main__":
    main()
