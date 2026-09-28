"""Structured display data must not change transaction matching or invent facts."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gui_12306_0 import TicketMonitor
from railwatch_bridge import RailWatchBridge
from railwatch_query import query_snapshot
from railwatch_row_parser import RowParser


CONFIG = {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-09-22",
          "date_range": "单日", "train_code": "G101", "seat_keyword": "二等座,一等座", "query_timeout": 5}


class QuerySnapshotTests(unittest.TestCase):
    def test_seat_states_come_only_from_single_inventory_cells(self):
        cases = [("3", "available", 3), ("有", "available", None), ("0", "unavailable", 0),
                 ("无", "unavailable", 0), ("候补", "alternate", None), ("不适用", "not_applicable", None),
                 (None, "unknown", None), ("--", "unknown", None), ("*", "unknown", None),
                 ("张家界", "unknown", None), ("无座", "unknown", None), ("3张", "unknown", None)]
        for raw, status, count in cases:
            with self.subTest(raw=raw):
                value = RowParser.seat_availability(raw)
                self.assertEqual(value["status"], status)
                self.assertEqual(value["count"], count)

    def test_one_snapshot_serializes_mixed_seats_without_web_elements(self):
        raw = [{"train": "G101", "raw": "张家界 无座", "element": object(), "seat_indices": {"二等座": 3},
                "from_station": "张家界西", "to_station": "上海虹桥", "departure_time": "23:00", "arrival_time": "07:00",
                "seats": {"二等座": "3", "一等座": "无", "无座": "候补"}}]
        rows = RowParser.structured_rows(raw, CONFIG["date"])
        self.assertEqual(rows[0]["from_station"], "张家界西")
        self.assertIsNone(rows[0]["arrival_day_offset"])
        self.assertEqual(rows[0]["seats"]["二等座"]["count"], 3)
        self.assertEqual(rows[0]["seats"]["一等座"]["status"], "unavailable")
        self.assertEqual(rows[0]["seats"]["无座"]["status"], "alternate")
        self.assertNotIn("element", rows[0])
        self.assertNotIn("seat_indices", rows[0])
        json.dumps(query_snapshot(CONFIG, rows, query_id="query", sequence=1))

    def test_business_conditions_and_failure_timestamps_are_explicit(self):
        config = {**CONFIG, "train_code": "g101、G103; G101", "seat_keyword": "一等座，二等座"}
        with patch("railwatch_query.time.time", return_value=100):
            good = query_snapshot(config, [], run_id="run", query_id="q1", sequence=1, fetched_at=90)
            failure = query_snapshot(config, [{"train": "OLD"}], run_id="run", query_id="q2", sequence=2,
                                     fetched_at=90, error="请求超时")
        self.assertEqual(good["conditions"]["train_codes"], ["G101", "G103"])
        self.assertEqual(good["conditions"]["seat_types"], ["一等座", "二等座"])
        self.assertEqual(good["fetched_at"], 90)
        self.assertEqual(good["completed_at"], 100)
        self.assertEqual(good["status"], "success")
        self.assertIsNone(failure["fetched_at"])
        self.assertEqual(failure["rows"], [])
        self.assertEqual(failure["status"], "error")

    def test_legacy_rows_do_not_invent_station_or_seat_data_from_text(self):
        result = query_snapshot(CONFIG, [{"train": "G101", "raw": "张家界 二等座 有"}])
        row = result["rows"][0]
        self.assertEqual(row["seats"], {})
        self.assertIsNone(row["from_station"])
        self.assertIsNone(row["arrival_time"])


class MonitorSnapshotTests(unittest.TestCase):
    def monitor(self, result):
        events, started = [], []
        monitor = TicketMonitor(Mock(), CONFIG, log_callback=lambda _: None, run_id="run-one",
                                progress_callback=events.append, query_start_callback=started.append)
        monitor.query_executor = Mock()
        monitor.query_executor.execute.return_value = result
        monitor._sleep = Mock()
        monitor._fill_query_params = Mock(return_value=True)
        monitor._find_hit_row = Mock(return_value=None)
        monitor.row_parser.snapshot_rows = Mock(return_value=[{"train": "G101", "raw": "有", "seats": {"二等座": "3"}}])
        return monitor, events, started

    def test_invalidation_during_read_emits_error_instead_of_available_rows(self):
        monitor, events, started = self.monitor({"status": "ok", "fetched_at": 90})
        checks = iter([True, False])
        monitor.query_executor.current.side_effect = lambda **kwargs: next(checks, False)
        self.assertFalse(monitor._run_single_loop(1, 3))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["snapshot"]["status"], "error")
        self.assertIsNone(events[0]["snapshot"]["fetched_at"])
        self.assertEqual(events[0]["rows"], [])
        self.assertEqual(started[0]["query_id"], events[0]["snapshot"]["query_id"])
        monitor._find_hit_row.assert_not_called()

    def test_success_reuses_dom_snapshot_and_retains_matching_path(self):
        monitor, events, started = self.monitor({"status": "ok", "fetched_at": 90})
        monitor.query_executor.current.return_value = True
        monitor._run_single_loop(2, 3)
        monitor.row_parser.snapshot_rows.assert_called_once()
        monitor._find_hit_row.assert_called_once()
        self.assertEqual(events[0]["snapshot"]["sequence"], 2)
        self.assertEqual(events[0]["snapshot"]["run_id"], "run-one")
        self.assertEqual(events[0]["rows"][0]["date"], CONFIG["date"])
        self.assertEqual(events[0]["rows"][0]["seats"]["二等座"]["count"], 3)
        self.assertEqual(started[0]["conditions"]["date"], CONFIG["date"])

    def test_failure_is_published_before_server_backoff(self):
        monitor, events, _ = self.monitor({"status": "rate_limited", "retry_after_seconds": 120, "reason": "HTTP 429"})
        monitor._sleep.side_effect = lambda seconds: self.assertEqual(events[0]["snapshot"]["status"], "error")
        monitor._run_single_loop(1, 3)
        monitor._sleep.assert_called_once_with(120)
        monitor.row_parser.snapshot_rows.assert_not_called()

    def test_empty_success_can_replace_previous_rows(self):
        monitor, events, _ = self.monitor({"status": "empty", "fetched_at": 95})
        monitor._run_single_loop(1, 3)
        monitor.row_parser.snapshot_rows.assert_not_called()
        self.assertEqual(events[0]["snapshot"]["status"], "success")
        self.assertEqual(events[0]["snapshot"]["rows"], [])
        self.assertEqual(events[0]["snapshot"]["fetched_at"], 95)

    def test_parser_exception_publishes_no_stale_rows(self):
        monitor, events, _ = self.monitor({"status": "ok", "fetched_at": 90})
        monitor.row_parser.snapshot_rows.side_effect = RuntimeError("browser disconnected")
        with self.assertRaises(RuntimeError):
            monitor._run_single_loop(1, 3)
        self.assertEqual(events[0]["snapshot"]["status"], "error")
        self.assertEqual(events[0]["rows"], [])


class ManualQuerySnapshotTests(unittest.TestCase):
    def test_query_never_changes_saved_trip_or_recoverable_draft(self):
        from railwatch_preferences import load_trip_draft

        for trains in ("G202", ""):
            for outcome in ("success", "query_failure", "driver_failure"):
                with self.subTest(trains=trains, outcome=outcome), tempfile.TemporaryDirectory() as directory:
                    bridge = RailWatchBridge(directory)
                    saved = bridge.save_config(CONFIG)
                    draft = {**saved, "train_code": "G303"}
                    bridge.save_trip_draft(draft, 1)
                    files = [Path(bridge.config_manager.config_path), Path(directory) / "trip_draft.json",
                             Path(directory) / "trip_choices.json"]
                    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
                    bridge._valid_dates = Mock(return_value=[CONFIG["date"]])
                    bridge._ensure_driver = Mock(return_value=object())
                    analyzer = Mock()
                    analyzer.last_query = {"fetched_at": 90}
                    analyzer.open_fill_query_and_analyze.return_value = []
                    if outcome == "query_failure":
                        analyzer.open_fill_query_and_analyze.side_effect = RuntimeError("query failed")
                    elif outcome == "driver_failure":
                        bridge._ensure_driver.side_effect = RuntimeError("driver failed")
                    query = {**saved, "train_code": trains}
                    with patch("railwatch_bridge.PageAnalyzer", return_value=analyzer):
                        status = bridge.analyze_query(query, request_id="read-only-query")
                    self.assertEqual(bool(status["error_message"]), outcome != "success")
                    self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in files], before)
                    self.assertEqual(bridge.load_config()["train_code"], "G101")
                    self.assertEqual(load_trip_draft(directory)["draft"]["config"], draft)
                    self.assertEqual(query["train_code"], trains)

    def test_partial_dates_preserve_success_and_include_failed_date(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            bridge = RailWatchBridge(directory, events.append)
            bridge._ensure_driver = Mock(return_value=object())
            bridge._valid_dates = Mock(return_value=["2026-09-21", "2026-09-22", "2026-09-23"])
            analyzer = Mock()
            analyzer.last_query = {"fetched_at": 90}
            analyzer.open_fill_query_and_analyze.side_effect = [[{"train": "G101", "raw": "原始信息"}], RuntimeError("network failed")]
            with patch("railwatch_bridge.PageAnalyzer", return_value=analyzer):
                status = bridge.analyze_query({**CONFIG, "date_range": "±1天"}, request_id="manual-one")
            result = next(event["payload"] for event in events if event["event"] == "results")
            self.assertEqual(result["request_id"], "manual-one")
            self.assertEqual([s["status"] for s in result["snapshots"]], ["success", "error"])
            self.assertEqual(result["snapshots"][0]["fetched_at"], 90)
            self.assertIsNone(result["snapshots"][1]["fetched_at"])
            self.assertEqual(result["rows"][0]["date"], "2026-09-21")
            self.assertEqual(result["snapshots"][1]["conditions"]["date"], "2026-09-22")
            self.assertTrue(status["error_message"])
            starts = [e["payload"] for e in events if e["event"] == "queryStarted"]
            self.assertEqual([s["query_id"] for s in starts], [s["query_id"] for s in result["snapshots"]])

    def test_invalid_manual_owner_is_rejected_before_browser_access(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            bridge._ensure_driver = Mock()
            for owner in ("", "bad owner", 3, "x" * 129):
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    bridge.analyze_query(CONFIG, request_id=owner)
            bridge._ensure_driver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
