import unittest
import sys
import types
from unittest.mock import Mock, patch

class TimeoutException(Exception):
    pass


class NoSuchElementException(Exception):
    pass


class StaleElementReferenceException(Exception):
    pass


class ElementClickInterceptedException(Exception):
    pass


selenium = types.ModuleType("selenium")
webdriver = types.ModuleType("selenium.webdriver")
common = types.ModuleType("selenium.webdriver.common")
by_module = types.ModuleType("selenium.webdriver.common.by")
support = types.ModuleType("selenium.webdriver.support")
ui_module = types.ModuleType("selenium.webdriver.support.ui")
ec_module = types.ModuleType("selenium.webdriver.support.expected_conditions")
actions_module = types.ModuleType("selenium.webdriver.common.action_chains")
exceptions_module = types.ModuleType("selenium.common.exceptions")
selenium_common = types.ModuleType("selenium.common")


class By:
    ID = "id"
    CSS_SELECTOR = "css selector"
    XPATH = "xpath"


class WebDriverWait:
    def __init__(self, driver, timeout):
        self.driver = driver

    def until(self, condition):
        raise TimeoutException()


class ActionChains:
    def __init__(self, driver):
        self.driver = driver

    def move_to_element(self, element):
        return self

    def perform(self):
        return None


def _identity_condition(locator):
    return lambda driver: None


by_module.By = By
ui_module.WebDriverWait = WebDriverWait
ec_module.presence_of_element_located = _identity_condition
ec_module.element_to_be_clickable = _identity_condition
actions_module.ActionChains = ActionChains
exceptions_module.TimeoutException = TimeoutException
exceptions_module.NoSuchElementException = NoSuchElementException
exceptions_module.StaleElementReferenceException = StaleElementReferenceException
exceptions_module.ElementClickInterceptedException = ElementClickInterceptedException

sys.modules.setdefault("selenium", selenium)
sys.modules.setdefault("selenium.webdriver", webdriver)
sys.modules.setdefault("selenium.webdriver.common", common)
sys.modules.setdefault("selenium.webdriver.common.by", by_module)
sys.modules.setdefault("selenium.webdriver.support", support)
sys.modules.setdefault("selenium.webdriver.support.ui", ui_module)
sys.modules.setdefault("selenium.webdriver.support.expected_conditions", ec_module)
sys.modules.setdefault("selenium.webdriver.common.action_chains", actions_module)
sys.modules.setdefault("selenium.common", selenium_common)
sys.modules.setdefault("selenium.common.exceptions", exceptions_module)

from gui_12306_0 import BaseHandler, PageAnalyzer, QueryConfig, TicketMonitor


class FakeButton:
    def __init__(self):
        self.clicked = False

    def click(self):
        self.clicked = True


class FakeDriver:
    def __init__(self):
        self.submit_button = FakeButton()
        self.wait_calls = 0
        self.selection_attempted = False

    def execute_script(self, script, *args):
        if "targetNames" in script and "selectedCount" in script:
            self.selection_attempted = True
            return 0
        return None

    def find_elements(self, by=None, value=None):
        return []

    def find_element(self, by=None, value=None):
        raise TimeoutException("not found")

    def next_wait_result(self):
        self.wait_calls += 1
        if self.wait_calls == 1:
            return object()
        if self.wait_calls == 2:
            return self.submit_button
        raise TimeoutException("no confirm button")


class FakeAlternateSubmitButton:
    def __init__(self):
        self.clicked = False

    def is_displayed(self):
        return True

    def click(self):
        self.clicked = True


class FakeAlternateButton(FakeAlternateSubmitButton):
    pass


class FakeAlternateRow:
    def __init__(self):
        self.alternate_button = FakeAlternateButton()

    def find_element(self, by=None, value=None):
        if value in ("a.btn-houbu", ".//a[contains(text(),'候补')]"):
            return self.alternate_button
        raise NoSuchElementException("not found")


class FakeAlternateDriver:
    def __init__(self):
        self.submit_button = FakeAlternateSubmitButton()
        self.selection_attempted = False

    def execute_script(self, script, *args):
        if "targetNames" in script:
            self.selection_attempted = True
            return 0
        return None

    def find_element(self, by=None, value=None):
        if value == "#submitHoubu_id":
            return self.submit_button
        raise NoSuchElementException("not found")

    def next_wait_result(self):
        return object()


class FakePageDriver:
    def __init__(self):
        self.opened_url = ""

    def get(self, url):
        self.opened_url = url

    def execute_script(self, script, *args):
        return None


class FakeDateCyclingDriver:
    def __init__(self):
        self.scripts = []

    def execute_script(self, script, *args):
        self.scripts.append((script, args))
        return None


class FakeRefreshDateDriver:
    def __init__(self):
        self.events = []

    def refresh(self):
        self.events.append("refresh")

    def execute_script(self, script, *args):
        if "train_date" in script:
            self.events.append(f"date:{args[0]}")
        return None


class SuccessfulWait:
    def __init__(self, driver, timeout):
        self.driver = driver

    def until(self, condition):
        return object()


class FakeWait:
    def __init__(self, driver, timeout):
        self.driver = driver

    def until(self, condition):
        return self.driver.next_wait_result()


class TicketMonitorLogicTests(unittest.TestCase):
    def test_candidate_seat_is_not_regular_ticket_availability(self):
        self.assertFalse(BaseHandler.is_seat_available("候补"))
        self.assertTrue(BaseHandler.is_alternate_available("候补"))

    def test_query_config_persists_passenger_count_and_alternate_fields(self):
        cfg = QueryConfig(
            passengers="张三,李四",
            auto_alternate=True,
            alternate_deadline="18:00",
        )
        cfg.passenger_count = 2

        data = cfg.to_dict()

        self.assertEqual(data.get("passenger_count"), 2)
        self.assertTrue(data["auto_alternate"])
        self.assertEqual(data["alternate_deadline"], "18:00")

    def test_query_config_persists_renderer_strategy_fields(self):
        cfg = QueryConfig(
            interval=1.5,
            query_timeout=25,
            date_range="±2天",
            smart_rate=False,
            timer_enabled=True,
            target_time="08:30:00",
        )

        data = cfg.to_dict()

        self.assertEqual(data["interval"], 1.5)
        self.assertEqual(data["query_timeout"], 25)
        self.assertEqual(data["date_range"], "±2天")
        self.assertFalse(data["smart_rate"])
        self.assertTrue(data["timer_enabled"])
        self.assertEqual(data["target_time"], "08:30:00")

    def test_page_analyzer_uses_configured_query_timeout(self):
        analyzer = PageAnalyzer(FakePageDriver(), log_callback=lambda msg: None, base_dir=".")
        analyzer.fill_query_form = Mock(return_value=True)
        analyzer._parse_rows = lambda: [{"train":"G101", "raw":"G101 二等座 有"}]
        executor = Mock()
        executor.execute.return_value = {"status":"ok"}
        executor.current.return_value = True
        with patch("gui_12306_0.WebDriverWait", SuccessfulWait), patch("gui_12306_0.QueryExecutor", return_value=executor):
            rows = analyzer.open_fill_query_and_analyze({"from_station_cn":"北京", "to_station_cn":"上海", "date":"2026-06-10", "query_timeout":25})
        self.assertEqual(len(rows), 1)
        self.assertEqual(executor.execute.call_args.args[1], 25)

    def test_ticket_monitor_uses_configured_query_timeout(self):
        class Driver:
            def refresh(self):
                return None

        monitor = TicketMonitor(
            Driver(),
            {"query_timeout": 23},
            log_callback=lambda msg: None,
        )
        monitor.click_query_button = lambda: True
        observed_timeout = []

        def wait_for_rows(timeout=40, stop_check=None):
            observed_timeout.append(timeout)
            return False

        monitor.wait_for_rows = wait_for_rows

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            monitor._run_single_loop(1, 1)

        self.assertEqual(observed_timeout, [23])

    def test_timed_burst_first_loop_queries_without_refreshing(self):
        class Driver:
            def __init__(self):
                self.refresh_count = 0

            def refresh(self):
                self.refresh_count += 1

        class ServerTime:
            def is_in_burst_window(self, target_time, prepare_seconds, burst_seconds):
                return True

        driver = Driver()
        monitor = TicketMonitor(
            driver,
            {"interval": 1, "query_timeout": 1, "timer_enabled": True, "target_time": "08:30:00"},
            log_callback=lambda msg: None,
            server_time_sync=ServerTime(),
        )
        monitor.click_query_button = lambda: True
        monitor.wait_for_rows = lambda timeout=40, stop_check=None: True
        monitor._find_hit_row = lambda indices: None
        monitor.row_parser.snapshot_rows = Mock(return_value=[])

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            result = monitor._run_single_loop(1, 1)

        self.assertFalse(result)
        self.assertEqual(driver.refresh_count, 0)

    def test_monitor_emits_progress_rows_and_structured_hit(self):
        progress_events = []
        hit_events = []

        class Row:
            def __init__(self, text):
                self._text = text
                self.text = text

            def find_elements(self, by=None, value=None):
                return []

        class Table:
            def find_elements(self, by=None, value=None):
                return [Row("G101 北京 上海 二等座 有")]

        class Driver:
            def refresh(self):
                return None

            def find_element(self, by=None, value=None):
                return Table()

        monitor = TicketMonitor(
            Driver(),
            {"interval": 1, "query_timeout": 1, "train_code": ""},
            log_callback=lambda msg: None,
            progress_callback=lambda payload: progress_events.append(payload),
            on_hit=lambda payload: hit_events.append(payload),
        )
        monitor.click_query_button = lambda: True
        monitor.wait_for_rows = lambda timeout=40, stop_check=None: True
        monitor._find_hit_row = lambda indices: ("G101", "二等座", "有", object(), None, "book")
        monitor._focus_and_highlight = lambda row, btn: None
        monitor.row_parser.snapshot_rows = Mock(return_value=[{"train":"G101", "raw":"G101 北京 上海 二等座 有", "seats":{}, "element":Row("G101")}])

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            hit = monitor._run_single_loop(1, 1)

        self.assertTrue(hit)
        self.assertEqual(progress_events[0]["loop"], 1)
        self.assertEqual(progress_events[0]["rows"], [{"train": "G101", "raw": "G101 北京 上海 二等座 有"}])
        self.assertEqual(hit_events[0]["train_code"], "G101")
        self.assertEqual(hit_events[0]["seat_type"], "二等座")
        self.assertEqual(hit_events[0]["status"], "有")
        self.assertEqual(hit_events[0]["source"], "regular")

    def test_monitor_run_preserves_decimal_interval_for_randomized_delay(self):
        class Driver:
            pass

        observed_intervals = []
        stop_calls = 0

        def should_stop():
            nonlocal stop_calls
            stop_calls += 1
            return stop_calls > 1

        monitor = TicketMonitor(
            Driver(),
            {"interval": 1.5, "smart_rate": False},
            log_callback=lambda msg: None,
            stop_check=should_stop,
        )
        monitor._run_single_loop = lambda loop_count, interval: False

        def fake_random_interval(base_interval):
            observed_intervals.append(base_interval)
            return 0

        with patch("gui_12306_0.WebDriverWait", SuccessfulWait), patch(
            "gui_12306_0.get_random_interval",
            fake_random_interval,
        ):
            monitor.run()

        self.assertEqual(observed_intervals, [1.5])

    def test_smart_rate_limiter_preserves_decimal_base_interval(self):
        observed_intervals = []

        class FakeRateLimiter:
            def __init__(self, base_interval, min_interval, max_interval, log_callback):
                observed_intervals.append(base_interval)

        with patch("gui_12306_0.AdaptiveRateLimiter", FakeRateLimiter):
            TicketMonitor(
                object(),
                {"interval": 3.5, "smart_rate": True},
                log_callback=lambda msg: None,
            )

        self.assertEqual(observed_intervals, [3.5])

    def test_auto_submit_aborts_when_no_passenger_selected(self):
        from railwatch_order_page import OrderPage
        from test_orders import intent
        page = OrderPage(Mock())
        page.snapshot = lambda: {"formReady": True}
        page.result = lambda *a, **k: __import__('railwatch_orders').OrderResult("unknown")
        page.prepare_people = lambda _: False
        result = page.regular(Mock(), intent())
        self.assertEqual(result.status, "verification")
        page.driver.find_elements.assert_not_called()

    def test_alternate_submit_aborts_when_no_passenger_selected(self):
        from railwatch_order_page import OrderPage
        page = OrderPage(Mock())
        page.driver.execute_script.return_value = False
        from test_orders import intent
        self.assertFalse(page.prepare_people(intent("alternate")))

    def test_alternate_selection_uses_exact_names(self):
        from railwatch_order_page import OrderPage, SELECT_PASSENGERS_JS
        from test_orders import intent
        driver = Mock()
        driver.execute_script.return_value = True
        self.assertTrue(OrderPage(driver).prepare_people(intent("alternate")))
        driver.execute_script.assert_called_once_with(SELECT_PASSENGERS_JS, ["张三"])

    def test_find_hit_row_uses_houbu_button_not_seat_text(self):
        class Row:
            text = "G101 北京 上海 二等座 无"

            def find_elements(self, by=None, value=None):
                return []

        class Table:
            def find_elements(self, by=None, value=None):
                return [Row()]

        class Driver:
            def find_element(self, by=None, value=None):
                return Table()

        monitor = TicketMonitor(
            Driver(),
            {"train_code": "G101", "seat_keyword": "二等座", "auto_alternate": True},
            log_callback=lambda m: None,
        )
        monitor._get_seat_value = lambda row, seat, idx: "无"
        monitor._find_book_button = lambda row: None
        monitor._find_alternate_button = lambda row, seat=None: object()
        monitor.row_parser.snapshot_rows = Mock(return_value=[{"train":"G101", "seats":{"二等座":"无"}, "element":Row()}])

        hit = monitor._find_hit_row({})

        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "G101")
        self.assertEqual(hit[5], "alternate")

    def test_find_hit_row_prefers_available_ticket_over_houbu(self):
        class Row:
            text = "G101 北京 上海 二等座 有"

            def find_elements(self, by=None, value=None):
                return []

        class Table:
            def find_elements(self, by=None, value=None):
                return [Row()]

        class Driver:
            def find_element(self, by=None, value=None):
                return Table()

        book = object()
        monitor = TicketMonitor(
            Driver(),
            {"train_code": "G101", "seat_keyword": "二等座", "auto_alternate": True},
            log_callback=lambda m: None,
        )
        monitor._get_seat_value = lambda row, seat, idx: "有"
        monitor._find_book_button = lambda row: book
        monitor._find_alternate_button = lambda row, seat=None: object()
        monitor.row_parser.snapshot_rows = Mock(return_value=[{"train":"G101", "seats":{"二等座":"有"}, "element":Row()}])

        hit = monitor._find_hit_row({})

        self.assertEqual(hit[5], "book")
        self.assertIs(hit[4], book)

    def test_unlimited_seat_cannot_create_unspecified_houbu_order(self):
        monitor = TicketMonitor(Mock(), {"auto_alternate": True}, log_callback=lambda m: None)
        monitor.driver.find_element.return_value.find_elements.return_value = []
        monitor.row_parser.snapshot_rows = Mock(return_value=[])
        self.assertIsNone(monitor._find_hit_row({}))

    def test_find_hit_row_no_houbu_when_auto_alternate_disabled(self):
        class Row:
            text = "G101 北京 上海 二等座 无"

            def find_elements(self, by=None, value=None):
                return []

        class Table:
            def find_elements(self, by=None, value=None):
                return [Row()]

        class Driver:
            def find_element(self, by=None, value=None):
                return Table()

        monitor = TicketMonitor(
            Driver(),
            {"train_code": "G101", "seat_keyword": "二等座", "auto_alternate": False},
            log_callback=lambda m: None,
        )
        monitor._get_seat_value = lambda row, seat, idx: "无"
        monitor._find_book_button = lambda row: None
        monitor._find_alternate_button = lambda row, seat=None: object()
        monitor.row_parser.snapshot_rows = Mock(return_value=[{"train":"G101", "seats":{"二等座":"无"}, "element":Row()}])

        self.assertIsNone(monitor._find_hit_row({}))

    def test_alternate_submit_uses_structured_order_evidence(self):
        from railwatch_alternate_flow import AlternateFlow
        from railwatch_orders import OrderResult
        from test_orders import intent, CONFIG
        button = Mock()
        flow = AlternateFlow(Mock(), CONFIG, Mock(), find_alternate_button=lambda row, seat: button)
        flow.order_page = Mock()
        expected = OrderResult("pending_payment", order_id="E123")
        flow.order_page.alternate.return_value = expected
        selected = intent("alternate")
        self.assertEqual(flow.try_alternate_order(Mock(), "G101", "二等座", selected), expected)
        flow.order_page.alternate.assert_called_once_with(button, selected)

    def test_alternate_submit_hands_off_when_success_not_confirmed(self):
        from test_orders import snapshot, intent
        from railwatch_order_page import OrderPage
        driver = Mock()
        driver.execute_script.return_value = snapshot(orders=[])
        self.assertEqual(OrderPage(driver).result(intent("alternate"), submitted=True).status, "unknown")

    def test_alternate_submit_reports_not_submitted_when_button_missing(self):
        from railwatch_alternate_flow import AlternateFlow
        from test_orders import CONFIG, intent
        flow = AlternateFlow(Mock(), CONFIG, Mock(), find_alternate_button=lambda *args: None)
        result = flow.try_alternate_order(Mock(), "G101", "二等座", intent("alternate"))
        self.assertEqual(result.status, "not_submitted")
        self.assertTrue(result.no_order)

    def test_alternate_success_present_reflects_driver_result_and_is_safe(self):
        class Driver:
            def __init__(self, value):
                self.value = value

            def execute_script(self, script, *args):
                return self.value

        self.assertFalse(TicketMonitor(Driver(True), {}, log_callback=lambda m: None).verification.alternate_success_present())
        self.assertFalse(TicketMonitor(Driver(False), {}, log_callback=lambda m: None).verification.alternate_success_present())

        class BadDriver:
            def execute_script(self, script, *args):
                raise RuntimeError("boom")

        self.assertFalse(TicketMonitor(BadDriver(), {}, log_callback=lambda m: None).verification.alternate_success_present())

    def test_alternate_submit_hands_off_on_verification(self):
        from test_orders import snapshot, intent
        from railwatch_order_page import OrderPage
        driver = Mock()
        driver.execute_script.return_value = snapshot(orders=[], dialogs=["请完成人脸核验"])
        self.assertEqual(OrderPage(driver).result(intent("alternate")).status, "verification")

    def test_run_single_loop_alternate_payment_publishes_order_stage(self):
        from railwatch_orders import OrderResult, OrderJournal
        from test_orders import CONFIG
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            orders, humans, hits = [], [], []
            monitor = TicketMonitor(Mock(), CONFIG, log_callback=lambda _: None,
                order_journal=OrderJournal(Path(tmp) / "orders.sqlite3"), run_id="test",
                on_order=lambda *args: orders.append(args), human_action_callback=humans.append, on_hit=hits.append)
            monitor.alternate_flow.try_alternate_order = Mock(return_value=OrderResult("pending_payment", order_id="E123456", evidence={"matched": True}))
            self.assertTrue(monitor._execute_order(("G101", "二等座", "候补", Mock(), Mock(), "alternate")))
            self.assertEqual(orders[-1][1].status, "pending_payment")
            self.assertEqual(hits, [])
            self.assertEqual(len(humans), 0)

    def test_run_single_loop_alternate_failed_hands_off_and_stops(self):
        from railwatch_orders import OrderResult, OrderJournal
        from test_orders import CONFIG
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            orders, humans, hits = [], [], []
            monitor = TicketMonitor(Mock(), CONFIG, log_callback=lambda _: None,
                order_journal=OrderJournal(Path(tmp) / "orders.sqlite3"), run_id="test",
                on_order=lambda *args: orders.append(args), human_action_callback=humans.append, on_hit=hits.append)
            monitor.alternate_flow.try_alternate_order = Mock(return_value=OrderResult("unknown", no_order=False))
            self.assertTrue(monitor._execute_order(("G101", "二等座", "候补", Mock(), Mock(), "alternate")))
            self.assertEqual(orders[-1][1].status, "unknown")
            self.assertEqual(hits, [])
            self.assertEqual(len(humans), 1)

    def test_run_single_loop_alternate_not_submitted_hands_off(self):
        from railwatch_orders import OrderResult, OrderJournal
        from test_orders import CONFIG
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            orders, humans, hits = [], [], []
            monitor = TicketMonitor(Mock(), CONFIG, log_callback=lambda _: None,
                order_journal=OrderJournal(Path(tmp) / "orders.sqlite3"), run_id="test",
                on_order=lambda *args: orders.append(args), human_action_callback=humans.append, on_hit=hits.append)
            monitor.alternate_flow.try_alternate_order = Mock(return_value=OrderResult("not_submitted", no_order=True))
            self.assertTrue(monitor._execute_order(("G101", "二等座", "候补", Mock(), Mock(), "alternate")))
            self.assertEqual(orders[-1][1].status, "not_submitted")
            self.assertEqual(hits, [])
            self.assertEqual(len(humans), 1)

    def test_run_single_loop_alternate_human_stops_without_hit_or_double_signal(self):
        from railwatch_orders import OrderResult, OrderJournal
        from test_orders import CONFIG
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            orders, humans, hits = [], [], []
            monitor = TicketMonitor(Mock(), CONFIG, log_callback=lambda _: None,
                order_journal=OrderJournal(Path(tmp) / "orders.sqlite3"), run_id="test",
                on_order=lambda *args: orders.append(args), human_action_callback=humans.append, on_hit=hits.append)
            monitor.alternate_flow.try_alternate_order = Mock(return_value=OrderResult("verification", no_order=False))
            self.assertTrue(monitor._execute_order(("G101", "二等座", "候补", Mock(), Mock(), "alternate")))
            self.assertEqual(orders[-1][1].status, "verification")
            self.assertEqual(hits, [])
            self.assertEqual(len(humans), 1)

    def test_verification_present_reflects_driver_result_and_is_safe(self):
        class Driver:
            def __init__(self, value):
                self.value = value

            def execute_script(self, script, *args):
                return self.value

        self.assertTrue(TicketMonitor(Driver(True), {}, log_callback=lambda m: None).verification.verification_present())
        self.assertFalse(TicketMonitor(Driver(False), {}, log_callback=lambda m: None).verification.verification_present())

        class BadDriver:
            def execute_script(self, script, *args):
                raise RuntimeError("boom")

        self.assertFalse(TicketMonitor(BadDriver(), {}, log_callback=lambda m: None).verification.verification_present())

    def test_unknown_burst_timeout_preserves_timeout_and_backoff(self):
        # 定时爆发期：单轮等待压缩到秒级，失败立即关弹窗重试，避免一次空等耗尽爆发窗口
        dismissed = []
        sleeps = []
        observed_timeouts = []

        class ServerTime:
            def is_in_burst_window(self, target_time, prepare_seconds, burst_seconds):
                return True

        class Driver:
            def refresh(self):
                return None

        monitor = TicketMonitor(
            Driver(),
            {"interval": 3, "query_timeout": 40, "timer_enabled": True, "target_time": "08:30:00"},
            log_callback=lambda msg: None,
            server_time_sync=ServerTime(),
        )
        monitor.click_query_button = lambda: True
        monitor._dismiss_query_blockers = lambda: dismissed.append("x") or ""

        def wait_for_rows(timeout=40, stop_check=None):
            observed_timeouts.append(timeout)
            return False

        monitor.wait_for_rows = wait_for_rows

        with patch("gui_12306_0.time.sleep", lambda seconds: sleeps.append(seconds)):
            monitor._run_single_loop(1, 3)

        self.assertEqual(observed_timeouts, [40])
        self.assertEqual(sleeps, [3])
        self.assertEqual(len(dismissed), 0)

    def test_non_burst_monitor_keeps_configured_query_timeout(self):
        # 非定时监控不得擅自压缩用户配置的 query_timeout
        observed_timeouts = []

        class Driver:
            def refresh(self):
                return None

        monitor = TicketMonitor(
            Driver(),
            {"interval": 3, "query_timeout": 23},
            log_callback=lambda msg: None,
        )
        monitor.click_query_button = lambda: True
        monitor._dismiss_query_blockers = lambda: ""

        def wait_for_rows(timeout=40, stop_check=None):
            observed_timeouts.append(timeout)
            return False

        monitor.wait_for_rows = wait_for_rows

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            monitor._run_single_loop(1, 3)

        self.assertEqual(observed_timeouts, [23])

    def test_monitor_syncs_query_params_from_config(self):
        # 监控循环要主动同步出发/到达/日期：普通轮只写一次，深度刷新轮重新同步
        fills = []

        class Driver:
            def refresh(self):
                return None

            def execute_script(self, script, *args):
                return None

        monitor = TicketMonitor(
            Driver(),
            {
                "from_station_cn": "北京",
                "to_station_cn": "上海",
                "date": "2026-09-20",
                "query_timeout": 1,
            },
            log_callback=lambda msg: None,
            param_filler=lambda from_cn, to_cn, date: fills.append((from_cn, to_cn, date)) or True,
        )
        monitor.query_executor = Mock()
        monitor.query_executor.snapshot_form.return_value = {"page":"one", "values":["北京","BJP","上海","SHH","2026-09-20"]}
        monitor.query_executor.execute.return_value = {"status":"ok"}
        monitor.query_executor.current.return_value = True
        monitor.row_parser.snapshot_rows = Mock(return_value=[])
        monitor.click_query_button = lambda: True
        monitor.wait_for_rows = lambda timeout=40, stop_check=None: True
        monitor._find_hit_row = lambda indices: None

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            monitor._run_single_loop(1, 1)
            monitor._run_single_loop(2, 1)
            monitor._run_single_loop(5, 1)

        self.assertEqual(
            fills,
            [
                ("北京", "上海", "2026-09-20"),
            ],
        )

    def test_monitor_without_param_filler_skips_param_sync(self):
        class Driver:
            def refresh(self):
                return None

            def execute_script(self, script, *args):
                return None

        monitor = TicketMonitor(
            Driver(),
            {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-09-20"},
            log_callback=lambda msg: None,
        )
        monitor.click_query_button = lambda: True
        monitor.wait_for_rows = lambda timeout=40, stop_check=None: False

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            monitor._run_single_loop(1, 1)  # 不应抛异常

    def test_dismiss_query_blockers_reports_dialog_text_and_is_safe(self):
        driver = Mock()
        driver.execute_script.side_effect = [{"kind":"not_on_sale", "text":"未到起售时间"}, True]
        monitor = TicketMonitor(driver, {}, log_callback=lambda message: None)
        self.assertEqual(monitor._dismiss_query_blockers(), "未到起售时间")
        for kind in ("human_action", "unknown"):
            driver.reset_mock()
            driver.execute_script.side_effect = [{"kind":kind, "text":"确认订单"}]
            monitor.human_action = Mock()
            self.assertEqual(monitor._dismiss_query_blockers(), "")
            self.assertEqual(driver.execute_script.call_count, 1)
            monitor.human_action.assert_called_once()

    def test_page_analyzer_fill_query_form_validates_and_fills(self):
        analyzer = PageAnalyzer(FakePageDriver(), log_callback=lambda msg: None, base_dir=".")
        analyzer.driver.execute_script = Mock(return_value=True)
        analyzer.resolver = type("Resolver", (), {"get_code": lambda self, name: f"{name}站码"})()

        # 缺任一参数不触发页面操作
        self.assertFalse(analyzer.fill_query_form("", "上海", "2026-06-10"))

        with patch("gui_12306_0.WebDriverWait", SuccessfulWait):
            self.assertTrue(analyzer.fill_query_form("北京", "上海", "2026-06-10"))

        class MissingInputsDriver:
            def execute_script(self, script, *args):
                return False

        analyzer_missing = PageAnalyzer(MissingInputsDriver(), log_callback=lambda msg: None, base_dir=".")
        analyzer_missing.resolver = type("Resolver", (), {"get_code": lambda self, name: f"{name}站码"})()
        with patch("gui_12306_0.WebDriverWait", SuccessfulWait):
            self.assertFalse(analyzer_missing.fill_query_form("北京", "上海", "2026-06-10"))


class TicketMonitorDateRangeTests(unittest.TestCase):
    def test_monitor_applies_date_range_dates_by_loop(self):
        driver = FakeDateCyclingDriver()
        monitor = TicketMonitor(
            driver,
            {"date": "2026-06-10", "date_range": "±1天"},
            log_callback=lambda msg: None,
        )

        monitor._apply_loop_date(1)
        monitor._apply_loop_date(2)
        monitor._apply_loop_date(3)
        monitor._apply_loop_date(4)

        applied_dates = [args[0] for script, args in driver.scripts if "train_date" in script]
        self.assertEqual(applied_dates, ["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-09"])

    def test_refresh_round_reapplies_travel_date_after_refresh(self):
        driver = FakeRefreshDateDriver()
        monitor = TicketMonitor(
            driver,
            {"date": "2026-06-10", "date_range": "单日", "query_timeout": 1},
            log_callback=lambda msg: None,
        )
        monitor.current_loop_date = "2026-06-10"
        monitor.click_query_button = lambda: True
        monitor.wait_for_rows = lambda timeout=40, stop_check=None: False

        with patch("gui_12306_0.time.sleep", lambda seconds: None):
            monitor._run_single_loop(5, 1)

        self.assertEqual(driver.events, [])


if __name__ == "__main__":
    unittest.main()
