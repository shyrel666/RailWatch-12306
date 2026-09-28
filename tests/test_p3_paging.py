"""Query-plan and result regressions for order-history pagination."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from railwatch_orders import OrderIntent, OrderJournal, OrderResult


def seed_history(journal, count):
    """Bulk-load synthetic resolved history, including timestamp ties."""
    intent = json.dumps(dict(kind="regular", train_code="1461", date="2026-09-24",
                             from_station="北京", to_station="上海", seat="硬座"))
    with journal.connection() as db:
        db.executemany("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (
            (f"order-{i:08d}", "run", intent, "{}",
             json.dumps({"status": "fulfilled" if i % 10 == 0 else "dismissed",
                         "order_id": f"E{i}", "evidence": {"matched": True}}), 0, i // 7)
            for i in range(count)))
        db.executemany("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)", (
            ("run", f"order-{i:08d}", "order_result", i // 7, i,
             '{"status":"fulfilled","official":true}') for i in range(count)))


@contextmanager
def measured_reads(journal):
    original = journal.connection
    stats = {"selects": [], "plans": [], "steps": 0}

    @contextmanager
    def connection():
        with original() as db:
            def trace(sql):
                if sql.lstrip().upper().startswith("SELECT"):
                    stats["selects"].append(sql)
            def progress():
                stats["steps"] += 100
                return 0
            db.set_trace_callback(trace)
            db.set_progress_handler(progress, 100)
            try:
                yield db
            finally:
                db.set_trace_callback(None)
                db.set_progress_handler(None, 0)
                for sql in stats["selects"]:
                    stats["plans"].extend(row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql))

    with patch.object(journal, "connection", connection):
        yield stats


class PagingPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.journal = OrderJournal(Path(cls.directory.name) / "history.sqlite3")
        seed_history(cls.journal, 20_000)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_page_uses_constant_number_of_selects(self):
        for limit in (1, 20, 50):
            with self.subTest(limit=limit), measured_reads(self.journal) as stats:
                page = self.journal.history_page(limit=limit)
            self.assertEqual(len(page["items"]), limit)
            self.assertLessEqual(len(stats["selects"]), 2)

    def test_first_and_deep_pages_use_indexes_without_temporary_sort(self):
        for status in (None, "fulfilled"):
            for cursor in (None, self.journal._cursor_encode(100, "order-00000700")):
                with self.subTest(status=status, cursor=cursor), measured_reads(self.journal) as stats:
                    self.journal.history_page(status=status, cursor=cursor)
                self.assertFalse(any("TEMP B-TREE" in plan for plan in stats["plans"]), stats["plans"])
                self.assertTrue(any("USING INDEX" in plan for plan in stats["plans"]), stats["plans"])
                # A deep cursor must seek into the index, not scan all newer rows.
                self.assertLess(stats["steps"], 10_000, stats)

    def test_latest_official_lookup_does_not_scan_later_local_events(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / "history.sqlite3")
            seed_history(journal, 1)
            with journal.connection() as db:
                db.executemany("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)", (
                    ("run", "order-00000000", "order_result", i + 1, i + 1,
                     '{"status":"unknown","official":false}') for i in range(10_000)))
            with measured_reads(journal) as stats:
                summary = journal.history_page()["items"][0]
            self.assertEqual(summary["official_status"], "fulfilled")
            self.assertEqual(summary["official_verified_at"], 0)
            self.assertEqual(summary["last_check_status"], "unknown")
            self.assertEqual(summary["last_checked_at"], 10_000)
            self.assertLess(stats["steps"], 2000)


class PagingCorrectnessTests(unittest.TestCase):
    def test_status_indexes_follow_order_updates_and_dismissal(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / "history.sqlite3")
            intent = OrderIntent("regular", "1461", "2026-09-24", "北京", "上海", "硬座", ("测试",))
            journal.begin("run", intent, {})
            self.assertEqual(len(journal.history_page(status="submitting")["items"]), 1)
            journal.record(intent, OrderResult("pending_payment", order_id="E1", evidence={"matched": True}))
            self.assertEqual(journal.history_page(status="submitting")["items"], [])
            self.assertEqual(len(journal.history_page(status="pending_payment")["items"]), 1)
            journal.record(intent, OrderResult("unknown"))
            journal.dismiss(intent.intent_id)
            restored = OrderJournal(journal.filename)
            self.assertEqual(restored.history_page(status="pending_payment")["items"], [])
            self.assertEqual(restored.history_page(status="unknown")["items"], [])
            item = restored.history_page(status="dismissed")["items"][0]
            self.assertEqual(item["official_status"], "pending_payment")
            self.assertFalse(item["recovery_required"])

    def test_tied_timestamps_all_pages_and_status_filters_have_no_gaps_or_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / "history.sqlite3")
            seed_history(journal, 257)
            for status in (None, "fulfilled", "dismissed", "expired"):
                with self.subTest(status=status):
                    ids, cursor = [], None
                    while True:
                        page = journal.history_page(limit=13, cursor=cursor, status=status)
                        ids.extend(item["intent_id"] for item in page["items"])
                        cursor = page["next_cursor"]
                        if cursor is None:
                            break
                    expected = [f"order-{i:08d}" for i in reversed(range(257)) if status is None or
                                status == ("fulfilled" if i % 10 == 0 else "dismissed")]
                    self.assertEqual(ids, expected)

    def test_latest_sequence_and_pending_check_keep_the_same_summary_in_list_and_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / "history.sqlite3")
            seed_history(journal, 1)
            with journal.connection() as db:
                db.executemany("INSERT INTO order_events(run_id,intent_id,stage,at,monotonic,detail) VALUES(?,?,?,?,?,?)", [
                    ("run", "order-00000000", "order_result", 500, 1, '{"status":"pending_payment","official":true}'),
                    ("run", "order-00000000", "order_result", 200, 2, '{"status":"fulfilled","official":true}'),
                    ("run", "order-00000000", "order_result", 300, 3, '{"status":"unknown","official":false}'),
                ])
                db.execute("INSERT INTO order_checks VALUES(?,?,?)", ("order-00000000", 400, "error"))
            with patch("railwatch_orders.time.time", return_value=600), patch("railwatch_orders.time.monotonic", return_value=1):
                journal.note_check("order-00000000", "unknown")
            summary = journal.history_page()["items"][0]
            self.assertEqual(summary, journal.history_detail("order-00000000")["summary"])
            self.assertEqual((summary["official_status"], summary["official_verified_at"]), ("fulfilled", 200))
            self.assertEqual((summary["last_check_status"], summary["last_checked_at"]), ("unknown", 600))

    def test_old_database_gains_indexes_without_changing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            journal = OrderJournal(path)
            seed_history(journal, 30)
            expected = journal.history_page()
            with journal.connection() as db:
                for name in ("orders_history_sort", "orders_history_status_sort", "order_events_official_latest"):
                    db.execute(f"DROP INDEX IF EXISTS {name}")
            restored = OrderJournal(path)
            with measured_reads(restored) as stats:
                self.assertEqual(restored.history_page(), expected)
            self.assertFalse(any("TEMP B-TREE" in plan for plan in stats["plans"]), stats["plans"])


if __name__ == "__main__":
    unittest.main()
