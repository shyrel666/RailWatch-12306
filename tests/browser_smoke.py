"""Run explicitly: python -X utf8 tests/browser_smoke.py (isolated headless Chrome)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_query import QueryExecutor, FILL_QUERY_FORM_JS, DISMISS_DIALOG_JS, LOGIN_CHECK_JS
from gui_12306_0 import PageAnalyzer, TicketMonitor


class BrowserQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = tempfile.TemporaryDirectory(prefix="railwatch-browser-test-")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument(f"--user-data-dir={cls.profile.name}")
        cls.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
        cls.driver.set_page_load_timeout(10)
        cls.driver.set_script_timeout(4)
        cls.driver.execute_cdp_cmd("Network.enable", {})
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls":["*12306.cn*"]})

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile.cleanup()

    def setUp(self):
        self.driver.get((Path(__file__).parent / "fixtures" / "query.html").resolve().as_uri())
        self.assertTrue(self.driver.execute_script(FILL_QUERY_FORM_JS, "北京", "BJP", "上海", "SHH", "2026-09-10"))
        self.query = QueryExecutor(self.driver)

    def click(self):
        self.driver.find_element("id", "query_ticket").click()
        return True

    def test_unchanged_old_rows_are_never_success(self):
        self.driver.execute_script("fixture.mode='unchanged'")
        self.assertEqual(self.query.execute(self.click, 0.5)["status"], "timeout")

    def test_identical_rows_replaced_are_fresh_and_edits_invalidate(self):
        self.assertEqual(self.query.execute(self.click, 2)["status"], "ok")
        self.assertTrue(self.query.current())
        self.driver.execute_script("document.querySelector('#fromStation').value='XXX'")
        self.assertFalse(self.query.current())

    def test_empty_result_is_success(self):
        self.driver.execute_script("fixture.mode='empty'")
        self.assertEqual(self.query.execute(self.click, 2)["status"], "empty")
        self.assertTrue(self.query.current())

    def test_navigation_invalidates_completed_query(self):
        self.query.execute(self.click, 2)
        self.driver.refresh()
        self.assertFalse(self.query.current())

    def test_late_response_is_discarded_by_new_page(self):
        self.driver.execute_script("fixture.delay=700")
        self.assertEqual(self.query.execute(self.click, 0.2)["status"], "timeout")
        self.driver.refresh()
        self.driver.execute_script(FILL_QUERY_FORM_JS, "北京", "BJP", "上海", "SHH", "2026-09-10")
        self.driver.execute_script("fixture.mode='unchanged'")
        self.assertEqual(QueryExecutor(self.driver).execute(self.click, 1)["status"], "timeout")

    def test_missing_hidden_field_fails_fill(self):
        self.driver.execute_script("document.querySelector('#fromStation').remove()")
        self.assertFalse(self.driver.execute_script(FILL_QUERY_FORM_JS, "北京", "BJP", "上海", "SHH", "2026-09-10"))

    def test_only_allowlisted_dialog_can_be_clicked(self):
        for text, kind in [("未到起售时间", "not_on_sale"), ("请完成人脸核验", "human_action"), ("确认提交订单", "human_action"), ("未知提示", "unknown"), ("尚未起售，请先登录", "human_action")]:
            self.driver.execute_script("fixture.show(arguments[0])", text)
            dialog = self.query.inspect_dialog()
            self.assertEqual(dialog["kind"], kind)
            self.assertEqual(self.driver.execute_script(DISMISS_DIALOG_JS, dialog["text"]), kind == "not_on_sale")
        self.assertEqual(self.driver.execute_script("return fixture.confirms"), 1)

    def test_login_response_classification_runs_actual_script(self):
        wrapper = """const done=arguments[arguments.length-1];
        const script=arguments[0], value=arguments[1];
        new Function('location','fetch',script)({hostname:'kyfw.12306.cn'},
          () => Promise.resolve({ok:true,json:()=>Promise.resolve(value)}), done);"""
        for value, expected in [({"data":{"flag":True}},"ok"), ({"data":{"flag":False}},"expired"), ({},"unknown"), ({"data":{"flag":"false"}},"unknown")]:
            self.assertEqual(self.driver.execute_async_script(wrapper, LOGIN_CHECK_JS, value), expected)

    def test_monitor_transaction_publishes_only_confirmed_empty_rows(self):
        self.driver.execute_script("fixture.mode='empty'")
        analyzer = PageAnalyzer(self.driver, log_callback=lambda message: None)
        analyzer.resolver._name2code = {"北京":"BJP", "上海":"SHH"}
        progress = []
        monitor = TicketMonitor(self.driver, {"from_station_cn":"北京", "to_station_cn":"上海", "date":"2026-09-10", "timer_enabled":True, "target_time":"08:30:00", "query_timeout":2},
                                param_filler=analyzer.fill_query_form, log_callback=lambda message: None,
                                progress_callback=progress.append, wait_callback=lambda seconds: None)
        monitor._is_burst_mode = lambda loop: True
        self.assertFalse(monitor._run_single_loop(1, 1))
        self.assertEqual(progress[0]["status"], "empty")
        self.assertEqual(progress[0]["rows"], [])
        self.assertTrue(progress[0]["query_id"])

    def test_monitor_refills_after_hidden_field_is_changed(self):
        analyzer = PageAnalyzer(self.driver, log_callback=lambda message: None)
        analyzer.resolver._name2code = {"北京":"BJP", "上海":"SHH"}
        monitor = TicketMonitor(self.driver, {"from_station_cn":"北京", "to_station_cn":"上海", "date":"2026-09-10"}, param_filler=analyzer.fill_query_form)
        self.assertTrue(monitor._fill_query_params())
        self.driver.execute_script("document.querySelector('#fromStation').value='WRONG'")
        self.assertTrue(monitor._fill_query_params())
        self.assertEqual(self.driver.execute_script("return document.querySelector('#fromStation').value"), "BJP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
