"""Offline production UI smoke for M3 notification settings."""
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
from railwatch_bridge import CHROMEDRIVER_PATH, RailWatchBridge

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "qa" / "m3"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="railwatch-m3-") as directory:
        bridge = RailWatchBridge(directory)
        preferences = bridge.load_preferences()
        runtime = bridge.get_runtime_info()
        config = bridge.load_config()
        script = """
        const preferences = PREFS, runtime = RUNTIME, config = CONFIG;
        window.railwatch = {
          command: async (name, payload = {}) => {
            if (name === 'loadPreferences') return preferences;
            if (name === 'savePreferences') {
              if (payload.notification_settings) Object.assign(preferences.notification_settings, payload.notification_settings);
              if (payload.close_to_tray !== undefined) preferences.close_to_tray = payload.close_to_tray;
              if (payload.theme) preferences.theme = payload.theme;
              return preferences;
            }
            if (name === 'notificationStatus') return {};
            if (name === 'testNotification') return {server_chan:{status:'disabled',sent_at:null},email:{status:'disabled',sent_at:null},wecom_webhook:{status:'disabled',sent_at:null}};
            if (name === 'getRuntimeInfo') return runtime;
            if (name === 'loadConfig') return config;
            if (name === 'loadTripState') return {saved_config:config,saved_at:Date.now()/1000,draft:{status:'missing',draft:null,warning:null}};
            if (name === 'loadTripChoices') return {recent_routes:[],favorites:[]};
            if (name === 'searchStations') return {items:[],warning:null};
            return {};
          },
          onEvent: () => () => {}, onConfirmRequest: () => () => {}, onUpdateState: () => () => {},
          stageDraft: () => {},
          getUpdateState: async () => ({phase:'idle',currentVersion:'0.4.2'}),
          getAppInfo: async () => ({appVersion:'0.4.2'}), stopUrgentAlert: () => {},
          respondConfirmation: () => {}, openExternal: async () => ({ok:true}),
        };
        """.replace("PREFS", json.dumps(preferences, ensure_ascii=False)).replace("RUNTIME", json.dumps(runtime, ensure_ascii=False)).replace("CONFIG", json.dumps(config, ensure_ascii=False))

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dist")))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        driver = None
        try:
            with tempfile.TemporaryDirectory(prefix="railwatch-m3-chrome-", ignore_cleanup_errors=True) as profile:
                options = webdriver.ChromeOptions()
                options.add_argument("--headless=new")
                options.add_argument("--disable-background-networking")
                options.add_argument(f"--user-data-dir={profile}")
                options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
                driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
                driver.execute_cdp_cmd("Network.enable", {})
                driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
                for width, height in ((1440, 900), (1180, 720)):
                    driver.set_window_size(width, height)
                    driver.get(f"http://127.0.0.1:{server.server_port}/")
                    wait = WebDriverWait(driver, 10)
                    wait.until(lambda d: d.find_elements("css selector", '[aria-label="系统设置"]'))
                    driver.find_element("css selector", '[aria-label="系统设置"]').click()
                    wait.until(lambda d: d.find_elements("xpath", '//button[normalize-space()="发送测试通知"]'))
                    driver.execute_script("document.getElementById('settings-notifications').scrollIntoView({block:'start'})")
                    driver.save_screenshot(str(OUTPUT / f"notifications-top-{width}.png"))
                    assert driver.find_element("css selector", '[aria-label="循环声音"]').get_attribute("aria-checked") == "true"
                    driver.find_element("xpath", '//button[normalize-space()="发送测试通知"]').click()
                    wait.until(lambda d: "已禁用" in d.find_element("css selector", "#settings-notifications").text)
                    driver.save_screenshot(str(OUTPUT / f"notifications-{width}.png"))
                    severe = [item for item in driver.get_log("browser") if item.get("level") == "SEVERE" and "favicon.ico" not in item.get("message", "")]
                    if severe:
                        print(json.dumps(severe, ensure_ascii=False))
                    assert not severe
                driver.quit()
                driver = None
            print("M3 notification UI smoke passed: settings and test delivery at 1440/1180.")
        finally:
            if driver:
                driver.quit()
            server.shutdown()


if __name__ == "__main__":
    main()
