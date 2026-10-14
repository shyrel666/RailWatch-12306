"""Timing diagnostics cannot delay a retry or change a transaction result."""
import tempfile
import unittest
from unittest.mock import Mock, patch

from gui_12306_0 import TicketMonitor
from railwatch_orders import OrderJournal, OrderResult
from railwatch_policies import QUERY_STRATEGIES
from railwatch_query import QueryExecutor
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
        self.monitor.query_executor.execute.side_effect = lambda *args, **kwargs: self.delay(.4, {"status": "ok"})
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
        self.assertIs(self.details()[0]["hit"], False)

    def test_selected_candidate_timing_finishes_before_order_work(self):
        self.monitor.auto_submit = True
        self.monitor._scan_current_rows = lambda: self.delay(.02, ("G101", "二等座", "有", Mock(), Mock(), "book"))
        self.monitor.row_parser.selected_route = lambda row: None
        self.monitor.submit_flow.try_auto_submit = lambda *a, **k: self.delay(10, OrderResult("pending_payment"))
        self.journal.record.side_effect = lambda intent, result: result
        self.monitor._run_single_loop(1, 6)
        self.assertEqual(len(self.details()), 1)
        self.assertEqual(sum(s["duration_ms"] for s in self.details()[0]["steps"]), 550)
        self.assertIs(self.details()[0]["hit"], True)
        self.assertAlmostEqual(self.now, 10.55)

    def test_hit_marker_is_claimed_with_the_intent_not_written_separately(self):
        self.monitor.auto_submit = True
        self.monitor._scan_current_rows = lambda: self.delay(.02, ("G101", "二等座", "有", Mock(), Mock(), "book"))
        self.monitor.row_parser.selected_route = lambda row: None
        self.monitor.submit_flow.try_auto_submit = lambda *a, **k: OrderResult("pending_payment")
        self.journal.record.side_effect = lambda intent, result: result
        self.monitor._run_single_loop(1, 6)
        self.assertEqual(self.journal.begin.call_args.args[3], "inventory_found")
        self.assertNotIn("inventory_found", [call.args[1] for call in self.journal.mark.call_args_list])

    def test_query_click_never_commits_even_with_a_full_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3", telemetry_batch_size=1)
            self.monitor.order_journal = journal
            with patch.object(journal, "connection", wraps=journal.connection) as connection:
                for _ in range(3):
                    self.monitor._mark("query_click")
                    self.monitor._mark("query_result")
                connection.assert_not_called()
            self.monitor._sleep(1)  # The idle wait writes the due batch.
            with journal.connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM order_events").fetchone()[0], 6)

    def test_idle_flush_counts_toward_the_wait_and_short_waits_skip_it(self):
        self.journal.flush_due_telemetry.side_effect = lambda: self.delay(.03, 64)
        self.monitor._sleep(3)
        self.assertAlmostEqual(self.now, 3)
        self.journal.flush_due_telemetry.reset_mock()
        self.monitor._sleep(.1)
        self.journal.flush_due_telemetry.assert_not_called()
        self.assertAlmostEqual(self.now, 3.1)
        self.journal.flush_due_telemetry.side_effect = OSError("disk unavailable")
        self.monitor._sleep(1)
        self.assertAlmostEqual(self.now, 4.1)

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

    def test_settle_and_presale_diagnostics_are_recorded_with_the_query(self):
        page = {"transport": "xhr", "late_count": 0, "late_max_ms": 0, "gap_max_ms": 0}
        self.monitor.cfg["_target_timestamp"] = 100.0
        self.monitor.target_trains = ["G101"]
        self.monitor.server_time_sync = Mock(server_timestamp=Mock(return_value=101.25))
        self.monitor.click_query_button = lambda: True
        def execute(click, timeout, **kwargs):
            click()
            return self.delay(.4, {"status": "ok", "requests": 1, "page_timing": page})
        self.monitor.query_executor.execute.side_effect = execute
        rows = [{"train": "G101", "seats": {"二等座": "*", "一等座": "--"},
                 "presale": {"stars": 1, "sale_text": True, "label": "12点起售", "book": False}},
                {"train": "G102", "seats": {"二等座": "有"},
                 "presale": {"stars": 0, "sale_text": False, "label": None, "book": True}}]
        self.monitor.row_parser.snapshot_rows = lambda *args: self.delay(.03, rows)
        self.assertFalse(self.monitor._run_single_loop(1, 6))
        detail = self.details()[0]
        self.assertEqual(detail["page"], page)
        self.assertEqual(detail["requests"], 1)
        self.assertEqual(detail["sale_offset_ms"], 1250)
        self.assertEqual(detail["presale"], {"rows": 1, "sale_text_rows": 1, "star_rows": 1, "all_star_rows": 1,
                                             "book_rows": 0, "labels": ["12点起售"]})
        self.assertAlmostEqual(self.now, 6.55)

    def test_not_on_sale_round_records_request_count_without_rows(self):
        self.monitor.query_executor.execute.side_effect = lambda *args, **kwargs: self.delay(
            .4, {"status": "not_on_sale", "reason": "未到起售时间", "requests": 0})
        self.monitor._dismiss_query_blockers = lambda: "未到起售时间"
        self.assertFalse(self.monitor._run_single_loop(1, 6))
        detail = self.details()[0]
        self.assertEqual((detail["status"], detail["requests"], detail["page"], detail["presale"],
                          detail["sale_offset_ms"]), ("not_on_sale", 0, None, None, None))

    def test_executor_returns_page_timing_and_prompt_request_count(self):
        form = {"page": "one", "values": ["北京", "BJP", "上海", "SHH", "2026-09-10"]}
        armed = {"form": form, "dialog": {"kind": "none"}, "armed": True}
        timing = {"transport": "xhr", "late_count": 0, "late_max_ms": 0, "gap_max_ms": 0}
        driver = Mock()
        driver.execute_script.side_effect = [armed, {"form": form, "dialog": {"kind": "none"},
            "status": {"status": "ok", "revision": 1, "requests": 1, "timing": timing}}]
        result = QueryExecutor(driver).execute(lambda: True, 1)
        self.assertEqual((result["page_timing"], result["requests"]), (timing, 1))
        self.assertNotIn("timing", result)
        for requests in (0, 1):
            driver = Mock()
            driver.execute_script.side_effect = [armed, {"form": form,
                "dialog": {"kind": "not_on_sale", "text": "未到起售时间"},
                "status": {"status": "pending", "revision": 0, "requests": requests}}]
            result = QueryExecutor(driver).execute(lambda: True, 1)
            self.assertEqual((result["status"], result["requests"]), ("not_on_sale", requests))

    def test_fast_polling_starts_only_after_the_response_arrives(self):
        form = {"page": "one", "values": ["北京", "BJP", "上海", "SHH", "2026-09-10"]}
        def observed(status, finished):
            return {"form": form, "dialog": {"kind": "none"},
                    "status": {"status": status, "revision": 1, "requests": 1, "responseFinished": finished}}
        driver, wait = Mock(), Mock()
        driver.execute_script.side_effect = [{"form": form, "dialog": {"kind": "none"}, "armed": True},
                                             observed("pending", False), observed("pending", False),
                                             observed("pending", True), observed("pending", True), observed("ok", True)]
        executor = QueryExecutor(driver, wait=wait, settle={"quiet_ms": 120, "poll_ms": 100})
        result = executor.execute(lambda: True, 1, poll_interval=.025)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("responseFinished", result)
        self.assertEqual([call.args[0] for call in wait.call_args_list], [.1, .1, .025, .025])
        self.assertEqual(driver.execute_script.call_args_list[0].args[3], 120)  # Armed in the page.

    def test_sale_window_polls_faster_only_while_focused(self):
        settle = QUERY_STRATEGIES["query_settle"]
        self.monitor.cfg.update(timer_enabled=True, _target_timestamp=100.0)
        self.monitor.server_time_sync = Mock(server_timestamp=Mock(return_value=101.0))
        self.monitor._run_single_loop(1, 6)
        self.assertEqual(self.monitor.query_executor.execute.call_args.kwargs["poll_interval"], settle["sale_poll_ms"] / 1000)
        self.monitor.server_time_sync.server_timestamp.return_value = 200.0
        self.monitor._run_single_loop(2, 6)
        self.assertEqual(self.monitor.query_executor.execute.call_args.kwargs["poll_interval"], settle["poll_ms"] / 1000)

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
