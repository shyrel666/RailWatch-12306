"""The settle report only reads local telemetry and applies the plan's quiet-window rule."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from railwatch_orders import OrderJournal
from scripts.query_settle_report import build_report, format_report, load_details, main, quiet_decision, settle_stats


def query(status="ok", late=0, late_max=0, gap=0, **extra):
    page = {"transport": "xhr", "sent_ms": 1, "response_ms": 101, "loadend_ms": 111, "last_change_ms": 105,
            "completed_ms": 420, "late_count": late, "late_max_ms": late_max, "gap_max_ms": gap}
    return {"status": status, "page": page, "steps": [{"id": "query", "duration_ms": 700}], **extra}


class QuietDecisionTests(unittest.TestCase):
    def test_rare_late_changes_allow_a_window_from_p99_plus_margin(self):
        details = [query(gap=40) for _ in range(199)] + [query(late=1, late_max=90, gap=90)]
        stats = settle_stats(details)
        self.assertEqual(stats["late_zero_share"], .995)
        self.assertEqual(quiet_decision(stats), {"eligible": True, "enough_samples": True, "quiet_ms": 70})

    def test_frequent_late_changes_keep_current_window_unless_they_are_short(self):
        slow = [query() for _ in range(90)] + [query(late=1, late_max=200, gap=200) for _ in range(10)]
        self.assertEqual(quiet_decision(settle_stats(slow)),
                         {"eligible": False, "enough_samples": False, "quiet_ms": 300})
        short = [query() for _ in range(90)] + [query(late=2, late_max=100, gap=60) for _ in range(10)]
        self.assertEqual(quiet_decision(settle_stats(short))["quiet_ms"], 130)

    def test_window_is_clamped_and_missing_data_keeps_current_window(self):
        self.assertEqual(quiet_decision(settle_stats([query()]))["quiet_ms"], 50)
        self.assertEqual(quiet_decision(settle_stats([query(gap=400)]))["quiet_ms"], 300)
        self.assertEqual(quiet_decision(settle_stats([])), {"eligible": False, "enough_samples": False, "quiet_ms": 300})

    def test_failed_and_malformed_samples_are_excluded(self):
        bad_pages = [None, {}, {**query()["page"], "late_count": True}, {**query()["page"], "gap_max_ms": float("nan")},
                     {**query()["page"], "late_max_ms": -1}]
        details = [{**query(), "page": page} for page in bad_pages] + [query("timeout"), query("invalid"), query()]
        stats = settle_stats(details)
        self.assertEqual(stats["samples"], 1)
        self.assertEqual(stats["network"]["p50_ms"], 100)
        self.assertEqual(stats["render"]["p50_ms"], 4)
        self.assertEqual(stats["detect"]["p50_ms"], 315)
        # The query step baseline keeps valid queries recorded without page timing.
        self.assertEqual(stats["query_step"]["samples"], 6)


class ReportTests(unittest.TestCase):
    def test_report_separates_stale_completions_prompts_and_sale_window(self):
        details = [query(sale_offset_ms=-500.0, presale={"rows": 1, "sale_text_rows": 1, "all_star_rows": 1,
                                                         "labels": ["12点起售"]}),
                   query("invalid", sale_offset_ms=1000.0),
                   {"status": "invalid", "steps": []},
                   {"status": "not_on_sale", "requests": 0, "sale_offset_ms": 0.0},
                   {"status": "not_on_sale", "requests": 1},
                   {"status": "not_on_sale"},
                   query(sale_offset_ms=60_000.0)]
        report = build_report(details)
        self.assertEqual(report["stale_after_completion"], {"completed": 3, "stale": 1, "rate": .3333})
        self.assertEqual(report["not_on_sale"], {"total": 3, "request_sent": 1, "no_request": 1, "unknown": 1})
        self.assertEqual(report["presale_rows"], {"queries": 1, "with_sale_text": 1, "all_rows_star": 1,
                                                  "labels": ["12点起售"]})
        self.assertEqual(report["sale_window"]["queries"], 2)
        self.assertEqual(report["sale_window"]["settle"]["samples"], 0)
        self.assertEqual([item["offset_ms"] for item in report["sale_sequence"]], [-500.0, 0.0, 1000.0])
        self.assertEqual(report["statuses"], {"invalid": 2, "not_on_sale": 3, "ok": 2})


    def test_report_counts_resettles_and_keeps_retry_evidence_in_the_sequence(self):
        details = [query(resettle=[{"at": "query", "ok": True}, {"at": "scan", "ok": False}]),
                   query("invalid", resettle=[{"at": "query", "ok": False}]),
                   query(resettle="malformed"),
                   {"status": "not_on_sale", "requests": 1, "sale_offset_ms": 20.0,
                    "sale_retry": {"evidence": "prompt", "retry": 1}}]
        report = build_report(details)
        self.assertEqual(report["resettle"], {"attempts": 3, "accepted": 1})
        self.assertEqual(report["sale_sequence"][0]["sale_retry"], {"evidence": "prompt", "retry": 1})
        text = format_report(report)
        self.assertIn("重新等稳定：1/3 次成功", text)
        self.assertIn("未开售证据=prompt 快速重查=1", text)


class LoadTests(unittest.TestCase):
    def test_reads_query_timing_by_run_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orders.sqlite3"
            journal = OrderJournal(path)
            journal.record_telemetry("run-a", "query_timing", detail=query())
            journal.record_telemetry("run-b", "query_timing", detail=query("empty"))
            journal.record_telemetry("run-a", "query_click")
            journal.flush_telemetry()
            before = path.stat().st_mtime_ns
            self.assertEqual(len(load_details(path)), 2)
            self.assertEqual([d["status"] for d in load_details(path, "run-b")], ["empty"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--db", str(path), "--run", "run-a", "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["recorded"], 1)
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--db", str(path)])
            self.assertEqual(path.stat().st_mtime_ns, before)
            missing = Path(directory) / "missing.sqlite3"
            with self.assertRaises(FileNotFoundError):
                load_details(missing)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
