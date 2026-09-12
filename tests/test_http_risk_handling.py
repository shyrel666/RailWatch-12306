"""HTTP cooldown and ambiguous confirmation regressions; no railway requests."""
import unittest
from unittest.mock import Mock, patch

from gui_12306_0 import TicketMonitor
from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent, OrderResult
from railwatch_query import parse_retry_after


class RetryAfterTests(unittest.TestCase):
    def test_seconds_and_http_dates_use_the_response_clock(self):
        self.assertEqual(parse_retry_after(" 120 "), 120)
        self.assertEqual(parse_retry_after("0"), 0)
        # Independent of the local machine's date or clock offset.
        self.assertEqual(parse_retry_after("Sat, 12 Sep 2026 08:02:00 GMT",
                                           "Sat, 12 Sep 2026 08:00:00 GMT"), 120)
        self.assertEqual(parse_retry_after("Sat, 12 Sep 2026 07:59:00 GMT",
                                           "Sat, 12 Sep 2026 08:00:00 GMT"), 0)
        with patch("railwatch_query.time.time", return_value=0):
            self.assertEqual(parse_retry_after("Thu, 01 Jan 1970 00:02:00 GMT"), 120)
            self.assertEqual(parse_retry_after("Thu, 01 Jan 1970 00:02:00 GMT", "invalid"), 120)

    def test_invalid_headers_do_not_become_an_immediate_retry(self):
        for value in (None, "", "invalid", "-1", "1.5", "NaN", "Infinity", "9" * 400, "１２０",
                      "Sat, 12 Sep 2026 08:02:00"):
            with self.subTest(value=value):
                self.assertIsNone(parse_retry_after(value))


class HttpRiskHandlingTests(unittest.TestCase):
    def monitor(self, result, smart=True):
        monitor = TicketMonitor(Mock(), {"interval": 3, "smart_rate": smart, "request_mode": "fast"},
                                log_callback=lambda _: None, server_time_sync=Mock())
        monitor.query_executor = Mock()
        monitor.query_executor.execute.return_value = result
        monitor._is_burst_mode = Mock(return_value=True)
        monitor._sleep = Mock()
        monitor._signal_human_action = Mock()
        monitor.row_parser.snapshot_rows = Mock()
        return monitor

    def test_server_cooldown_exceeds_mode_cap_even_without_smart_rate(self):
        for smart in (True, False):
            with self.subTest(smart=smart):
                monitor = self.monitor({"status": "rate_limited", "http_status": 429,
                                        "retry_after_seconds": 120}, smart)
                with patch("anti_detect.random.uniform", return_value=0):
                    self.assertFalse(monitor._run_single_loop(1, 3))
                monitor._sleep.assert_called_once_with(120)
                monitor.driver.get.assert_not_called()
                monitor.row_parser.snapshot_rows.assert_not_called()
                monitor._signal_human_action.assert_not_called()
                if smart:
                    self.assertTrue(monitor.rate_limiter.risk_detected)

    def test_missing_cooldown_pauses_instead_of_retrying(self):
        for smart in (True, False):
            with self.subTest(smart=smart):
                monitor = self.monitor({"status": "rate_limited", "http_status": 429,
                                        "retry_after_seconds": None}, smart)
                self.assertTrue(monitor._run_single_loop(1, 3))
                monitor._signal_human_action.assert_called_once()
                monitor._sleep.assert_not_called()
                monitor.driver.get.assert_not_called()
                monitor.row_parser.snapshot_rows.assert_not_called()

    def test_zero_retry_after_does_not_bypass_local_backoff(self):
        monitor = self.monitor({"status": "rate_limited", "http_status": 429,
                                "retry_after_seconds": 0})
        with patch("anti_detect.random.uniform", return_value=0):
            self.assertFalse(monitor._run_single_loop(1, 3))
        monitor._sleep.assert_called_once_with(7.5)

    def test_server_unavailable_obeys_cooldown_without_false_risk_signal(self):
        monitor = self.monitor({"status": "server_backoff", "http_status": 503,
                                "retry_after_seconds": 120})
        self.assertFalse(monitor._run_single_loop(1, 3))
        monitor._sleep.assert_called_once_with(120)
        self.assertFalse(monitor.rate_limiter.risk_detected)
        monitor.driver.get.assert_not_called()


class AmbiguousConfirmationTests(unittest.TestCase):
    def test_delayed_confirmation_receipt_is_resolved_without_reclick(self):
        intent = OrderIntent("regular", "G101", "2026-09-12", "北京", "上海", "二等座", ("张三",))
        page = OrderPage(Mock())
        page.snapshot = Mock(return_value={"formReady": True, "confirmation": True})
        page.result = Mock(return_value=OrderResult("unknown"))
        page.prepare_people = Mock(return_value=True)
        page.select_regular_seats = Mock(return_value=True)
        page.verify_form = Mock(return_value=True)
        submit = Mock()
        confirm = Mock()
        confirm.click.side_effect = TimeoutError("Acknowledgement lost after accepted action")
        page.button = Mock(side_effect=lambda selectors: confirm if selectors == ("#qr_submit_id",) else submit)
        page._post_submit = Mock(return_value=OrderResult("pending_payment", order_id="E123"))
        result = page.regular(Mock(), intent)
        self.assertEqual(result.status, "pending_payment")
        confirm.click.assert_called_once()
        page._post_submit.assert_called_once_with(intent, True)


if __name__ == "__main__":
    unittest.main()
