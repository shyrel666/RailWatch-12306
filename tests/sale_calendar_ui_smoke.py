"""Offline production-renderer review with a deterministic sale-time fixture."""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from railwatch_bridge import CHROMEDRIVER_PATH, state_to_payload
from railwatch_config_contract import default_config
from railwatch_state import RailWatchState

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "qa" / "sale-calendar"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = {**default_config(), "from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-10-11", "date_range": "单日"}
    state = state_to_payload(RailWatchState.initial())
    runtime = {"app_display_name": "RailWatch 12306", "app_version": "0.4.2", "pages": [], "state": state,
               "date_policy": {"presale_window_days": 15, "timezone": "Asia/Shanghai"}}
    bootstrap = """
      const NativeDate = Date;
      const fixed = NativeDate.parse('2026-09-27T09:59:50+08:00');
      window.Date = class extends NativeDate { constructor(...args) { super(...(args.length ? args : [fixed])); } static now() { return fixed; } };
      const config = CONFIG, runtime = RUNTIME;
      window.commands = []; window.listeners = []; window.saleUnavailable = false;
      window.railwatch = {
        command: async (command, payload) => {
          window.commands.push({command,payload});
          if (command === 'loadConfig') return config;
          if (command === 'loadTripState') return {saved_config:config,saved_at:fixed/1000,draft:{status:'missing',draft:null,warning:null}};
          if (command === 'getRuntimeInfo') return runtime;
          if (command === 'loadPreferences') return {theme:'light'};
          if (command === 'savePreferences') return {theme:payload.theme};
          if (command === 'stationSaleTimes') return {station:payload.station,status:window.saleUnavailable?'unavailable':'available',
            schedules:window.saleUnavailable?[]:[{station_name:payload.station,station_code:'BJP',sale_time:'10:00',start_date:'2010-01-01',stop_date:'2099-12-31'}],
            checked_at:window.saleUnavailable?null:fixed/1000-10,expires_at:fixed/1000+3590,retry_at:fixed/1000+50,
            warning:window.saleUnavailable?'无法更新官方起售时间，请稍后刷新或前往官方核对。':null};
          return {};
        },
        onEvent: listener => {window.listeners.push(listener);return () => {};},
        stageDraft: () => {}, onConfirmRequest: () => () => {}, onUpdateState: () => () => {},
        getUpdateState: async () => ({phase:'idle',currentVersion:'0.4.2',enabled:false}),
        stopUrgentAlert: () => {}, respondConfirmation: () => {}, openExternal: async () => ({ok:true})
      };
    """.replace("CONFIG", json.dumps(config, ensure_ascii=False)).replace("RUNTIME", json.dumps(runtime, ensure_ascii=False))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="railwatch-sale-ui-") as profile:
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
                wait = WebDriverWait(driver, 15)
                wait.until(lambda d: d.find_elements("css selector", ".sale-calendar-time") and d.find_element("css selector", ".sale-calendar-time").text == "10:00")
                assert "00:00:10" in driver.find_element("css selector", ".sale-calendar").text
                assert driver.execute_script("return getComputedStyle(document.querySelector('.sale-calendar-footnote')).textAlign") == "center"
                driver.set_window_size(1440, 1200)
                wait.until(lambda d: d.find_elements("css selector", '[aria-label="折叠侧栏"]'))
                driver.find_element("css selector", '[aria-label="折叠侧栏"]').click()
                driver.refresh()
                wait.until(lambda d: d.find_elements("css selector", '[aria-label="展开侧栏"]'))
                driver.find_element("css selector", '[aria-label="展开侧栏"]').click()
                driver.refresh()
                wait.until(lambda d: d.find_elements("css selector", '[aria-label="折叠侧栏"]'))
                driver.set_window_size(1180, 1200)
                assert driver.find_elements("css selector", '[aria-label="折叠侧栏"]')
                driver.execute_script("""
                  window.themeMetrics = [];
                  const start = document.startViewTransition.bind(document);
                  document.startViewTransition = (...args) => {
                    const began = performance.now(), t = start(...args);
                    const sample = {frames: [], readyMs: null, totalMs: null, done: false};
                    window.themeMetrics.push(sample);
                    t.ready.then(() => {
                      sample.readyMs = performance.now() - began;
                      let last;
                      const frame = now => {
                        if (sample.done) return;
                        if (last) sample.frames.push(now-last);
                        last=now; requestAnimationFrame(frame);
                      };
                      requestAnimationFrame(frame);
                    });
                    t.finished.then(() => {sample.done=true; sample.totalMs=performance.now()-began;});
                    return t;
                  };
                """)
                checks = []
                for width in (1440, 1180, 800):
                    driver.set_window_size(width, 1200)
                    for theme in ("light", "dark"):
                        button = driver.find_element("css selector", ".theme-toggle")
                        desired = "明亮" if theme == "light" else "深色"
                        for _ in range(3):
                            if button.text == desired:
                                break
                            button.click()
                            wait.until(lambda d: d.find_element("css selector", ".theme-toggle").is_enabled() and not d.execute_script("return !!document.documentElement.dataset.themeTransition"))
                        wait.until(lambda d: d.find_element("css selector", ".theme-toggle").text == desired)
                        card = driver.find_element("css selector", ".sale-calendar")
                        driver.execute_script("arguments[0].scrollIntoView({block:'end'})", card)
                        overflow = driver.execute_script("return [...document.querySelectorAll('.sale-calendar, .sale-calendar-body, .sale-calendar-dates, .sale-calendar-detail, .sale-calendar-day')].some(e=>e.scrollWidth>e.clientWidth+1)")
                        assert not overflow, (width, theme)
                        card.screenshot(str(OUTPUT / f"calendar-{width}-{theme}.png"))
                        checks.append({"width": width, "theme": theme, "overflow": overflow})
                driver.execute_script("window.saleUnavailable = true")
                driver.find_element("css selector", '[aria-label="刷新起售时间"]').click()
                wait.until(lambda d: "时间待核对" == d.find_element("css selector", ".sale-calendar-time").text)
                assert not driver.find_elements("css selector", ".sale-calendar-countdown")
                errors = [item for item in driver.get_log("browser") if item["level"] == "SEVERE" and "favicon" not in item["message"]]
                assert not errors, errors
                commands = driver.execute_script("return window.commands.map(x=>x.command)")
                assert "startMonitor" not in commands and "saveConfig" not in commands
                metrics = driver.execute_script("return window.themeMetrics")
                assert metrics and all(item["done"] and len(item["frames"]) > 5 for item in metrics), metrics
                # Freeze one animation frame for visual review, separately from timing samples.
                driver.set_window_size(1440, 1200)
                driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "light"}]})
                driver.execute_script("""
                  const root=document.documentElement, animate=root.animate.bind(root);
                  root.animate=(...args) => {
                    const animation=animate(...args);
                    window.reviewAnimation=animation;
                    animation.pause(); animation.currentTime=65;
                    root.animate=animate;
                    return animation;
                  };
                """)
                driver.find_element("css selector", ".theme-toggle").click()
                wait.until(lambda d: d.execute_script("return !!window.reviewAnimation"))
                driver.save_screenshot(str(OUTPUT / "theme-transition.png"))
                driver.execute_script("window.reviewAnimation.play()")
                wait.until(lambda d: d.find_element("css selector", ".theme-toggle").is_enabled())
                driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}, {"name": "prefers-color-scheme", "value": "light"}]})
                count = driver.execute_script("return window.themeMetrics.length")
                for _ in range(2):
                    driver.find_element("css selector", ".theme-toggle").click()
                    wait.until(lambda d: d.find_element("css selector", ".theme-toggle").is_enabled())
                assert driver.execute_script("return window.themeMetrics.length") == count
                (OUTPUT / "report.json").write_text(json.dumps({"checks": checks, "errors": errors, "themeMetrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"checks": len(checks), "errors": errors, "output": str(OUTPUT)}))
            finally:
                driver.quit()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
