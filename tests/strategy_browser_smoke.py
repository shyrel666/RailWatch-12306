"""Explicit local UI check: python -X utf8 tests/strategy_browser_smoke.py.

Serves the built renderer; uses a fake desktop bridge and an isolated Chrome profile.
"""
import functools
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_config_contract import default_config


class StrategyBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.output = root / "build" / "strategy-review"
        cls.output.mkdir(parents=True, exist_ok=True)
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if self.path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                    return
                super().do_GET()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root / "dist")))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.profile = tempfile.TemporaryDirectory(prefix="railwatch-strategy-")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument("--window-size=1440,1100")
        options.add_argument(f"--user-data-dir={cls.profile.name}")
        cls.driver = webdriver.Chrome(options=options, service=Service(CHROMEDRIVER_PATH))
        cls.driver.execute_cdp_cmd("Network.enable", {})
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*"]})
        script = """
        const initial = __INITIAL__;
        window.railwatch = {
          command: async (command, payload) => {
            if (command === 'loadConfig') return JSON.parse(localStorage.getItem('test-config') || JSON.stringify(initial));
            if (command === 'saveConfig') { localStorage.setItem('test-config', JSON.stringify(payload.config)); return payload.config; }
            if (command === 'loadPreferences') return {theme:'light'};
            if (command === 'getRuntimeInfo') return {
              app_display_name:'RailWatch 12306', app_version:'0.3.2', data_dir:'本地测试',
              core_available:true, state:{phase:'idle', hits:[], monitoring:false, environment_ready:true,
              login_ready:false, query_ready:false, risk_level:'notice',status_message:'就绪'}
            };
            return {};
          },
          onEvent: () => () => {},
          onUpdateState: () => () => {},
          stopUrgentAlert: () => {},
          getUpdateState: async () => ({phase:'not-available', currentVersion:'0.3.2'}),
          getAppInfo: async () => ({appVersion:'0.3.2', platform:'win32'}),
          openExternal: async () => ({ok:true})
        };
        """.replace("__INITIAL__", json.dumps(default_config(), ensure_ascii=False))
        cls.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
        cls.driver.get(f"http://127.0.0.1:{cls.server.server_port}")

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile.cleanup()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def click(self, label):
        button = WebDriverWait(self.driver, 8).until(lambda driver: next(
            (item for item in driver.find_elements("tag name", "button") if item.text.strip() == label and item.is_displayed()), None))
        button.click()

    def open_strategy(self):
        self.click("行程设置")
        section = self.driver.find_element("id", "trip-query")
        if not section.get_attribute("open"):
            section.find_element("tag name", "summary").click()
        return section

    def test_presets_save_restore_and_layout(self):
        section = self.open_strategy()
        for label, priority, interval, timeout, preview in (
            ("速度优先", "speed", 3, 20, "3.0 ~ 3.6 秒"),
            ("成功率优先", "reliability", 6, 40, "5.0 ~ 7.2 秒"),
        ):
            self.click(label)
            WebDriverWait(self.driver, 5).until(lambda _: preview in section.text)
            self.assertEqual(self.driver.find_element("css selector", 'button[aria-label="智能轮询"]').get_attribute("aria-checked"), "true")
            self.click("保存配置")
            def saved_priority(driver):
                saved = json.loads(driver.execute_script("return localStorage.getItem('test-config')") or "null")
                return saved if saved and saved.get("query_priority") == priority else False
            saved = WebDriverWait(self.driver, 5).until(saved_priority)
            self.assertEqual((saved["query_priority"], saved["interval"], saved["query_timeout"]), (priority, interval, timeout))
            self.assertFalse(saved["auto_submit"] or saved["auto_alternate"])
            section.screenshot(str(self.output / f"strategy-{priority}.png"))
        self.driver.refresh()
        section = self.open_strategy()
        self.assertIn("5.0 ~ 7.2 秒", section.text)
        self.assertEqual(section.find_element("xpath", './/button[normalize-space()="成功率优先"]').get_attribute("aria-pressed"), "true")
        self.driver.set_window_size(1180, 900)
        self.assertTrue(self.driver.execute_script("return document.documentElement.scrollWidth <= innerWidth"))
        self.assertEqual(self.driver.get_log("browser"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
