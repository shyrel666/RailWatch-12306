"""Only proven pre-submission failures can advance to another candidate."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gui_12306_0 import TicketMonitor
from railwatch_orders import OrderJournal, OrderResult


CONFIG = {"date": "2026-10-10", "date_range": "±1天", "from_station_cn": "北京",
          "to_station_cn": "上海", "passengers": "张三", "seat_keyword": "二等座,一等座",
          "train_code": "G101,G102", "auto_submit": True, "auto_alternate": True}


class CandidateRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal = OrderJournal(Path(directory.name) / "orders.sqlite3")
        self.humans = []
        self.monitor = TicketMonitor(Mock(), CONFIG, order_journal=self.journal,
                                     human_action_callback=self.humans.append, log_callback=lambda _: None,
                                     run_id="recovery")
        self.monitor.row_parser.selected_route = Mock(return_value=None)
        self.monitor._sleep = Mock()
        self.monitor._find_book_button = Mock(return_value=Mock())
        self.monitor._get_seat_value = Mock(return_value="有")
        self.monitor._find_alternate_button = Mock(return_value=Mock())
        self.clock = 100.0
        self.time_patch = patch("gui_12306_0.time.monotonic", lambda: self.clock)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.rows = [{"train": train, "element": Mock(), "seats": {"二等座": "有", "一等座": "无"}}
                     for train in ("G101", "G102")]
        self.monitor._row_snapshot = self.rows
        self.hit = ("G101", "二等座", "有", self.rows[0]["element"], Mock(), "book")

    def sold_out(self):
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=OrderResult("sold_out", no_order=True))
        self.assertFalse(self.monitor._execute_order(self.hit))
        self.assertIsNone(self.journal.pending())

    def test_failed_train_yields_to_other_inventory_before_waitlist(self):
        self.sold_out()
        hit = self.monitor._find_hit_row()
        self.assertEqual((hit[0], hit[-1]), ("G102", "book"))
        self.monitor._find_alternate_button.assert_not_called()
        self.monitor._sleep.assert_not_called()

    def test_cooldown_is_scoped_to_seat_date_and_action(self):
        self.sold_out()
        self.rows[0]["seats"]["一等座"] = "有"
        self.assertEqual(self.monitor._find_hit_row()[1], "一等座")
        for row in self.rows:
            row["seats"] = {"二等座": "无", "一等座": "无"}
        self.assertEqual(self.monitor._find_hit_row()[-1], "alternate")
        self.rows[0]["seats"]["二等座"] = "有"
        self.monitor.cfg["date"] = "2026-10-11"
        self.assertEqual(self.monitor._find_hit_row()[-1], "book")

    def test_failed_candidate_is_reconsidered_after_cooldown(self):
        self.sold_out()
        self.clock += 29.9
        self.assertEqual(self.monitor._find_hit_row()[0], "G102")
        self.clock += 0.1
        self.assertEqual(self.monitor._find_hit_row()[0], "G101")
        self.assertEqual(self.monitor._candidate_cooldowns, {})

    def test_without_waitlist_sold_out_continues_at_normal_cadence(self):
        self.monitor.auto_alternate = False
        self.sold_out()
        self.monitor._sleep.assert_called_once()
        self.assertGreater(self.monitor._sleep.call_args.args[0], 0)
        self.assertFalse(self.monitor._prefer_alternate)
        self.assertEqual(self.humans, [])

    def test_disappeared_waitlist_entry_advances_to_next_configured_seat(self):
        self.monitor.alternate_flow.find_alternate_button = Mock(return_value=None)
        hit = (*self.hit[:-1], "alternate")
        self.assertFalse(self.monitor._execute_order(hit))
        self.assertIsNone(self.journal.pending())
        self.monitor._sleep.assert_called_once()
        for row in self.rows:
            row["seats"] = {"二等座": "无", "一等座": "无"}
        choice = self.monitor._find_hit_row()
        self.assertEqual((choice[0], choice[1], choice[-1]), ("G101", "一等座", "alternate"))
        self.assertEqual(self.humans, [])

    def test_generic_missing_submit_button_still_needs_human(self):
        self.monitor.alternate_flow.try_alternate_order = Mock(
            return_value=OrderResult("not_submitted", "候补提交按钮不可用", no_order=True))
        self.assertTrue(self.monitor._execute_order((*self.hit[:-1], "alternate")))
        self.assertEqual(self.monitor._candidate_cooldowns, {})
        self.assertEqual(len(self.humans), 1)

    def test_submission_marker_overrides_retryable_failure(self):
        def submit(*args, intent):
            self.journal.mark("recovery", "alternate_submit", intent.intent_id)
            return OrderResult("not_submitted", no_order=True, evidence={"candidate_unavailable": True})
        self.monitor.alternate_flow.try_alternate_order = submit
        self.assertTrue(self.monitor._execute_order((*self.hit[:-1], "alternate")))
        self.assertEqual(self.journal.pending()["result"]["status"], "unknown")
        self.assertEqual(self.monitor._candidate_cooldowns, {})
        self.monitor._sleep.assert_not_called()

    def test_unproven_sold_out_retains_order_and_never_retries(self):
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=OrderResult("sold_out"))
        self.assertTrue(self.monitor._execute_order(self.hit))
        self.assertIsNotNone(self.journal.pending())
        self.assertEqual(self.monitor._candidate_cooldowns, {})
        self.assertFalse(self.monitor._needs_navigation)

    def test_stop_after_failure_never_schedules_retry(self):
        def submit(*args, **kwargs):
            self.monitor.should_stop = lambda: True
            return OrderResult("sold_out", no_order=True)
        self.monitor.submit_flow.try_auto_submit = submit
        self.assertTrue(self.monitor._execute_order(self.hit))
        self.assertEqual(self.monitor._candidate_cooldowns, {})
        self.monitor._sleep.assert_not_called()

    def test_no_waitlist_on_original_date_restores_date_rotation(self):
        self.sold_out()
        self.monitor.query_executor = Mock()
        self.monitor.query_executor.execute.return_value = {"status": "empty"}
        self.monitor._fill_query_params = Mock(return_value=True)
        self.assertFalse(self.monitor._run_single_loop(2, 3))
        self.assertEqual(self.monitor.current_loop_date, CONFIG["date"])
        self.assertFalse(self.monitor._prefer_alternate)
        self.assertEqual(self.monitor._fallback_date, "")
        self.monitor._apply_loop_date(3)
        self.assertEqual(self.monitor.current_loop_date, "2026-10-11")

    def test_pending_waitlist_order_blocks_every_new_intent(self):
        self.monitor.alternate_flow.try_alternate_order = Mock(return_value=OrderResult(
            "pending_payment", order_id="E123456", evidence={"matched": True}))
        self.assertTrue(self.monitor._execute_order((*self.hit[:-1], "alternate")))
        self.monitor.submit_flow.try_auto_submit = Mock()
        self.assertTrue(self.monitor._execute_order(self.hit))
        self.monitor.submit_flow.try_auto_submit.assert_not_called()
        self.assertIsNotNone(self.journal.pending())


if __name__ == "__main__":
    unittest.main()
