"""Offline renderer smoke for date strategies and recorded query timings.

Run after build:renderer. Uses a mock desktop bridge and blocks external HTTPS.
"""
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading

from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException, ElementNotInteractableException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_bridge import CHROMEDRIVER_PATH, state_to_payload
from railwatch_config_contract import default_config
from railwatch_run_review import QUERY_STEP_LABELS
from railwatch_seats import public_seat_capabilities
from railwatch_state import RailWatchState


def main():
    output = ROOT / "build/qa/efficiency-phase1/ui"
    output.mkdir(parents=True, exist_ok=True)
    config = {**default_config(), "date": (date.today() + timedelta(days=3)).isoformat(),
              "date_range": "±1天", "train_code": "G101", "seat_keyword": "二等座", "passengers": "张三"}
    runtime = {"app_display_name": "RailWatch 12306", "app_version": "0.5.3", "pages": [],
               "state": state_to_payload(RailWatchState.initial()), "date_policy": {"presale_window_days": 15},
               "seat_capabilities": public_seat_capabilities(), "data_dir": "离线演示目录",
               "data_dir_writable": True, "chrome_version": "本地夹具", "core_available": True}
    summary = {"run_id": "offline-efficiency", "started_at": 1791086400, "target_at": None,
               "trip": {"from_station": "北京", "to_station": "上海"}, "conclusion": "已停止"}
    detail = {**summary, "segments": [], "prediction": [], "slowest": None, "preparation_margin_ms": None,
              "query_median_ms": 485, "history_complete": True, "note": "界面验证用本地示例数据。",
              "query_timings": {"recorded_queries": 26, "valid_queries": 25, "window_limit": 200,
                  "phases": [{"id": key, "label": label, "samples": 25, "median_ms": value, "p95_ms": value * 1.2}
                             for (key, label), value in zip(QUERY_STEP_LABELS.items(), (9, 485, 5, 24, 3, 20))],
                  "date_revisits": [{"date": config["date"], "samples": 8, "median_ms": 12400, "p95_ms": 15000}]}}
    script = """
      const initial=CONFIG, runtime=RUNTIME, summary=SUMMARY, detail=DETAIL;
      let config=JSON.parse(localStorage.getItem('qa-config')||'null')||initial;
      window.railwatch={
        command: async (name,payload={})=>{
          if(name==='getRuntimeInfo')return runtime;
          if(name==='loadTripState')return {saved_config:config,saved_at:100,draft:{status:'missing'}};
          if(name==='loadTripChoices')return {recent_routes:[],favorites:[]};
          if(name==='searchStations')return {items:[],warning:null};
          if(name==='loadPreferences')return {theme:localStorage.getItem('qa-theme')||'light',notification_settings:{}};
          if(name==='orderHistory')return {items:[],next_cursor:null};
          if(name==='runReviews')return {items:[summary],next_cursor:null};
          if(name==='runReview')return detail;
          if(name==='saveConfig'){config=payload.config;localStorage.setItem('qa-config',JSON.stringify(config));return config;}
          if(name==='saveTripDraft')return {schema_version:1,revision:payload.revision,saved_at:Date.now()/1000,config:payload.config};
          return {};
        },
        stageDraft:()=>{},onEvent:()=>()=>{},onConfirmRequest:()=>()=>{},onUpdateState:()=>()=>{},
        getUpdateState:async()=>({phase:'idle',currentVersion:'0.5.3'}),
        getAppInfo:async()=>({appVersion:'0.5.3'}),stopUrgentAlert:()=>{},respondConfirmation:()=>{}
      };
    """
    for key, value in (("CONFIG", config), ("RUNTIME", runtime), ("SUMMARY", summary), ("DETAIL", detail)):
        script = script.replace(key, json.dumps(value, ensure_ascii=False))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = None
    try:
        with tempfile.TemporaryDirectory(prefix="railwatch-efficiency-ui-", ignore_cleanup_errors=True) as profile:
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
            # Dropdown and dialog motion can briefly cover the target; retry until the click lands.
            settle = WebDriverWait(driver, 12, ignored_exceptions=(ElementClickInterceptedException,
                                                                   ElementNotInteractableException))

            def click_text(text):
                element = wait.until(lambda d: d.find_element("xpath", f"//button[normalize-space(.)='{text}']"))
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", element)
                element.click()

            for width, height, theme in ((1440, 1000, "light"), (1180, 850, "dark")):
                driver.set_window_size(width, height)
                driver.get(url)
                driver.execute_script("localStorage.setItem('qa-theme',arguments[0])", theme)
                driver.get(url)
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 6)
                driver.find_element("css selector", '[aria-label="行程设置"]').click()
                select = wait.until(lambda d: d.find_element("css selector", '[aria-label="多日期策略"]'))
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", select)
                select.click()
                settle.until(lambda d: d.find_element("xpath", "//div[contains(@class,'ant-select-item-option-content') and text()='限时扫描多日期现票']").click() or True)
                budget = wait.until(lambda d: d.find_element("css selector", '[aria-label="跨日期扫描预算（秒）"]'))
                budget.send_keys(Keys.CONTROL, "a")
                budget.send_keys("45", Keys.TAB)
                click_text("保存配置")
                wait.until(lambda d: d.execute_script("return JSON.parse(localStorage.getItem('qa-config')||'{}').date_scan_budget_seconds===45"))
                saved = driver.execute_script("return JSON.parse(localStorage.getItem('qa-config'))")
                assert saved["date_strategy"] == "inventory_first"
                assert not saved["auto_submit"] and not saved["auto_alternate"]
                driver.get(url)
                wait.until(lambda d: d.find_element("css selector", '[aria-label="行程设置"]')).click()
                budget = wait.until(lambda d: d.find_element("css selector", '[aria-label="跨日期扫描预算（秒）"]'))
                assert budget.get_attribute("value") == "45"
                driver.execute_script("arguments[0].scrollIntoView({block:'center'})", budget)
                driver.save_screenshot(str(output / f"trip-{width}-{theme}.png"))
                driver.find_element("css selector", '[aria-label="订单中心"]').click()
                toggle = wait.until(lambda d: d.find_element("css selector", '.run-reviews-toggle'))
                if toggle.get_attribute("aria-expanded") != "true":
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'})", toggle)
                    toggle.click()
                click_text("查看复盘")
                stats = wait.until(lambda d: d.find_element("css selector", '[aria-label="查询分阶段统计"]'))
                assert "25轮取得有效结果" in stats.text and "12.40 秒" in stats.text
                assert len(stats.find_elements("css selector", "tbody tr")) == 7
                assert driver.execute_script("return document.querySelector('.page-surface').scrollWidth<=document.querySelector('.page-surface').clientWidth+1")
                driver.execute_script("arguments[0].scrollIntoView({block:'start'})", stats)
                driver.save_screenshot(str(output / f"review-{width}-{theme}.png"))
    finally:
        if driver:
            driver.quit()
        server.shutdown()
        server.server_close()
        thread.join()
    print("Offline UI smoke passed: saved date policy and budget, automation unchanged, phase statistics, two sizes/themes.")


if __name__ == "__main__":
    main()
