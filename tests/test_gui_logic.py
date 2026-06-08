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

from gui_12306_0 import BaseHandler, QueryConfig, TicketMonitor


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


if __name__ == "__main__":
    unittest.main()
