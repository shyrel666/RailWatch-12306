"""Actual Chrome + visible DOM; isolated profile and blocked railway network."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent


class OrderBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = tempfile.TemporaryDirectory(prefix="railwatch-order-browser-")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument(f"--user-data-dir={cls.profile.name}")
        cls.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
        cls.driver.execute_cdp_cmd("Network.enable", {})
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*"]})

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile.cleanup()

    def setUp(self):
        self.driver.get((Path(__file__).parent / "fixtures/orders.html").resolve().as_uri())
        self.page = OrderPage(self.driver, allow_fixture=True)
        self.intent = OrderIntent("regular", "G101", "2026-09-10", "北京", "上海", "二等座", ("张三",), "18:00")

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def test_regular_order_verified_once_then_payment_observed(self):
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual((result.status, result.order_id), ("pending_payment", "E123456"))
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])
        self.js("fixture.record('已支付')")
        self.assertEqual(self.page.result(self.intent, known_id="E123456").status, "fulfilled")

    def test_candidate_order_binds_combination_and_payment_does_not_mean_fulfilled(self):
        selected = replace(self.intent, kind="alternate")
        result = self.page.alternate(self.driver.find_element("id", "candidate"), selected)
        self.assertEqual(result.status, "pending_payment")
        self.js("fixture.record('待兑现')")
        self.assertEqual(self.page.result(selected, known_id=result.order_id).status, "active")
        self.js("fixture.record('兑现成功')")
        self.assertEqual(self.page.result(selected, known_id=result.order_id).status, "fulfilled")
        self.assertEqual(self.js("return fixture.alternateClicks"), 1)

    def test_wrong_candidate_seat_and_extra_choices_never_submit(self):
        for script in ["document.querySelector('.ticket-info-txt span').innerText='一等座'",
                       "document.getElementById('addTrainInput').checked=true",
                       "document.getElementById('is_open').innerText='已开启'",
                       "document.getElementById('planList').innerHTML='<div class=group-ticket>G102</div>'"]:
            self.setUp()
            self.js(script)
            result = self.page.alternate(self.driver.find_element("id", "candidate"), replace(self.intent, kind="alternate"))
            self.assertEqual(result.status, "verification")
            self.assertEqual(self.js("return fixture.alternateClicks"), 0)

    def test_deadline_selection_failure_never_submits(self):
        result = self.page.alternate(self.driver.find_element("id", "candidate"), replace(self.intent, kind="alternate", deadline="19:30"))
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.alternateClicks"), 0)

    def test_duplicate_passenger_name_rejected(self):
        self.js("document.getElementById('normal_passenger_id').innerHTML+='<label title=张三><input type=checkbox>张三</label>'")
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.regularClicks"), 0)

    def test_sold_out_before_submission_can_fallback(self):
        self.js("fixture.mode='sold_out'")
        self.assertTrue(self.page.regular(self.driver.find_element("id", "book"), self.intent).can_fallback)
        self.assertEqual(self.js("return fixture.regularClicks"), 0)

    def test_verification_after_submit_does_not_confirm_or_retry(self):
        self.js("fixture.mode='verification'")
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 0])

    def test_generic_success_does_not_create_order_evidence(self):
        self.js("document.getElementById('records').innerHTML='<div class=success-tip>候补成功</div>'")
        self.assertEqual(self.page.result(replace(self.intent, kind="alternate")).status, "unknown")

    def test_order_identity_passengers_and_seat_must_match(self):
        self.js("fixture.record()")
        for changed in [replace(self.intent, seat="一等座"), replace(self.intent, train_code="G102"), replace(self.intent, passengers=("李四",)), replace(self.intent, date="2026-09-11")]:
            self.assertEqual(self.page.result(changed).status, "unknown")

    def test_accepted_confirmation_then_transport_failure_still_reads_order_without_retry(self):
        original_button = self.page.button
        def button(selectors):
            found = original_button(selectors)
            if found and selectors == ("#qr_submit_id",):
                def click():
                    found.click()
                    raise TimeoutError("Response lost after server acceptance")
                return Mock(click=click)
            return found
        self.page.button = button
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])

    def test_timeout_or_stop_after_submit_never_replays_or_reports_sold_out(self):
        self.js("fixture.mode='timeout'")
        original_poll = self.page.poll
        self.page.poll = lambda predicate, timeout=10: original_poll(predicate, min(timeout, 0.2))
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.can_fallback)
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 0])
        self.page.stop = lambda: True
        self.assertEqual(self.page.wait_result(self.intent).status, "unknown")
        self.assertEqual(self.js("return fixture.regularClicks"), 1)

    def test_relative_deadline_selects_offered_equivalent_and_reads_back(self):
        self.js("document.querySelector('#date_box li').innerText='开车前1小时'")
        result = self.page.alternate(self.driver.find_element("id", "candidate"), replace(self.intent, kind="alternate", deadline="开车前60分钟"))
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return document.getElementById('dafaultTime').innerText"), "开车前1小时")


if __name__ == "__main__":
    unittest.main(verbosity=2)
