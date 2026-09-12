"""Run explicitly: python -X utf8 tests/browser_smoke.py (isolated headless Chrome)."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from email.utils import formatdate
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_query import QueryExecutor, FILL_QUERY_FORM_JS, DISMISS_DIALOG_JS, LOGIN_CHECK_JS
from gui_12306_0 import PageAnalyzer, TicketMonitor, SeatType
from railwatch_row_parser import RowParser


class BrowserQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(Path(__file__).parent / "fixtures"), **kwargs)

            def log_message(self, *args):
                pass

            def do_GET(self):
                if urlparse(self.path).path != "/otn/leftTicket/query":
                    return super().do_GET()
                params = parse_qs(urlparse(self.path).query)
                time.sleep(min(float(params.get("delay", ["0"])[0]) / 1000, 2))
                self.send_response(int(params.get("status", ["500" if params.get("fail") == ["1"] else "200"])[0]))
                self.send_header("Content-Type", "application/json")
                if "retryAfter" in params:
                    self.send_header("Retry-After", params["retryAfter"][0])
                self.end_headers()
                try:
                    self.wfile.write(b'{"ok":true}')
                except ConnectionError:
                    pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/query.html"
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
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def setUp(self):
        self.driver.get(self.url)
        self.assertTrue(self.driver.execute_script(FILL_QUERY_FORM_JS, "北京", "BJP", "上海", "SHH", "2026-09-10"))
        self.query = QueryExecutor(self.driver)

    def click(self):
        self.driver.find_element("id", "query_ticket").click()
        return True

    def test_unchanged_old_rows_are_never_success(self):
        self.driver.execute_script("fixture.mode='unchanged'")
        self.assertEqual(self.query.execute(self.click, 0.5)["status"], "timeout")

    def test_unrelated_mutation_without_response_never_completes_query(self):
        self.driver.execute_script("""fixture.mode='unchanged';
          document.getElementById('query_ticket').addEventListener('click',()=>{
            setTimeout(()=>document.querySelector('#ticket_G101 td').append('详情'),50);
          });""")
        self.assertEqual(self.query.execute(self.click, 0.6)["status"], "timeout")

    def test_pending_or_failed_response_cannot_validate_dom_changes(self):
        self.driver.execute_script("fixture.delay=900; setTimeout(()=>document.querySelector('#queryLeftTable').innerHTML+='<tr><td>详情</td></tr>',50)")
        self.assertEqual(self.query.execute(self.click, 0.5)["status"], "timeout")
        self.setUp()
        self.driver.execute_script("fixture.mode='failed'")
        self.assertEqual(self.query.execute(self.click, 1)["status"], "invalid")

    def test_fetch_and_fast_response_without_disabled_button_are_supported(self):
        self.driver.execute_script("fixture.useFetch=true; fixture.noBusy=true; fixture.delay=0")
        self.assertEqual(self.query.execute(self.click, 2)["status"], "ok")

    def test_http_429_preserves_cooldown_for_xhr_and_fetch(self):
        for use_fetch in (False, True):
            with self.subTest(fetch=use_fetch):
                self.setUp()
                self.driver.execute_script("fixture.useFetch=arguments[0]; fixture.httpStatus=429; fixture.retryAfter='120'", use_fetch)
                result = self.query.execute(self.click, 2)
                self.assertEqual(result["status"], "rate_limited")
                self.assertEqual(result["http_status"], 429)
                self.assertEqual(result["retry_after_seconds"], 120)
                self.assertFalse(self.query.current())

    def test_http_503_preserves_retry_after_without_reporting_success(self):
        self.driver.execute_script("fixture.httpStatus=503; fixture.retryAfter='120'")
        result = self.query.execute(self.click, 2)
        self.assertEqual(result["status"], "server_backoff")
        self.assertEqual(result["http_status"], 503)
        self.assertEqual(result["retry_after_seconds"], 120)

    def test_http_429_without_valid_retry_after_retains_risk_classification(self):
        for header in (None, "invalid", "-1"):
            with self.subTest(header=header):
                self.setUp()
                self.driver.execute_script("fixture.httpStatus=429; fixture.retryAfter=arguments[0]", header)
                result = self.query.execute(self.click, 2)
                self.assertEqual(result["status"], "rate_limited")
                self.assertIsNone(result["retry_after_seconds"])

    def test_http_date_cooldown_and_monitor_wiring(self):
        self.driver.execute_script("fixture.httpStatus=429; fixture.retryAfter=arguments[0]", formatdate(time.time() + 120, usegmt=True))
        analyzer = PageAnalyzer(self.driver, log_callback=lambda _: None)
        analyzer.resolver._name2code = {"北京": "BJP", "上海": "SHH"}
        waits = []
        progress = []
        monitor = TicketMonitor(self.driver, {"from_station_cn": "北京", "to_station_cn": "上海",
                                "date": "2026-09-10", "smart_rate": True, "interval": 3,
                                "request_mode": "fast", "query_timeout": 2},
                                param_filler=analyzer.fill_query_form, log_callback=lambda _: None,
                                progress_callback=progress.append, wait_callback=waits.append)
        self.assertFalse(monitor._run_single_loop(1, 3))
        self.assertEqual(monitor.last_query["status"], "rate_limited")
        self.assertGreaterEqual(waits[-1], 118)
        self.assertLessEqual(waits[-1], 120)
        self.assertTrue(monitor.rate_limiter.risk_detected)
        self.assertFalse(progress)
        self.assertEqual(self.driver.execute_script("return fixture.clicks"), 1)
        self.assertEqual(self.driver.current_url, self.url)

    def test_next_query_does_not_accept_a_previous_response(self):
        self.driver.execute_script("fixture.delay=650")
        self.assertEqual(self.query.execute(self.click, 0.2)["status"], "timeout")
        self.driver.execute_script("fixture.mode='unchanged'")
        self.assertEqual(self.query.execute(self.click, 1)["status"], "invalid")

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

    def test_numeric_and_y_trains_are_read_from_train_field_not_fares(self):
        self.driver.execute_script("""document.getElementById('queryLeftTable').innerHTML=
          '<tr id="ticket_a"><td><a class="number">1461</a></td><td>2026-09-10 08:30 1234.50</td></tr>'+
          '<tr id="ticket_b"><td><a class="number">Y701</a></td><td>G101 20:00</td></tr>'+
          '<tr id="ticket_c"><td>08:30</td><td>1461 元</td></tr>';""")
        parser = RowParser(self.driver, SeatType.get_prefix)
        self.assertEqual([row['train'] for row in parser.parse_rows()], ["1461", "Y701"])

    def test_batch_snapshot_reused_for_display_and_matching(self):
        self.driver.execute_script("""document.getElementById('queryLeftTable').innerHTML=
          Array.from({length:100},(_,i)=>'<tr id="ticket_'+i+'"><td>G'+(i+1)+'</td>'+
            '<td id="ZE_'+i+'">有</td><td><a class="btn72">预订</a></td></tr>').join('');""")
        monitor = TicketMonitor(self.driver, {"train_code":"G100", "seat_keyword":"二等座"}, log_callback=lambda _:None)
        original = self.driver.execute
        calls = []
        def counted(command, params=None):
            calls.append(command)
            return original(command, params)
        self.driver.execute = counted
        try:
            monitor._row_snapshot = monitor.row_parser.snapshot_rows(monitor.target_seats)
            shown = monitor.row_parser.display_rows(monitor._row_snapshot)
            hit = monitor._find_hit_row({})
        finally:
            self.driver.execute = original
        self.assertEqual(len(shown), 100)
        self.assertEqual(hit[0], "G100")
        self.assertLessEqual(len(calls), 15)
        self.assertLessEqual(calls.count('getElementText'), 1)
        # A cached seat value must not override a newer value on the page.
        self.driver.execute_script("document.getElementById('ZE_99').innerText='无'")
        self.assertIsNone(monitor._find_hit_row({}))

    def test_advanced_sleeper_uses_its_own_inventory(self):
        self.driver.execute_script("""document.getElementById('queryLeftTable').innerHTML=
          '<tr id="ticket_a"><td>D101</td><td id="RW_a">有</td><td id="GR_a">无</td><td><a class="btn72">预订</a></td></tr>';""")
        monitor = TicketMonitor(self.driver, {"train_code":"D101", "seat_keyword":"高级软卧"}, log_callback=lambda _:None)
        self.assertIsNone(monitor._find_hit_row({}))
        self.driver.execute_script("document.getElementById('GR_a').innerText='有'")
        self.assertEqual(monitor._find_hit_row({})[1], "高级软卧")


if __name__ == "__main__":
    unittest.main(verbosity=2)
