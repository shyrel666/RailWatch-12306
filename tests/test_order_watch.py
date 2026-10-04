"""Persistent read-only observation, state transitions and bounded backoff."""
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_orders import OrderIntent, OrderResult
from railwatch_task import MonitorTask


class OrderWatchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bridge = RailWatchBridge(directory.name)
        self.addCleanup(self.bridge.notification_service.close)
        self.bridge._notify_async = Mock()
        self.bridge.emit = Mock()
        self.intent = OrderIntent("alternate", "G101", "2026-10-10", "北京", "上海", "二等座", ("张三",))
        self.task = self.bridge._task = MonitorTask({"order_watch_enabled": True, "order_watch_interval_seconds": 60})
        self.bridge.order_journal.begin(self.task.run_id, self.intent, self.task.config)
        self.now, self.delays = 0.0, []
        self.bridge._task_wait = self.wait
        self.clock = patch("time.monotonic", lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.page = Mock()

    def wait(self, task, delay):
        self.assertGreater(delay, 0)
        self.delays.append(delay)
        self.now += delay
        if self.now > 100000:
            self.fail("observer did not stop")

    def result(self, status):
        return OrderResult(status, order_id="E123456", evidence={"matched": True})

    def observe(self, previous="active"):
        initial = self.bridge.order_journal.record(self.intent, self.result(previous))
        with patch("railwatch_bridge.OrderPage", return_value=self.page):
            self.bridge._observe_order(self.task, Mock(), self.intent, initial)

    def test_active_order_is_checked_beyond_ten_minutes_and_fulfillment_releases_lock(self):
        self.page.probe_known_order.side_effect = [self.result("active")] * 12 + [self.result("fulfilled")]
        self.observe()
        self.assertEqual(self.now, 780)
        self.assertIsNone(self.bridge.order_journal.pending())
        self.assertEqual(self.bridge._notify_async.call_count, 1)
        self.assertEqual(self.bridge.state.order["status"], "fulfilled")
        self.assertFalse(self.bridge.state.order["observing"])
        self.page.result.assert_not_called()

    def test_payment_transitions_to_active_then_continues_in_separate_probes(self):
        self.page.result.return_value = self.result("active")
        self.page.probe_known_order.side_effect = [self.result("active"), self.result("fulfilled")]
        self.observe("pending_payment")
        self.assertEqual(self.page.result.call_count, 1)
        self.assertEqual(self.page.probe_known_order.call_count, 2)
        self.assertEqual(self.bridge._notify_async.call_count, 2)
        self.assertIsNone(self.bridge.order_journal.pending())

    def test_failed_probes_back_off_without_overwriting_last_official_state(self):
        original = self.bridge.order_journal.record(self.intent, self.result("active"))
        def stop_after_failures(*args):
            self.task.cancel.set()
            return OrderResult("unknown")
        responses = iter([OrderResult("unknown"), RuntimeError("offline"), *[OrderResult("unknown")] * 4, None])
        def read(*args):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return stop_after_failures() if value is None else value
        self.page.probe_known_order.side_effect = read
        with patch("railwatch_bridge.OrderPage", return_value=self.page):
            self.bridge._observe_order(self.task, Mock(), self.intent, original)
        self.assertEqual(self.delays, [60, 120, 240, 480, 600, 600, 600])
        pending = self.bridge.order_journal.pending()
        self.assertEqual(pending["result"]["status"], "active")
        self.assertEqual(pending["result"]["order_id"], "E123456")
        self.bridge._notify_async.assert_not_called()

    def test_official_terminal_evidence_stops_observation_and_releases_lock(self):
        for index, status in enumerate(("cancelled", "expired", "failed")):
            with self.subTest(status=status):
                if index:
                    self.intent = replace(self.intent, intent_id=status)
                    self.bridge.order_journal.begin(self.task.run_id, self.intent, self.task.config)
                self.page.probe_known_order.return_value = self.result(status)
                self.observe()
                self.assertIsNone(self.bridge.order_journal.pending())
                self.assertEqual(self.bridge.state.order["status"], status)
                self.assertFalse(self.bridge.state.order["observing"])

    def test_login_verification_pauses_and_keeps_bound_order(self):
        self.page.probe_known_order.return_value = OrderResult("verification", "请重新登录")
        self.observe()
        self.assertTrue(self.task.cancel.is_set())
        self.assertEqual(self.bridge.order_journal.pending()["result"]["order_id"], "E123456")
        self.assertEqual(self.bridge.state.human_action["message"], "请重新登录")

    def test_stale_unpaid_state_cannot_regress_active_order(self):
        def read(*args):
            self.task.cancel.set()
            return self.result("pending_payment")
        self.page.probe_known_order.side_effect = read
        self.observe()
        self.assertEqual(self.bridge.order_journal.pending()["result"]["status"], "active")
        self.bridge._notify_async.assert_not_called()

    def test_stopping_during_wait_performs_no_read_and_restart_does_not_start_browser(self):
        self.bridge._task_wait = lambda task, delay: task.cancel.set()
        self.observe()
        self.page.probe_known_order.assert_not_called()
        with patch.object(RailWatchBridge, "_ensure_driver") as ensure:
            restored = RailWatchBridge(self.bridge.data_dir)
            self.addCleanup(restored.notification_service.close)
            ensure.assert_not_called()
            self.assertFalse(restored.is_monitoring)
            self.assertEqual(restored.order_journal.pending()["result"]["order_id"], "E123456")


if __name__ == "__main__":
    unittest.main()
