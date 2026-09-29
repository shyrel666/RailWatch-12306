"""Production renderer rehearsal/review smoke using synthetic IPC only."""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_bridge import CHROMEDRIVER_PATH, state_to_payload
from railwatch_config_contract import default_config
from railwatch_state import RailWatchState
from railwatch_rehearsal import CHECKS, public_trip
from railwatch_run_review import build_prediction


def main():
    config = {**default_config(), "passengers": "测试甲", "train_code": "G9", "seat_keyword": "二等座", "auto_submit": True}
    checks = [{"id": key, "title": title, "status": "pass", "critical": True,
               "summary": "本地演示检查通过", "duration_ms": 125, "details": []} for key, title in CHECKS]
    checks[4].update(status="warn", summary="列表未明确成人票种，普通订单将在下单页回读", details=["测*：本人类型未显示"],
                     fix={"page": "行程设置", "section": "trip-basics", "label": "修改乘车人"})
    checks[7].update(status="unknown", summary="时间测量误差过大，无法判断电脑时钟是否准确；定时仍使用系统时钟",
                     details=["HTTP 辅助估计偏差 +5.20s，不确定度至少 ±6.00s。", "请在启动定时任务前完成系统对时。"])
    report = {"schema_version": 1, "rehearsal_id": "ui", "trigger": "manual", "started_at": 1, "finished_at": 2,
              "trip": public_trip(config), "checks": checks, "verdict": "risky",
              "measurements": {"scheduler_late_ms": {"p95": 15}, "query_round_trip_ms": 230, "drill_ms": {"readback": 420}}}
    report["prediction"] = build_prediction(report, [])
    review = {"run_id": "demo", "started_at": 1, "target_at": 2, "trip": public_trip(config), "conclusion": "未命中",
              "segments": report["prediction"], "prediction": report["prediction"], "slowest": "下单页与核对",
              "preparation_margin_ms": 22000, "query_median_ms": 230, "history_complete": False, "note": "演示数据；未记录阶段不推测补齐。"}
    review["order_timings"] = [{"kind": "regular", "segments": [
        {"id": "page_load", "label": "打开并等待下单页", "duration_ms": 6000, "start_ms": 0, "source": "本机观察"},
        {"id": "passengers", "label": "选择乘车人", "duration_ms": 500, "start_ms": 6000, "source": "本机观察"},
        {"id": "seats", "label": "选择席别", "duration_ms": 250, "start_ms": 6500, "source": "本机观察"},
        {"id": "readback", "label": "提交前核对", "duration_ms": 100, "start_ms": 6750, "source": "本机观察"},
    ]}]
    runtime = {"state": state_to_payload(RailWatchState.initial()), "app_version": "0.5.0", "data_dir": "演示目录"}
    script = """
      const config=CONFIG, report=REPORT, review=REVIEW, runtime=RUNTIME;
      window.listeners=[];window.commands=[];
      const emit=(event,payload)=>listeners.forEach(fn=>fn({event,payload}));
      window.railwatch={
        command:async(name,payload={})=>{
          commands.push(name);
          if(name==='getRuntimeInfo')return runtime;
          if(name==='loadTripState')return {saved_config:config,saved_at:1,draft:{status:'missing',draft:null,warning:null}};
          if(name==='loadTripChoices')return {recent_routes:[],favorites:[]};
          if(name==='loadPreferences'||name==='savePreferences')return {theme:payload.theme||'light',auto_rehearsal:true,notification_settings:{}};
          if(name==='orderHistory')return {items:[],next_cursor:null};
          if(name==='rehearsalHistory')return {items:[]};
          if(name==='clearRehearsalHistory')return {cleared:1};
          if(name==='runReviews')return {items:[review],next_cursor:null};
          if(name==='runReview')return review;
          if(name==='rehearse'){
            emit('rehearsalStarted',{rehearsal_id:'ui',trigger:'manual',checks:report.checks.map(c=>({id:c.id,title:c.title,critical:c.critical}))});
            for(const check of report.checks){await new Promise(r=>setTimeout(r,20));emit('rehearsalStep',{rehearsal_id:'ui',check});}
            emit('rehearsalFinished',{report});return report;
          }
          return {};
        },
        stageDraft:()=>{},onEvent:fn=>{listeners.push(fn);return()=>{};},onConfirmRequest:()=>()=>{},onUpdateState:()=>()=>{},
        getUpdateState:async()=>({phase:'idle',currentVersion:'0.5.0'}),getAppInfo:async()=>({appVersion:'0.5.0'}),
        stopUrgentAlert:()=>{},respondConfirmation:()=>{},openExternal:async()=>({ok:true})
      };
    """
    for key, value in (("CONFIG", config), ("REPORT", report), ("REVIEW", review), ("RUNTIME", runtime)):
        script = script.replace(key, json.dumps(value, ensure_ascii=False))
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            super().do_GET()
        def log_message(self, *_):
            pass
    output = ROOT / "build/qa/rehearsal"
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="rehearsal-ui-") as profile:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument(f"--user-data-dir={profile}")
            options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
            try:
                driver.execute_cdp_cmd("Network.enable", {})
                driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["https://*", "*12306.cn*"]})
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
                driver.set_window_size(1440, 1800)
                driver.get(f"http://127.0.0.1:{server.server_port}/")
                wait = WebDriverWait(driver, 10)
                wait.until(lambda d: len(d.find_elements("css selector", ".nav .nav-item")) == 6)
                driver.find_element("css selector", '[aria-label="购票监控"]').click()
                start = wait.until(lambda d: d.find_element("xpath", "//button[span[text()='开始彩排']]"))
                wait.until(lambda _: start.is_enabled())
                start.click()
                # A manual run opens the result dialog; checks light up inside it.
                dialog_body = ".rehearsal-dialog .ant-modal-container"
                wait.until(lambda d: len(d.find_elements("css selector", f"{dialog_body} .rehearsal-check.pass")) == 8)
                assert len(driver.find_elements("css selector", f"{dialog_body} .rehearsal-check.unknown")) == 1
                assert "有风险" in driver.find_element("css selector", f"{dialog_body} .rehearsal-verdict").text
                assert "有风险" in driver.find_element("css selector", "#monitor-rehearsal .rehearsal-verdict").text
                assert driver.execute_script("return commands.filter(c=>c==='rehearse').length") == 1
                def dialog_visible(d):
                    wraps = d.find_elements("css selector", ".rehearsal-dialog")
                    return bool(wraps) and wraps[0].is_displayed() and "ant-zoom-leave" not in wraps[0].get_attribute("class")
                def dialog_hidden(d):
                    wraps = d.find_elements("css selector", ".rehearsal-dialog")
                    return not wraps or not wraps[0].is_displayed()
                for theme in ("light", "dark"):
                    if theme == "dark":
                        # The dialog mask covers the shell: close, switch theme, reopen from the summary.
                        driver.find_element("css selector", f"{dialog_body} .ant-modal-footer .ant-btn-primary").click()
                        wait.until(dialog_hidden)
                        driver.find_element("css selector", '[aria-label*="主题"]').click()
                        wait.until(lambda d: d.execute_script("return document.documentElement.dataset.theme") == "dark")
                        time.sleep(1)  # Let the existing theme reveal animation finish.
                        driver.find_element("xpath", "//button[span[text()='查看结果']]").click()
                        wait.until(dialog_visible)
                        time.sleep(.4)  # Zoom-in motion.
                    content = driver.find_element("css selector", dialog_body)
                    content.screenshot(str(output / f"rehearsal-{theme}.png"))
                    driver.set_window_size(1180, 720)
                    time.sleep(.3)
                    assert driver.execute_script("return arguments[0].scrollWidth<=arguments[0].clientWidth+1", content)
                    driver.set_window_size(1440, 1800)
                driver.find_element("css selector", f"{dialog_body} .ant-modal-footer .ant-btn-primary").click()
                wait.until(dialog_hidden)
                panel = driver.find_element("id", "monitor-rehearsal")
                driver.execute_script("arguments[0].scrollIntoView({block:'start'})", panel)
                panel.screenshot(str(output / "rehearsal-panel-dark.png"))
                assert panel.size["height"] < 180, panel.size
                driver.set_window_size(1180, 720)
                assert driver.execute_script("return arguments[0].scrollWidth<=arguments[0].clientWidth+1", panel)
                driver.find_element("xpath", "//button[span[text()='清除记录']]").click()
                wait.until(lambda d: not d.find_elements("xpath", "//button[span[text()='查看结果']]"))
                assert driver.execute_script("return commands.filter(c=>c==='clearRehearsalHistory').length") == 1
                driver.set_window_size(1440, 1800)
                driver.find_element("css selector", '[aria-label="订单中心"]').click()
                wait.until(lambda d: d.find_element("css selector", '#order-run-reviews .run-reviews-toggle')).click()
                wait.until(lambda d: d.find_element("xpath", "//button[span[text()='查看复盘']]" )).click()
                wait.until(lambda d: d.find_element("css selector", '[aria-label="复盘详情"]'))
                breakdown = driver.find_element("css selector", '[aria-label="下单分步耗时"]')
                assert "6.00 秒" in breakdown.text and "不重复计入总耗时" in breakdown.text
                driver.find_element("id", "order-run-reviews").screenshot(str(output / "review-dark.png"))
                driver.set_window_size(1180, 720)
                assert driver.execute_script("return arguments[0].scrollWidth<=arguments[0].clientWidth+1", breakdown)
                errors = [entry for entry in driver.get_log("browser") if entry["level"] == "SEVERE"]
                assert not errors, errors
                print("PASS: rehearsal events, risk/fix display, review, light/dark, 1180px layout; synthetic IPC only")
            finally:
                driver.quit()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
