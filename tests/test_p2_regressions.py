"""Behavior regressions for the confirmed v0.4.2 P2 review findings."""
import tempfile
import threading
import time
import unittest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_notify import NotificationService
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_task import MonitorTask
from railwatch_trip_choices import load_trip_choices, save_train_favorites


class NotificationQueueTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.service = NotificationService({
            "server_chan_enabled": True, "server_chan_key": "fake",
            "wecom_webhook_enabled": True, "wecom_webhook_url": "unused",
            "event_channels": {"hit": ["server_chan"]},
        })
        self.service._send_server_chan = Mock(side_effect=lambda *_: self.release.wait(3) or True)
        self.service._send_wecom = Mock(return_value=True)

    def tearDown(self):
        self.release.set()
        if hasattr(self.service, "close"):
            self.service.close()
        else:
            self.service._executor.shutdown(wait=True)

    def fill_slow_channel(self):
        for index in range(20):
            result = self.service.enqueue("fill", "test", event_type="hit", event_key=f"fill-{index}")
            if result["server_chan"]["status"] == "queue_full":
                return
        self.fail("Notification queue must be bounded")

    def test_busy_channel_does_not_delay_other_channel(self):
        fast = threading.Event()
        self.service._send_wecom.side_effect = lambda *_: fast.set() or True
        self.fill_slow_channel()
        result = self.service.enqueue("payment", "test", event_type="payment", event_key="order-1")
        self.assertEqual(result["server_chan"]["status"], "queue_full")
        self.assertEqual(result["wecom_webhook"]["status"], "queued")
        self.assertTrue(fast.wait(1), "Fast channel must finish while slow channel is still blocked")

    def test_partial_admission_retries_only_the_channel_that_was_not_queued(self):
        self.fill_slow_channel()
        first = self.service.enqueue("payment", "test", event_type="payment", event_key="order-1")
        self.assertEqual(first["server_chan"]["status"], "queue_full")
        self.assertEqual(first["wecom_webhook"]["status"], "queued")
        self.assertEqual(self.service.status()["server_chan"]["status"], "queue_full")
        self.release.set()
        # Deterministic barriers wait for sends and their capacity callbacks.
        for executor in self.service._executors.values():
            executor.submit(lambda: None).result(timeout=2)
        self.service._send_server_chan.reset_mock()
        self.service._send_wecom.reset_mock()
        retry = self.service.enqueue("payment", "test", event_type="payment", event_key="order-1")
        self.assertEqual(retry["server_chan"]["status"], "queued")
        self.assertEqual(retry["wecom_webhook"]["status"], "duplicate")
        self.service._executors["server_chan"].submit(lambda: None).result(timeout=2)
        self.service._send_server_chan.assert_called_once()
        self.service._send_wecom.assert_not_called()

    def test_concurrent_repeated_event_is_admitted_once_per_channel(self):
        with ThreadPoolExecutor(max_workers=8) as callers:
            results = list(callers.map(lambda _: self.service.enqueue("event", "test", event_type="payment", event_key="same"), range(20)))
        for channel in ("server_chan", "wecom_webhook"):
            self.assertEqual(sum(result[channel]["status"] == "queued" for result in results), 1)
            self.assertEqual(sum(result[channel]["status"] == "duplicate" for result in results), 19)

    def test_completion_of_older_sends_does_not_hide_a_new_queue_rejection(self):
        self.fill_slow_channel()
        self.release.set()
        self.service._executors["server_chan"].submit(lambda: None).result(timeout=2)
        self.assertEqual(self.service.status()["server_chan"]["status"], "queue_full")

    def test_executor_rejection_does_not_claim_dedup_or_leak_capacity(self):
        executor = self.service._executors["server_chan"]
        with patch.object(executor, "submit", side_effect=RuntimeError("unavailable")):
            first = self.service.enqueue("event", "test", event_type="hit", event_key="retry")
        self.assertEqual(first["server_chan"]["status"], "failed")
        second = self.service.enqueue("event", "test", event_type="hit", event_key="retry")
        self.assertEqual(second["server_chan"]["status"], "queued")

    def test_test_notification_reports_still_queued_instead_of_inventing_failure(self):
        fast = threading.Event()
        self.service._send_wecom.side_effect = lambda *_: fast.set() or True
        from concurrent.futures import wait as real_wait
        # Exercise the real shared-deadline logic with a shorter test deadline.
        with patch("railwatch_notify.wait", side_effect=lambda futures, timeout: real_wait(futures, timeout=0.1)):
            result = self.service.test_notification()
        self.assertTrue(fast.is_set())
        self.assertEqual(result["server_chan"]["status"], "queued")
        self.assertEqual(result["wecom_webhook"]["status"], "success")


class UpdateCleanupTests(unittest.TestCase):
    def test_install_closes_idle_browser_before_returning_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(data_dir=directory)
            driver = Mock()
            bridge.driver = driver
            self.assertTrue(bridge.prepare_shutdown("install")["ready"])
            driver.quit.assert_called_once()
            driver.service.stop.assert_called_once()
            self.assertIsNone(bridge.driver)

    def test_install_does_not_claim_ready_when_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(data_dir=directory)
            driver = Mock()
            driver.quit.side_effect = RuntimeError("disconnected")
            bridge.driver = driver
            with self.assertRaisesRegex(RuntimeError, "浏览器"):
                bridge.prepare_shutdown("install")
            self.assertFalse(bridge._admission_closed)

    def test_timed_out_cleanup_retains_browser_exclusion_until_worker_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(data_dir=directory)
            driver = Mock()
            release = threading.Event()
            finished = threading.Event()
            driver.quit.side_effect = lambda: release.wait(3)
            bridge.driver = driver
            cleanup = bridge._shutdown_browser
            release_driver = bridge._release_driver
            def tracked_release(*args, **kwargs):
                try:
                    return release_driver(*args, **kwargs)
                finally:
                    finished.set()
            try:
                with patch.object(bridge, "_release_driver", side_effect=tracked_release), \
                     patch.object(bridge, "_shutdown_browser", side_effect=lambda: cleanup(timeout=0.01)):
                    with self.assertRaisesRegex(RuntimeError, "超时"):
                        bridge.prepare_shutdown("install")
                    self.assertEqual(bridge.task_activity()["state"], "busy")
                    bridge.cancel_shutdown()
                    with self.assertRaises(RuntimeError):
                        bridge.open_login()
                    self.assertFalse(bridge.prepare_shutdown("install")["ready"])
                    release.set()
                    self.assertTrue(finished.wait(2))
            finally:
                release.set()
                finished.wait(2)

    def test_service_cleanup_failure_also_blocks_install(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(data_dir=directory)
            driver = Mock()
            driver.service.stop.side_effect = RuntimeError("service still alive")
            bridge.driver = driver
            with self.assertRaisesRegex(RuntimeError, "浏览器"):
                bridge.prepare_shutdown("install")
            self.assertFalse(bridge._admission_closed)


class FavoriteTrainTests(unittest.TestCase):
    def test_numeric_favorites_survive_reload_with_order_and_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            save_train_favorites(directory, "北京", "上海", ["1461", "G101", "1461", "Y123", "12345"])
            self.assertEqual(load_trip_choices(directory)["favorites"][0]["trains"],
                             ["1461", "G101", "Y123", "12345"])

    def test_favorite_format_matches_query_parser_and_rejects_bad_tokens(self):
        from railwatch_row_parser import RowParser
        with tempfile.TemporaryDirectory() as directory:
            for code in ("1461", "12345", "G1", "D12345", "C12", "Z99", "T12", "K123", "Y12", "S1", "L1", "g101"):
                with self.subTest(code=code):
                    saved = save_train_favorites(directory, "北京", "上海", [code])
                    self.assertEqual(saved["favorites"][0]["trains"], [RowParser.extract_train_code(code)])
            before = load_trip_choices(directory)
            for code in ("", "123", "123456", "G", "G12G", "G123456", "X123", "G1 G2", "G1\n", " 1461"):
                with self.subTest(code=code), self.assertRaises(ValueError):
                    save_train_favorites(directory, "北京", "上海", [code])
            self.assertEqual(load_trip_choices(directory), before)


class ObservationTimeTests(unittest.TestCase):
    def test_same_state_and_unknown_reads_advance_check_time_without_changing_official_evidence(self):
        for observed in ("pending_payment", "unknown", "error"):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as directory:
                bridge = RailWatchBridge(data_dir=directory)
                intent = OrderIntent("regular", "G101", "2026-09-24", "北京", "上海", "二等座", ("测试",))
                result = OrderResult("pending_payment", order_id="E1", evidence={"matched": True})
                bridge.order_journal.begin("run", intent, {})
                with patch("railwatch_orders.time.time", return_value=100):
                    bridge.order_journal.record(intent, result)
                task = MonitorTask({})
                def read(*args, **kwargs):
                    task.cancel.set()
                    if observed == "error":
                        raise RuntimeError("page unavailable")
                    return result if observed == "pending_payment" else OrderResult("unknown")
                with patch("railwatch_bridge.OrderPage") as page, patch.object(bridge, "_task_wait"), \
                     patch("railwatch_bridge.time.time", return_value=200):
                    page.return_value.result.side_effect = read
                    if observed == "error":
                        with self.assertRaisesRegex(RuntimeError, "page unavailable"):
                            bridge._observe_order(task, Mock(), intent, result)
                    else:
                        bridge._observe_order(task, Mock(), intent, result)
                summary = bridge.order_detail(intent.intent_id)["summary"]
                self.assertEqual(summary["last_checked_at"], 200)
                self.assertEqual(summary["last_check_status"], observed)
                self.assertEqual(summary["official_status"], "pending_payment")
                self.assertEqual(summary["official_verified_at"], 100)
                restored = OrderJournal(bridge.order_journal.filename)
                self.assertEqual(restored.history_detail(intent.intent_id)["summary"]["last_checked_at"], 200)

    def test_checkpoints_batch_writes_and_flush_latest_without_adding_timeline_events(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            intent = OrderIntent("regular", "G101", "2026-09-24", "北京", "上海", "二等座", ("测试",))
            journal.begin("run", intent, {})
            journal.record(intent, OrderResult("pending_payment", order_id="E1", evidence={"matched": True}))
            events = journal.history_detail(intent.intent_id)["events"]
            at = time.time()
            with patch("railwatch_orders.time.monotonic", return_value=100):
                journal.note_check(intent.intent_id, "pending_payment")
            with patch("railwatch_orders.time.monotonic", return_value=101), patch("railwatch_orders.time.time", return_value=at + 10):
                for _ in range(20):
                    journal.note_check(intent.intent_id, "unknown")
            detail = journal.history_detail(intent.intent_id)
            self.assertEqual(detail["summary"]["last_checked_at"], at + 10)
            self.assertEqual(detail["events"], events)
            with journal.connection() as db:
                self.assertLess(db.execute("SELECT checked_at FROM order_checks").fetchone()[0], at + 10)
            journal.flush_checks()
            restored = OrderJournal(journal.filename)
            self.assertEqual(restored.history_detail(intent.intent_id)["summary"]["last_check_status"], "unknown")
            with restored.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM order_checks").fetchone()[0], 1)

    def test_legacy_database_migration_keeps_history_without_inventing_check_time(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = directory + "/orders.sqlite3"
            journal = OrderJournal(filename)
            intent = OrderIntent("regular", "1461", "2026-09-24", "北京", "上海", "硬座", ("测试",))
            journal.begin("run", intent, {})
            with journal.connection() as db:
                db.execute("DROP TABLE order_checks")
            restored = OrderJournal(filename)
            detail = restored.history_detail(intent.intent_id)
            self.assertIsNone(detail["summary"]["last_checked_at"])
            self.assertIsNone(detail["summary"]["last_check_status"])
            self.assertEqual(detail["events"][0]["stage"], "submitting")

    def test_failed_checkpoint_write_is_retained_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            intent = OrderIntent("regular", "G1", "2026-09-24", "北京", "上海", "二等座", ("测试",))
            journal.begin("run", intent, {})
            with patch.object(journal, "connection", side_effect=sqlite3.OperationalError("busy")):
                journal.note_check(intent.intent_id, "unknown")
            self.assertEqual(journal.history_detail(intent.intent_id)["summary"]["last_check_status"], "unknown")
            journal.flush_checks()
            self.assertEqual(OrderJournal(journal.filename).history_detail(intent.intent_id)["summary"]["last_check_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
