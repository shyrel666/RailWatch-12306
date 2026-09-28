import json
import tempfile
import unittest
from pathlib import Path

from railwatch_orders import OrderIntent, OrderJournal, OrderResult


class OrderHistoryTests(unittest.TestCase):
    def test_paging_detail_and_restart_keep_official_evidence_separate(self):
        with tempfile.TemporaryDirectory() as data_dir:
            filename = str(Path(data_dir) / "orders.sqlite3")
            journal = OrderJournal(filename)
            first = OrderIntent("regular", "G101", "2026-09-24", "北京", "上海", "二等座", ("张三",))
            journal.begin("run-1", first, {})
            journal.mark("run-1", "regular_submit", first.intent_id)
            journal.record(first, OrderResult("pending_payment", order_id="E123", evidence={"matched": True}))
            journal.record(first, OrderResult("unknown", "页面暂不可读"))
            second = OrderIntent("alternate", "D21", "2026-09-25", "上海", "南京", "二等座", ("李四",))
            # A resolved first order allows another intent to start.
            journal.dismiss(first.intent_id)
            journal.begin("run-2", second, {})
            journal.record(second, OrderResult("active", order_id="H123", evidence={"matched": True}))
            restored = OrderJournal(filename)
            page = restored.history_page(limit=1)
            self.assertEqual(len(page["items"]), 1)
            self.assertIsNotNone(page["next_cursor"])
            older = restored.history_page(limit=1, cursor=page["next_cursor"])
            self.assertEqual(len(older["items"]), 1)
            self.assertNotEqual(page["items"][0]["intent_id"], older["items"][0]["intent_id"])
            detail = restored.history_detail(first.intent_id)
            self.assertEqual(detail["summary"]["status"], "dismissed")
            self.assertEqual(detail["summary"]["official_status"], "pending_payment")
            self.assertIsNotNone(detail["summary"]["official_verified_at"])
            self.assertTrue(detail["history_complete"])
            self.assertIn("official", [event["scope"] for event in detail["events"]])
            self.assertEqual(detail["events"][-1]["message"], "用户结束本地核对；官方订单未取消")
            self.assertNotIn("张三", json.dumps(detail, ensure_ascii=False))

    def test_legacy_final_result_has_incomplete_timeline_and_unknown_verified_time(self):
        with tempfile.TemporaryDirectory() as data_dir:
            journal = OrderJournal(str(Path(data_dir) / "orders.sqlite3"))
            intent = OrderIntent("regular", "G1", "2026-09-24", "北京", "上海", "二等座", ("张三",))
            with journal.connection() as db:
                db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (intent.intent_id, "run-old",
                           json.dumps(intent.__dict__, ensure_ascii=False), "{}",
                           json.dumps(OrderResult("fulfilled", order_id="E1", evidence={"matched": True}).payload()), 0, 100.0))
            detail = journal.history_detail(intent.intent_id)
            self.assertEqual(detail["events"], [])
            self.assertFalse(detail["history_complete"])
            self.assertEqual(detail["summary"]["official_status"], "fulfilled")
            self.assertIsNone(detail["summary"]["official_verified_at"])
            self.assertIsNone(detail["summary"]["last_checked_at"])

    def test_rejects_bad_page_parameters_and_identifiers(self):
        with tempfile.TemporaryDirectory() as data_dir:
            journal = OrderJournal(str(Path(data_dir) / "orders.sqlite3"))
            for kwargs in ({"limit": 0}, {"limit": 51}, {"cursor": "not-base64"}, {"status": "bad"}):
                with self.assertRaises(ValueError):
                    journal.history_page(**kwargs)
            with self.assertRaises(ValueError):
                journal.history_detail("x' OR 1=1")


if __name__ == "__main__":
    unittest.main()
