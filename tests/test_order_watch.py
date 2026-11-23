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

    def observe_once(self, previous, bridge=None):
        bridge = bridge or self.bridge
        task = bridge._task
        task.cancel.clear()
        with patch("railwatch_bridge.OrderPage", return_value=self.page), \
                patch.object(bridge, "_task_wait", side_effect=lambda task, _: task.cancel.set()):
            bridge._observe_order(task, Mock(), self.intent, previous)

    def begin_another(self, kind):
        self.intent = OrderIntent(kind, "G101", "2026-10-10", "北京", "上海", "二等座", ("张三",))
        self.bridge.order_journal.begin(self.task.run_id, self.intent, self.task.config)

    def payment_events(self, bridge=None):
        bridge = bridge or self.bridge
        detail = bridge.order_journal.history_detail(self.intent.intent_id)
        return [event for event in detail["events"] if event["stage"] == "payment_urgent"]

    def run_monitor_with_active_order(self):
        self.bridge.driver = Mock()
        self.bridge._ensure_driver = Mock(return_value=self.bridge.driver)
        self.bridge._make_param_filler = Mock()
        self.bridge._prepare_query_page = Mock(return_value=True)
        self.bridge._check_session_for_task = Mock(return_value=True)
        self.bridge._valid_dates = Mock(return_value=[self.intent.date])
        self.bridge._start_monitor_heartbeat = Mock()
        monitor = Mock()
        monitor.run.side_effect = lambda: self.bridge._handle_order(
            self.intent, self.bridge.order_journal.record(self.intent, self.result("active")))
        with patch("railwatch_bridge.TicketMonitor", return_value=monitor), \
                patch("railwatch_bridge.OrderPage", return_value=self.page):
            self.bridge._monitor_worker(self.task.config, self.task)
        monitor.run.assert_called_once()
        self.assertTrue(self.task.done.is_set())
        self.assertNotEqual(self.task.status, "error")

    def test_monitor_first_observes_active_order_until_fulfilled(self):
        self.page.probe_known_order.return_value = self.result("fulfilled")
        self.run_monitor_with_active_order()
        self.page.probe_known_order.assert_called_once_with(self.intent, "E123456")
        self.page.result.assert_not_called()
        self.assertEqual(self.delays, [60])
        self.assertIsNone(self.bridge.order_journal.pending())
        self.assertEqual(self.bridge.state.order["status"], "fulfilled")
        self.assertFalse(self.bridge.state.order["observing"])

    def test_monitor_does_not_watch_initial_active_order_when_disabled(self):
        self.task.config["order_watch_enabled"] = False
        self.run_monitor_with_active_order()
        self.page.probe_known_order.assert_not_called()
        self.page.result.assert_not_called()
        self.assertEqual(self.delays, [])
        self.assertEqual(self.bridge.order_journal.pending()["result"]["status"], "active")

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

    def test_payment_reminder_obeys_official_deadline_boundaries(self):
        for index, remaining in enumerate((-1, 0, 1, 299, 300, 301)):
            with self.subTest(remaining=remaining), patch("time.time", side_effect=lambda: 1800000000 + self.now):
                self.now = 0
                if index:
                    self.begin_another("regular")
                self.bridge._notify_async.reset_mock()
                initial = self.bridge.order_journal.record(self.intent, replace(
                    self.result("pending_payment"), review={"payment_deadline_at": 1800000900 + remaining}))
                self.now = 900
                self.observe_once(initial)
                pending_status = self.bridge.order_journal.pending()["result"]["status"]
                self.bridge.order_journal.record(self.intent, self.result("expired"))
                expected = int(0 < remaining <= 300)
                self.assertEqual(self.bridge._notify_async.call_count, expected)
                self.assertEqual(len(self.payment_events()), expected)
                self.assertEqual(pending_status, "pending_payment")

    def test_payment_reminder_without_deadline_uses_first_official_observation(self):
        for index, (kind, threshold) in enumerate((("alternate", 720), ("regular", 300))):
            with self.subTest(kind=kind), patch("time.time", side_effect=lambda: 1800000000 + self.now):
                self.now = 100
                if index:
                    self.begin_another(kind)
                self.bridge._notify_async.reset_mock()
                self.bridge.order_journal.record(self.intent, self.result("pending_payment"))
                self.now = 250
                observed_again = self.bridge.order_journal.record(self.intent, self.result("pending_payment"))

                self.now = 100 + threshold - 1
                self.observe_once(observed_again)
                self.bridge._notify_async.assert_not_called()
                self.assertEqual(self.payment_events(), [])

                self.now += 1
                self.observe_once(observed_again)
                self.bridge._notify_async.assert_called_once()
                self.assertIn(f"已待支付 {threshold // 60} 分钟", self.bridge._notify_async.call_args.args[1])
                self.assertEqual(len(self.payment_events()), 1)
                self.bridge.order_journal.record(self.intent, self.result("expired"))

    def test_payment_reminder_is_private_and_deduplicated_across_observers_and_restart(self):
        with patch("time.time", return_value=1800000000):
            initial = self.bridge.order_journal.record(self.intent, replace(
                self.result("pending_payment"), review={"payment_deadline_at": 1800000180}))
            self.observe_once(initial)
            self.observe_once(initial)
            reopened = RailWatchBridge(self.bridge.data_dir)
            self.addCleanup(reopened.notification_service.close)
            reopened._notify_async = Mock()
            reopened.emit = Mock()
            reopened._task = MonitorTask(self.task.config)
            self.observe_once(OrderResult(**reopened.order_journal.pending()["result"]), reopened)

        self.bridge._notify_async.assert_called_once()
        title, message = self.bridge._notify_async.call_args.args
        event_id = f"order:{self.intent.intent_id}:payment_urgent"
        self.assertEqual(title, "待支付即将超时")
        self.assertEqual(self.bridge._notify_async.call_args.kwargs, {"event_type": "payment", "event_key": event_id})
        self.assertIn("预计剩余 3 分钟", message)
        self.assertIn("12306 官方页面", message)
        self.assertIn("G101", message)
        self.assertNotIn(self.intent.passengers[0], message)
        self.assertNotIn(initial.order_id, message)
        published = [call.args[1] for call in self.bridge.emit.call_args_list if call.args[0] == "notify"]
        self.assertEqual(published, [{"title": title, "message": message, "priority": "urgent", "event_id": event_id}])
        reopened._notify_async.assert_not_called()
        self.assertEqual(len(self.payment_events(reopened)), 1)

    def test_confirmed_same_status_refreshes_regular_and_alternate_review(self):
        for index, (kind, existing, latest) in enumerate((
            ("alternate", {"success_rate": 84, "prepay_amount": "661.0"}, {"payment_deadline_at": 1800000900}),
            ("regular", {"ticket_price": "661.0"}, {"seat_assignments": ["09车02A号"]}),
        )):
            with self.subTest(kind=kind), patch("time.time", side_effect=lambda: 1800000000 + self.now):
                if index:
                    self.begin_another(kind)
                self.task.cancel.clear()
                initial = self.bridge.order_journal.record(self.intent, replace(self.result("pending_payment"), review=existing))
                self.bridge._handle_order(self.intent, initial)
                self.bridge._notify_async.reset_mock()
                self.page.result.return_value = initial

                def refresh(*_args):
                    self.task.cancel.set()
                    return replace(self.result("pending_payment"), review=latest)

                self.page.probe_known_order.side_effect = refresh
                with patch("railwatch_bridge.OrderPage", return_value=self.page):
                    self.bridge._observe_order(self.task, Mock(), self.intent, initial)

                summary = self.bridge.order_journal.history_detail(self.intent.intent_id)["summary"]
                self.bridge.order_journal.record(self.intent, self.result("expired"))
                expected = {**existing, **latest}
                self.assertEqual(self.bridge.state.order["review"], expected)
                self.assertEqual(summary["review"], expected)
                self.assertEqual(summary["official_status"], "pending_payment")
                self.assertEqual(summary["order_id"], initial.order_id)
                self.assertEqual(summary["official_verified_at"], 1800000000 + self.now - 60)
                self.bridge._notify_async.assert_not_called()

    def test_probe_with_partial_review_keeps_countdown_seen_on_the_checkout_page(self):
        countdown = {"payment_deadline_at": 1800000900, "payment_countdown_observed_at": 1800000001}
        with patch("time.time", side_effect=lambda: 1800000000 + self.now):
            initial = self.bridge.order_journal.record(self.intent, self.result("pending_payment"))
            self.page.result.side_effect = lambda *_args, **_kwargs: replace(initial, review=countdown) if self.now == 1 else initial

            def probe(*_args):
                self.task.cancel.set()
                return replace(initial, review={"prepay_amount": "661.0"})

            self.page.probe_known_order.side_effect = probe
            with patch("railwatch_bridge.OrderPage", return_value=self.page):
                self.bridge._observe_order(self.task, Mock(), self.intent, initial)

        expected = {**countdown, "prepay_amount": "661.0"}
        self.assertEqual(self.bridge.state.order["review"], expected)
        self.assertEqual(self.bridge.order_journal.pending()["result"]["review"], expected)

    def test_unmatched_same_status_review_cannot_change_confirmed_evidence(self):
        original = {"ticket_price": "661.0"}
        initial = self.bridge.order_journal.record(self.intent, replace(self.result("pending_payment"), review=original))
        self.bridge._handle_order(self.intent, initial)
        self.bridge._notify_async.reset_mock()
        self.page.result.return_value = initial
        altered = replace(initial, review={"ticket_price": "1.0"})
        mismatched = iter([replace(altered, order_id="OTHER"), replace(altered, evidence={"matched": False})])

        def read(*_args):
            result = next(mismatched)
            if not result.evidence["matched"]:
                self.task.cancel.set()
            return result

        self.page.probe_known_order.side_effect = read
        with patch("railwatch_bridge.OrderPage", return_value=self.page):
            self.bridge._observe_order(self.task, Mock(), self.intent, initial)

        self.bridge.order_journal.refresh_review(replace(self.intent, train_code="G9"), altered)
        self.assertEqual(self.bridge.state.order["review"], original)
        summary = self.bridge.order_journal.history_detail(self.intent.intent_id)["summary"]
        self.assertEqual(summary["review"], original)
        self.assertEqual(summary["order_id"], initial.order_id)
        self.assertTrue(summary["recovery_required"])
        self.bridge._notify_async.assert_not_called()

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
