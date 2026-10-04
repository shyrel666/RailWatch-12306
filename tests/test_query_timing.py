"""Timing diagnostics cannot delay a retry or change a transaction result."""
import tempfile
import unittest
from unittest.mock import Mock, patch

from gui_12306_0 import TicketMonitor
from railwatch_orders import OrderJournal, OrderResult
from railwatch_run_review import query_timing_summary


class QueryTimingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        timer = patch("time.monotonic", lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.journal = Mock()
        self.monitor = TicketMonitor(Mock(), {"date": "2026-10-10", "date_range": "单日",
            "from_station_cn": "北京", "to_station_cn": "上海"}, log_callback=lambda _: None,
            order_journal=self.journal, run_id="timing", wait_callback=self.advance)
        self.monitor._fill_query_params = lambda **kwargs: self.delay(.1, True)
        self.monitor.query_executor = Mock()
        self.monitor.query_executor.current.return_value = True
        self.monitor.query_executor.execute.side_effect = lambda *args: self.delay(.4, {"status": "ok"})
        self.monitor.row_parser.snapshot_rows = lambda *args: self.delay(.03, [])
        self.monitor._scan_current_rows = lambda: self.delay(.02, None)

    def advance(self, seconds):
        self.now += seconds

    def delay(self, seconds, result):
        self.advance(seconds)
        return result

    def details(self):
        return [call.kwargs["detail"] for call in self.journal.record_telemetry.call_args_list
                if call.args[1] == "query_timing"]

    def test_phase_samples_exclude_normal_backoff_and_are_written_once(self):
        self.monitor._run_single_loop(1, 6)
        self.assertEqual(len(self.details()), 1)
        steps = {s["id"]: s["duration_ms"] for s in self.details()[0]["steps"]}
        self.assertEqual(steps, {"prepare": 100, "query": 400, "snapshot": 30, "decision": 20, "publish": 0})
        self.assertAlmostEqual(self.now, 6.55)
        self.assertEqual(self.details()[0]["status"], "ok")

    def test_selected_candidate_timing_finishes_before_order_work(self):
        self.monitor.auto_submit = True
        self.monitor._scan_current_rows = lambda: self.delay(.02, ("G101", "二等座", "有", Mock(), Mock(), "book"))
        self.monitor.row_parser.selected_route = lambda row: None
        self.monitor.submit_flow.try_auto_submit = lambda *a, **k: self.delay(10, OrderResult("pending_payment"))
        self.journal.record.side_effect = lambda intent, result: result
        self.monitor._run_single_loop(1, 6)
        self.assertEqual(len(self.details()), 1)
        self.assertEqual(sum(s["duration_ms"] for s in self.details()[0]["steps"]), 550)
        self.assertAlmostEqual(self.now, 10.55)

    def test_diagnostic_write_failure_does_not_change_query_behavior(self):
        def fail_phase_summary(run, stage, *args, **kwargs):
            if stage == "query_timing":
                raise OSError("diagnostics unavailable")
        self.journal.record_telemetry.side_effect = fail_phase_summary
        self.assertFalse(self.monitor._run_single_loop(1, 6))
        self.assertAlmostEqual(self.now, 6.55)

    def test_invalidated_page_is_not_a_valid_query_timing_sample(self):
        self.monitor.query_executor.current.return_value = False
        self.assertFalse(self.monitor._run_single_loop(1, 6))
        self.assertEqual(self.details()[0]["status"], "invalid")

    def test_revisit_uses_click_acknowledgements_for_the_same_date(self):
        self.monitor.click_query_button = lambda: self.delay(.2, True)
        self.monitor._timed_query_click()
        self.assertIsNone(self.monitor._date_revisit_ms)
        self.monitor.cfg["date"] = "2026-10-11"
        self.advance(2)
        self.monitor._timed_query_click()
        self.assertIsNone(self.monitor._date_revisit_ms)
        self.monitor.cfg["date"] = "2026-10-10"
        self.advance(2)
        self.monitor._timed_query_click()
        self.assertEqual(self.monitor._date_revisit_ms, 4400)

    def test_query_diagnostics_are_buffered_bounded_and_available_in_review(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3", telemetry_batch_size=1, telemetry_limit=20)
            with patch.object(journal, "flush_telemetry", wraps=journal.flush_telemetry) as flush:
                journal.record_telemetry("run", "query_timing", detail={"status": "ok"})
                flush.assert_not_called()
            for _ in range(50):
                journal.record_telemetry("run", "query_timing", detail={"status": "ok"})
            journal.flush_telemetry()
            self.assertEqual(len(journal.run_events("run")), 20)

    def test_summary_excludes_failed_phases_and_handles_missing_history(self):
        events = [{"stage": "query_timing", "detail": {"status": status, "date": "2026-10-10",
            "revisit_ms": revisit, "steps": [{"id": "decision", "duration_ms": value}]}}
            for status, revisit, value in (("ok", None, 10), ("ok", 2000, 30), ("timeout", 5000, 999))]
        summary = query_timing_summary(events)
        self.assertEqual(summary["valid_queries"], 2)
        self.assertEqual(summary["phases"][0]["median_ms"], 20)
        self.assertEqual(summary["phases"][0]["p95_ms"], 30)
        self.assertEqual(summary["date_revisits"][0]["median_ms"], 3500)
        self.assertEqual(query_timing_summary([])["phases"], [])
