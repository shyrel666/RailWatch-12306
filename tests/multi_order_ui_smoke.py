"""Offline production-renderer acceptance for multi-choice and order observation."""
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_bridge import CHROMEDRIVER_PATH, state_to_payload
from railwatch_config_contract import default_config
from railwatch_seats import public_seat_capabilities
from railwatch_state import RailWatchState


def main():
    output = ROOT / "build/qa/efficiency-phase2/ui"
    output.mkdir(parents=True, exist_ok=True)
    config = {**default_config(), "date": (date.today() + timedelta(days=3)).isoformat(),
              "date_range": "±1天", "train_code": "G101,G102", "seat_keyword": "二等座", "passengers": "张三"}
    runtime = {"app_display_name": "RailWatch 12306", "app_version": "0.5.3", "pages": [],
               "state": state_to_payload(RailWatchState.initial()), "date_policy": {"presale_window_days": 15},
               "seat_capabilities": public_seat_capabilities(), "data_dir": "离线演示目录",
               "data_dir_writable": True, "chrome_version": "本地夹具", "core_available": True}
    summary = {"intent_id": "offline-multi", "order_id": "E123456", "kind": "alternate", "train_code": "G101",
               "date": config["date"], "from_station": "北京", "to_station": "上海", "seat": "二等座",
               "status": "active", "official_status": "active", "official_verified_at": 1791086400,
               "updated_at": 1791086400, "last_checked_at": 1791086400, "observing": False,
               "recovery_required": True, "choices": [
                   {"train_code": train, "date": config["date"], "from_station": "北京", "to_station": "上海", "seat": "二等座"}
                   for train in ("G101", "G102")]}
    script = """
      const initial=CONFIG, runtime=RUNTIME, summary=SUMMARY;
      let config=JSON.parse(localStorage.getItem('qa-config')||'null')||initial, listener=()=>{}, sequence=0;
      window.qa={commands:[], observe(active){
        Object.assign(summary,{observing:active,next_check_at:active?Date.now()/1000+120:null,check_failures:active?2:0});
        Object.assign(runtime.state,{monitoring:active,current_config:config,
          task:{run_id:'offline-observer',status:active?'active':'stopped',sequence:++sequence},
          activity:{state:active?'busy':'idle',unresolved_order:true},
          order:{status:'active',label:'候补已生效',order_id:summary.order_id,updated_at:Date.now()/1000,
            observing:active,recovery_required:false,intent:{...summary,choices:summary.choices}}});
        listener({event:'state',payload:structuredClone(runtime.state)});
      }};
      window.railwatch={
        command: async (name,payload={})=>{
          qa.commands.push(name);
          if(name==='getRuntimeInfo')return runtime;
          if(name==='loadTripState')return {saved_config:config,saved_at:100,draft:{status:'missing'}};
          if(name==='loadTripChoices')return {recent_routes:[],favorites:[]};
          if(name==='searchStations')return {items:[],warning:null};
          if(name==='loadPreferences')return {theme:localStorage.getItem('qa-theme')||'light',notification_settings:{}};
          if(name==='orderHistory')return {items:[structuredClone(summary)],next_cursor:null};
          if(name==='runReviews')return {items:[],next_cursor:null};
          if(name==='saveConfig'){config=payload.config;localStorage.setItem('qa-config',JSON.stringify(config));return config;}
          if(name==='saveTripDraft')return {schema_version:1,revision:payload.revision,saved_at:Date.now()/1000,config:payload.config};
          if(name==='stopMonitor'){qa.observe(false);return structuredClone(runtime.state);}
          if(name==='continueOrder'){qa.observe(true);return structuredClone(runtime.state);}
          return {};
        },
        stageDraft:()=>{},onEvent:fn=>{listener=fn;return ()=>{}},onConfirmRequest:()=>()=>{},onUpdateState:()=>()=>{},
        getUpdateState:async()=>({phase:'idle',currentVersion:'0.5.3'}),
        getAppInfo:async()=>({appVersion:'0.5.3'}),stopUrgentAlert:()=>{},respondConfirmation:()=>{}
      };
    """
    for key, value in (("CONFIG", config), ("RUNTIME", runtime), ("SUMMARY", summary)):
        script = script.replace(key, json.dumps(value, ensure_ascii=False))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = None
    try:
        with tempfile.TemporaryDirectory(prefix="railwatch-multi-ui-", ignore_cleanup_errors=True) as profile:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-background-networking")
            options.add_argument(f"--user-data-dir={profile}")
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
            url = f"http://127.0.0.1:{server.server_port}/"
            wait = WebDriverWait(driver, 12)

            def click(element):
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", element)
                element.click()

            def button(text):
                click(wait.until(lambda d: d.find_element("xpath", f"//button[normalize-space(.)='{text}']")))

            def automation():
                driver.find_element("css selector", '[aria-label="行程设置"]').click()
                section = wait.until(lambda d: d.find_element("id", "trip-automation"))
                if not section.get_attribute("open"):
                    click(section.find_element("css selector", "summary"))
                return wait.until(lambda d: d.find_element("css selector", '[aria-label="候补组合"]'))

            def capture(name):
                assert driver.execute_script("return document.querySelector('.page-surface').scrollWidth<=document.querySelector('.page-surface').clientWidth+1")
                driver.save_screenshot(str(output / name))

            for width, height, theme in ((1440, 1000, "light"), (1180, 850, "dark")):
                driver.set_window_size(width, height)
                driver.get(url)
                driver.execute_script("localStorage.setItem('qa-theme',arguments[0]);localStorage.removeItem('qa-config')", theme)
                driver.get(url)
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 6)
                click(automation())
                click(wait.until(lambda d: d.find_element("xpath", "//div[contains(@class,'ant-select-item-option-content') and text()='多个已配置组合']")))
                for label, value in (("候补组合上限", "8"), ("订单核对间隔（秒）", "120")):
                    field = driver.find_element("css selector", f'[aria-label="{label}"]')
                    field.send_keys(Keys.CONTROL, "a")
                    field.send_keys(value, Keys.TAB)
                button("保存配置")
                wait.until(lambda d: d.execute_script("return JSON.parse(localStorage.getItem('qa-config')||'{}').alternate_max_combinations===8"))
                saved = driver.execute_script("return JSON.parse(localStorage.getItem('qa-config'))")
                assert saved["alternate_mode"] == "multiple" and saved["order_watch_interval_seconds"] == 120
                assert saved["order_watch_enabled"] and not saved["auto_submit"] and not saved["auto_alternate"]
                driver.get(url)
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 6)
                automation()
                assert driver.find_element("css selector", '[aria-label="候补组合上限"]').get_attribute("value") == "8"
                interval = driver.find_element("css selector", '[aria-label="订单核对间隔（秒）"]')
                assert interval.get_attribute("value") == "120"
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", interval)
                capture(f"trip-{width}-{theme}.png")
                driver.execute_script("qa.observe(true)")
                driver.find_element("css selector", '[aria-label="购票监控"]').click()
                policy = wait.until(lambda d: d.find_element("css selector", '[aria-label="本次候补与核对策略"]'))
                assert "最多8个组合" in policy.text and "每120秒" in policy.text
                driver.find_element("css selector", '[aria-label="订单中心"]').click()
                choices = wait.until(lambda d: d.find_element("css selector", ".order-choice-list"))
                click(choices.find_element("css selector", "summary"))
                assert len(choices.find_elements("css selector", "li")) == 2
                assert "正在持续核对兑现状态" in driver.find_element("tag name", "body").text
                assert "已放慢核对" in driver.find_element("tag name", "body").text
                capture(f"order-{width}-{theme}.png")
                button("停止本地核对")
                wait.until(lambda d: "当前未持续核对" in d.find_element("tag name", "body").text)
                button("继续核对")
                wait.until(lambda d: "正在持续核对兑现状态" in d.find_element("tag name", "body").text)
                assert driver.execute_script("return qa.commands.filter(n=>['stopMonitor','continueOrder'].includes(n))") == ["stopMonitor", "continueOrder"]
    finally:
        if driver:
            driver.quit()
        server.shutdown()
        server.server_close()
        thread.join()
    print("Offline UI passed: settings persist, running policy matches, full choice list, backoff, stop/resume, two sizes/themes.")


if __name__ == "__main__":
    main()
