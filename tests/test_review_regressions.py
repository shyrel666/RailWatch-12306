"""Review regressions: isolated storage and controlled concurrency, no network."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_run_review import build_run_review
from railwatch_runtime import RailWatchRuntime
from railwatch_system import inspect_data_dir


class ReviewOrderTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal = OrderJournal(Path(directory.name) / "orders.sqlite3")
        self.intent = OrderIntent("regular", "G101", "2026-10-02", "北京南", "上海虹桥", "二等座", ("测试甲",))
        self.journal.begin("new-run", self.intent, {})
        self.journal.mark("new-run", "regular_submit", self.intent.intent_id)
        self.page = OrderPage(None)
        self.card = {"order_id": "OLD_ORDER", "kind": "regular",
                     "text": "G101 2026-10-02 北京南 上海虹桥 二等座",
                     "passengers": ["测试甲"], "state": "已取消"}
        self.page.snapshot = lambda: {"url": "https://kyfw.12306.cn/otn/view/train_order.html",
                                      "orders": [self.card]}

    def test_historical_terminal_order_never_releases_a_new_submission(self):
        for label in ("已取消", "支付超时", "已支付", "兑现失败"):
            with self.subTest(label=label):
                self.card["state"] = label
                result = self.page.result(self.intent, submitted=True)
                self.assertEqual((result.status, result.order_id), ("unknown", ""))
                self.journal.record(self.intent, result)
                restarted = OrderJournal(self.journal.filename)
                self.assertEqual(restarted.pending()["result"]["order_id"], "")
                with self.assertRaises(RuntimeError):
                    restarted.begin("another-run", replace(self.intent, intent_id="new"), {})

    def test_journal_rejects_unbound_terminal_evidence_and_identity_switches(self):
        for status in ("cancelled", "expired", "fulfilled", "failed"):
            result = self.journal.record(self.intent, OrderResult(status, order_id="OLD_ORDER", evidence={"matched": True}))
            self.assertEqual((result.status, result.order_id), ("unknown", ""))
        self.journal.record(self.intent, OrderResult("pending_payment", order_id="CURRENT", evidence={"matched": True}))
        switched = self.journal.record(self.intent, OrderResult("cancelled", order_id="OLD_ORDER", evidence={"matched": True}))
        self.assertEqual((switched.status, switched.order_id), ("unknown", "CURRENT"))
        self.card.update(order_id="CURRENT", state="已取消")
        self.journal.record(self.intent, self.page.result(self.intent, known_id="CURRENT"))
        self.assertIsNone(self.journal.pending())

    def test_conflicting_history_cannot_smuggle_an_identity_into_recovery(self):
        self.card["state_conflict"] = True
        result = self.page.result(self.intent, submitted=True)
        self.assertEqual((result.status, result.order_id), ("unknown", ""))
        # Guard the journal too, including adapters returning an uncertain ID.
        stored = self.journal.record(self.intent, OrderResult("unknown", order_id="OLD_ORDER", evidence={"matched": True}))
        self.assertEqual((stored.order_id, stored.evidence), ("", {}))


class ReviewRuntimeTests(unittest.TestCase):
    def test_cancellation_and_shutdown_bypass_saturated_lookup_workers(self):
        entered = threading.Barrier(5)
        release = threading.Event()
        cancelled = threading.Event()
        bridge = Mock()

        def slow_search(*_):
            entered.wait(5)
            release.wait(5)
            return {"items": []}

        bridge.search_stations.side_effect = slow_search
        bridge.stop_monitor.side_effect = lambda: cancelled.set() or {"monitoring": False}
        bridge.cancel_rehearsal.return_value = {"cancelled": True}
        bridge.system_resumed.return_value = {}
        bridge.prepare_shutdown.return_value = {"ready": True}
        runtime = RailWatchRuntime(bridge=bridge, writer=lambda _: None)

        def send(command, index=0):
            return runtime.handle_line(json.dumps({"id": f"{command}-{index}", "command": command,
                                                   "payload": {"query": "北", "purpose": "quit"}}))

        try:
            searches = [send("searchStations", i) for i in range(4)]
            entered.wait(5)
            for command in ("stopMonitor", "cancelRehearsal", "systemResumed", "prepareShutdown"):
                send(command).result(timeout=2)
            self.assertTrue(cancelled.is_set())
            self.assertTrue(all(not future.done() for future in searches))
            bridge.cancel_rehearsal.assert_called_once()
            bridge.system_resumed.assert_called_once()
            bridge.prepare_shutdown.assert_called_once_with("quit")
        finally:
            release.set()
            runtime.shutdown()


class ReviewEventOrderingTests(unittest.TestCase):
    def test_review_flush_cannot_be_overtaken_by_later_events(self):
        for writer in ("telemetry", "mark", "result"):
            with self.subTest(writer=writer), tempfile.TemporaryDirectory() as directory:
                journal = OrderJournal(Path(directory) / "orders.sqlite3")
                intent = OrderIntent("regular", "G101", "2026-10-02", "北京", "上海", "二等座", ("测试",))
                journal.begin("run", intent, {})
                journal.mark("run", "target_sale", detail={"target_at": None})
                journal.record_telemetry("run", "query_click")
                if writer != "telemetry":
                    journal.record_telemetry("run", "query_result")
                connection = journal.connection
                detached, release, attempted = threading.Event(), threading.Event(), threading.Event()

                @contextmanager
                def delayed_connection():
                    if threading.current_thread().name.startswith("review-flush"):
                        detached.set()
                        if not release.wait(5):
                            raise RuntimeError("test writer was not released")
                    with connection() as db:
                        yield db

                def later_event():
                    attempted.set()
                    if writer == "telemetry":
                        journal.record_telemetry("run", "query_result")
                        journal.mark("run", "inventory_found")
                    elif writer == "mark":
                        journal.mark("run", "inventory_found")
                    else:
                        journal.record(intent, OrderResult("unknown"))

                with patch.object(journal, "connection", delayed_connection), \
                        ThreadPoolExecutor(1, thread_name_prefix="review-flush") as reader, \
                        ThreadPoolExecutor(1, thread_name_prefix="monitor") as monitor:
                    first = reader.submit(journal.flush_telemetry)
                    try:
                        self.assertTrue(detached.wait(2))
                        second = monitor.submit(later_event)
                        self.assertTrue(attempted.wait(2))
                        # No later event may commit while the earlier batch is held.
                        threading.Event().wait(.05)
                        self.assertFalse(second.done())
                    finally:
                        release.set()
                    first.result(timeout=2)
                    second.result(timeout=2)
                with connection() as db:
                    stages = [row[0] for row in db.execute("SELECT stage FROM order_events ORDER BY sequence")]
                self.assertLess(stages.index("query_click"), stages.index("query_result"))
                self.assertLess(stages.index("query_result"), stages.index("order_result" if writer == "result" else "inventory_found"))
                review = build_run_review(journal.run_events("run"))
                self.assertIsNotNone(next(s["duration_ms"] for s in review["segments"] if s["id"] == "query"))

    def test_failed_flush_retains_batch_without_duplication_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / "orders.sqlite3")
            journal.record_telemetry("run", "query_click")
            with patch.object(journal, "connection", side_effect=sqlite3.OperationalError("busy")):
                with self.assertRaises(sqlite3.OperationalError):
                    journal.flush_telemetry()
            journal.record_telemetry("run", "query_result")
            self.assertEqual(journal.flush_telemetry(), 2)
            self.assertEqual(journal.flush_telemetry(), 0)


class ReviewDirectoryTests(unittest.TestCase):
    def test_concurrent_probes_use_distinct_files_and_remove_only_their_own(self):
        with tempfile.TemporaryDirectory() as directory:
            create = tempfile.NamedTemporaryFile
            barrier = threading.Barrier(2)
            paths = []

            @contextmanager
            def synchronized_probe(*args, **kwargs):
                with create(*args, **kwargs) as handle:
                    paths.append(handle.name)
                    barrier.wait(5)
                    yield handle

            with patch("railwatch_system.tempfile.NamedTemporaryFile", synchronized_probe), ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(inspect_data_dir, directory) for _ in range(2)]
                results = [future.result(timeout=6) for future in futures]
            self.assertEqual(len(set(paths)), 2)
            self.assertTrue(all(result["data_dir_writable"] for result in results))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
