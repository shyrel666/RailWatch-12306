"""Fault injection for the 2026-09-27 review; no railway requests."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_runtime import RailWatchRuntime
from railwatch_bridge import RailWatchBridge, is_session_lost, driver_session_alive
from railwatch_task import MonitorTask


def intent():
    return OrderIntent("regular", "G101", "2026-09-10", "北京", "上海", "二等座", ("张三",))


class TransactionEvidenceTests(unittest.TestCase):
    def test_missing_receipt_is_not_dispatched_and_never_retried(self):
        for receipt in (None, RuntimeError("transport")):
            with self.subTest(receipt=receipt):
                driver = Mock()
                driver.execute_script.side_effect = [True, receipt]
                marks = []
                page = OrderPage(driver, mark=lambda stage, detail=None: marks.append(stage))
                page.poll = Mock()
                button = Mock()
                outcome = page._click_regular_confirmation(button, intent())
                self.assertEqual(getattr(outcome, "value", outcome), "unknown")
                button.click.assert_called_once()
                page.poll.assert_not_called()
                self.assertNotIn("regular_confirm_dispatched", marks)

    def test_empty_page_cannot_clear_a_submitted_intent(self):
        page = OrderPage(Mock())
        page.snapshot = lambda: {"pendingEmpty": True, "orders": []}
        self.assertEqual(page.result(intent(), submitted=True, allow_empty=True).status, "unknown")

    def test_journal_defends_against_incorrect_no_order_after_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = OrderJournal(Path(tmp) / "orders.sqlite3")
            target = intent()
            journal.begin("run", target, {})
            journal.mark("run", "regular_submit", target.intent_id)
            result = journal.record(target, OrderResult("not_submitted", no_order=True))
            self.assertEqual(result.status, "unknown")
            self.assertIsNotNone(journal.pending())
            with self.assertRaises(RuntimeError):
                journal.begin("other", intent(), {})


class RuntimeReliabilityTests(unittest.TestCase):
    def test_invalid_lines_do_not_terminate_or_dispatch_and_valid_request_survives(self):
        output = []
        bridge = Mock()
        bridge.get_runtime_info.return_value = {"ready": True}
        runtime = RailWatchRuntime(bridge=bridge, writer=output.append)
        try:
            for line in (b'\xff', 'null', '[]', '1', '"x"', '{',
                         '{"id":"bad","command":[],"payload":{}}',
                         '{"id":"bad","command":"getRuntimeInfo","payload":[]}'):
                runtime.handle_line(line).result()
            bridge.get_runtime_info.assert_not_called()
            runtime.handle_line('{"id":"valid","command":"getRuntimeInfo","payload":{}}').result()
            self.assertEqual(output[-1]["result"], {"ready": True})
            self.assertFalse(any(item.get("event") == "runtimeError" for item in output))
        finally:
            runtime.shutdown()

    def test_slow_passenger_read_keeps_activity_responsive_and_releases_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            entered, release = threading.Event(), threading.Event()
            def read(_script):
                entered.set()
                release.wait(3)
                return []
            bridge.driver = Mock(window_handles=["one"])
            bridge.driver.execute_script.side_effect = read
            worker = threading.Thread(target=bridge.read_passengers)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                answered = threading.Event()
                activity = []
                probe = threading.Thread(target=lambda: (activity.append(bridge.task_activity()), answered.set()))
                probe.start()
                self.assertTrue(answered.wait(0.5), "task lock held across browser I/O")
                probe.join(1)
                self.assertEqual(activity[0]["operation"], "read_passengers")
                with self.assertRaises(RuntimeError):
                    bridge.read_passengers()
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(bridge._browser_busy)

    def test_transport_error_is_not_session_death_but_dead_service_is(self):
        self.assertFalse(is_session_lost(RuntimeError("connection refused; max retries exceeded")))
        driver = Mock(window_handles=["one"])
        driver.service.process.poll.return_value = 1
        self.assertFalse(driver_session_alive(driver))


class RecoveryStateTests(unittest.TestCase):
    def test_order_observation_has_a_budget_and_preserves_pending_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._notify_async = Mock()
            target = intent()
            task = bridge._task = MonitorTask({})
            result = OrderResult("pending_payment", order_id="E123456", evidence={"matched": True})
            bridge.order_journal.begin(task.run_id, target, {})
            bridge.order_journal.record(target, result)
            bridge._handle_order(target, result)
            elapsed, delays = [0.0], []
            def wait(_task, seconds):
                delays.append(seconds)
                elapsed[0] += seconds
            bridge._task_wait = wait
            with patch("railwatch_bridge.OrderPage") as page, patch("railwatch_bridge.time.monotonic", lambda: elapsed[0]), patch("railwatch_bridge.ORDER_OBSERVATION_SECONDS", 90):
                page.return_value.result.return_value = result
                bridge._observe_order(task, Mock(), target, result)
            bridge._finish_task(task)
            self.assertEqual(elapsed[0], 90)
            self.assertIn(15, delays)
            self.assertFalse(bridge.state.monitoring)
            self.assertEqual(bridge.state.phase.value, "order")
            self.assertEqual(bridge.order_journal.pending()["result"]["status"], "pending_payment")
            self.assertIn("停止自动核对", bridge.state.human_action["message"])
            recovered = RailWatchBridge(tmp)
            self.assertTrue(recovered.get_runtime_info()["state"]["human_action"])

    def test_stored_complete_history_can_have_a_truncated_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = OrderJournal(Path(tmp) / "orders.sqlite3")
            target = intent()
            journal.begin("run", target, {})
            journal.record(target, OrderResult("unknown"))
            with journal.connection() as db:
                db.executemany("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)",
                               [("run", target.intent_id, "check", index, index, "{}") for index in range(510)])
            detail = journal.history_detail(target.intent_id)
            self.assertTrue(detail["history_complete"])
            self.assertTrue(detail["events_truncated"])
            self.assertEqual(len(detail["events"]), 500)


if __name__ == "__main__":
    unittest.main()
