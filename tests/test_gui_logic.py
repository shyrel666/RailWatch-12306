import unittest
import sys
import types
from unittest.mock import patch

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
        analyzer.resolver = type("Resolver", (), {"get_code": lambda self, name: f"{name}站码"})()
        analyzer.click_query_button = lambda: True
        analyzer._parse_rows = lambda: [{"train": "G101", "raw": "G101 二等座 有"}]
        observed_timeout = []

        def wait_for_rows(timeout=40, stop_check=None):
            observed_timeout.append(timeout)
            return True

        analyzer.wait_for_rows = wait_for_rows

        with patch("gui_12306_0.WebDriverWait", SuccessfulWait):
            rows = analyzer.open_fill_query_and_analyze(
                {
                    "from_station_cn": "北京",
                    "to_station_cn": "上海",
                    "date": "2026-06-10",
                    "query_timeout": 25,
                }
            )

        self.assertEqual(rows, [{"train": "G101", "raw": "G101 二等座 有"}])
        self.assertEqual(observed_timeout, [25])

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
        driver = FakeDriver()
        monitor = TicketMonitor(
            driver,
            {"auto_submit": True, "passenger_count": 1, "passengers": ""},
            log_callback=lambda msg: None,
        )

        with patch("gui_12306_0.WebDriverWait", FakeWait), patch("gui_12306_0.time.sleep", lambda seconds: None):
            monitor._try_auto_submit(FakeButton(), "一等座")

        self.assertTrue(driver.selection_attempted)
        self.assertFalse(driver.submit_button.clicked)

    def test_alternate_submit_aborts_when_no_passenger_selected(self):
        driver = FakeAlternateDriver()
        monitor = TicketMonitor(
            driver,
            {"auto_alternate": True, "passenger_count": 1, "passengers": ""},
            log_callback=lambda msg: None,
        )

        with patch("gui_12306_0.WebDriverWait", FakeWait), patch("gui_12306_0.time.sleep", lambda seconds: None):
            monitor._try_alternate_order(FakeAlternateRow(), "G101", "二等座")

        self.assertTrue(driver.selection_attempted)
        self.assertFalse(driver.submit_button.clicked)


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

        self.assertEqual(driver.events, ["refresh", "date:2026-06-10"])


if __name__ == "__main__":
    unittest.main()
