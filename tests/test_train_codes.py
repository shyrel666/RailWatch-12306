"""Train number prefixes come from one shared table, including 12306's 2026 X, N and V prefixes."""
import copy
import datetime as dt
import os
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import railwatch_train_schedules as train_schedules_module
from gui_12306_0 import TicketMonitor
from railwatch_alternate_plan import AlternateChoice
from railwatch_config_contract import TRAIN_CODE_VALUE_PATTERN
from railwatch_order_page import SNAPSHOT_JS, OrderPage
from railwatch_orders import OrderIntent
from railwatch_policies import TRAIN_CODE_PREFIX, TRAIN_CODE_TABLE, validate_train_codes
from railwatch_query import MissingTargets
from railwatch_row_parser import RowParser
from railwatch_train_schedules import TrainSchedules

CONFIG = {"date": "2026-12-28", "from_station_cn": "北京", "to_station_cn": "上海",
          "train_code": "V6001", "seat_keyword": "硬座", "passengers": "张三"}
RENUMBERED = ("X1", "X9998", "N1", "N1998", "V1", "V6001", "V7998")
LEGACY = ("G101", "D12345", "C12", "Z99", "T110", "K1234", "Y701", "S1", "L123", "1461")


class TrainCodeTableTests(unittest.TestCase):
    def test_table_adds_the_new_prefixes_and_keeps_the_old_ones_during_the_transition(self):
        self.assertEqual(set(TRAIN_CODE_TABLE["prefixes"]), set("GDCZTKYSL") | set("XNV"))
        self.assertEqual(TRAIN_CODE_PREFIX, "[" + "".join(TRAIN_CODE_TABLE["prefixes"]) + "]")

    def test_invalid_tables_are_rejected_at_load(self):
        for prefixes in ([], ["G", "G"], ["g"], ["GD"], ["]"], [1], "GDC"):
            with self.subTest(prefixes=prefixes), self.assertRaisesRegex(ValueError, "车次字头定义无效"):
                validate_train_codes({"prefixes": prefixes})
        self.assertEqual(validate_train_codes(copy.deepcopy(TRAIN_CODE_TABLE)), TRAIN_CODE_TABLE)
        for rounds in (None, 1, 21, "3", 2.5, True):
            with self.subTest(rounds=rounds), self.assertRaisesRegex(ValueError, "missing_target_rounds"):
                validate_train_codes({**TRAIN_CODE_TABLE, "missing_target_rounds": rounds})


class TrainCodeUseTests(unittest.TestCase):
    def test_config_and_query_rows_accept_renumbered_and_legacy_codes(self):
        for code in (*RENUMBERED, *LEGACY):
            with self.subTest(code=code):
                self.assertTrue(TRAIN_CODE_VALUE_PATTERN.fullmatch(code))
                self.assertEqual(RowParser.extract_train_code(f"{code} 北京 上海"), code)
        for value in ("E123", "X", "XN1", "V12345678", "W12 北京"):
            with self.subTest(value=value):
                self.assertIsNone(TRAIN_CODE_VALUE_PATTERN.fullmatch(value))
                self.assertIsNone(RowParser.extract_train_code(value))

    def test_waitlist_choices_accept_renumbered_codes(self):
        for code in RENUMBERED:
            with self.subTest(code=code):
                self.assertEqual(AlternateChoice(code, "2026-12-28", "北京", "上海", "硬座").train_code, code)
        with self.assertRaisesRegex(ValueError, "候补车次无效"):
            AlternateChoice("E123", "2026-12-28", "北京", "上海", "硬座")

    def test_order_page_reads_renumbered_codes_back(self):
        # The browser-side reader uses the same prefix class as the Python readback.
        self.assertIn(f"({TRAIN_CODE_PREFIX}\\d{{1,5}}|\\d{{1,5}})", SNAPSHOT_JS)
        intent = OrderIntent.from_config(CONFIG, "V6001", "硬座", "regular")

        def read(text, target=intent):
            driver = Mock()
            driver.execute_script.return_value = {
                "url": "https://kyfw.12306.cn/otn/view/train_order.html", "dialogs": [],
                "orders": [{"order_id": "E123456", "kind": "regular", "text": text, "state": "待支付",
                            "passengers": ["张三"]}]}
            return OrderPage(driver).result(target)

        self.assertEqual(read("V6001次 2026-12-28 北京 上海 硬座 张三").status, "pending_payment")
        # A second renumbered train in the same record is evidence of another order, never ignored.
        self.assertEqual(read("V6001次 N12 2026-12-28 北京 上海 硬座 张三").status, "unknown")
        self.assertEqual(read("V6002次 2026-12-28 北京 上海 硬座 张三").status, "unknown")
        self.assertEqual(read("X1次 2026-12-28 北京 上海 二等座 张三", replace(intent, train_code="X1", seat="二等座")).status,
                         "pending_payment")

    def test_no_module_keeps_its_own_prefix_list(self):
        root = Path(__file__).resolve().parents[1]
        sources = [*root.glob("railwatch_*.py"), root / "gui_12306_0.py", *(root / "src").rglob("*.ts"),
                   *(root / "src").rglob("*.tsx")]
        for path in sources:
            with self.subTest(path=path.name):
                self.assertIsNone(re.search(r"\[(?:[GDCZTKYSLXNV]){4,}\]", path.read_text(encoding="utf-8")))


class MissingTargetTests(unittest.TestCase):
    def test_a_target_reaches_the_threshold_once_per_date_and_clears_when_listed_again(self):
        tracker = MissingTargets(3)
        others = {"G101", "G103"}
        self.assertEqual([tracker.observe("2026-11-25", ["K1234"], others) for _ in range(4)], [[], [], ["K1234"], []])
        self.assertEqual(tracker.missing(["2026-11-25"]), [{"train": "K1234", "date": "2026-11-25"}])
        # The old number still runs before the change date; that must not hide the later date.
        tracker.observe("2026-11-24", ["K1234"], {"K1234", *others})
        self.assertEqual(tracker.missing(["2026-11-24", "2026-11-25"]), [{"train": "K1234", "date": "2026-11-25"}])
        self.assertEqual(tracker.missing(["2026-11-24"]), [])
        tracker.observe("2026-11-25", ["K1234"], {"K1234"})
        self.assertEqual(tracker.missing(["2026-11-25"]), [])

    def test_each_target_counts_on_its_own(self):
        tracker = MissingTargets(2)
        for _ in range(2):
            reached = tracker.observe("2026-11-25", ["G101", "K1234"], {"G101", "G103"})
        self.assertEqual(reached, ["K1234"])
        self.assertEqual(tracker.missing(["2026-11-25"]), [{"train": "K1234", "date": "2026-11-25"}])
        self.assertEqual(MissingTargets().rounds, TRAIN_CODE_TABLE["missing_target_rounds"])

    def monitor(self, train_code="K1234"):
        logs, events = [], []
        monitor = TicketMonitor(Mock(), {**CONFIG, "date": "2026-11-25", "date_range": "单日", "train_code": train_code,
                                         "seat_keyword": "二等座", "query_timeout": 5},
                                log_callback=logs.append, run_id="run-one", progress_callback=events.append)
        monitor.query_executor = Mock()
        monitor.query_executor.current.return_value = True
        monitor._sleep = Mock()
        monitor._fill_query_params = Mock(return_value=True)
        monitor._find_hit_row = Mock(return_value=None)
        return monitor, logs, events

    def run_round(self, monitor, loop, status="ok", trains=("G101",)):
        monitor.query_executor.execute.return_value = {"status": status, "fetched_at": 90}
        monitor.row_parser.snapshot_rows = Mock(return_value=[{"train": train, "raw": "有", "seats": {"二等座": "3"}}
                                                               for train in trains])
        monitor._run_single_loop(loop, 3)

    def test_monitor_warns_once_and_reports_until_the_target_is_listed_again(self):
        monitor, logs, events = self.monitor()
        rounds = TRAIN_CODE_TABLE["missing_target_rounds"]
        for loop in range(1, rounds + 2):
            self.run_round(monitor, loop)
        warnings = [line for line in logs if "可能已因全国车次调整换号" in line]
        self.assertEqual(len(warnings), 1)
        self.assertIn("K1234", warnings[0])
        self.assertIn("2026-11-25", warnings[0])
        reports = [event["missing_targets"] for event in events]
        self.assertEqual([report["items"] for report in reports[:rounds - 1]], [[]] * (rounds - 1))
        self.assertEqual(reports[rounds - 1], {"rounds": rounds, "items": [{"train": "K1234", "date": "2026-11-25", "candidates": []}]})
        self.assertEqual(reports[rounds], reports[rounds - 1])
        self.run_round(monitor, rounds + 2, trains=("G101", "K1234"))
        self.assertEqual(events[-1]["missing_targets"], {"rounds": rounds, "items": []})
        self.assertEqual(len([line for line in logs if "可能已因全国车次调整换号" in line]), 1)

    def test_empty_failed_or_unrestricted_rounds_report_nothing(self):
        monitor, logs, events = self.monitor()
        for loop in range(1, 6):
            self.run_round(monitor, loop, status="empty")
        self.run_round(monitor, 6, status="timeout")
        self.assertTrue(events)
        self.assertFalse(any("missing_targets" in event for event in events))
        unrestricted, logs, events = self.monitor(train_code="")
        for loop in range(1, 6):
            self.run_round(unrestricted, loop)
        self.assertFalse(any("missing_targets" in event for event in events))
        self.assertFalse(any("可能已因全国车次调整换号" in line for line in logs))


def timetable(train, departure="08:00", arrival="10:05", offset=0, origin="上海虹桥", destination="南京南"):
    return {"train": train, "raw": "有", "seats": {"二等座": "3"}, "from_station": origin, "to_station": destination,
            "departure_time": departure, "arrival_time": arrival, "arrival_day_offset": offset}


class TrainScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.schedules = TrainSchedules(self.temp.name)
        self.schedules.observe([timetable("K1234"), timetable("G101", "09:00", "10:10")], "2026-11-20")

    def test_listed_train_with_the_same_stations_and_times_is_a_candidate(self):
        found = self.schedules.candidates("K1234", [timetable("N1234"), timetable("G101", "09:00", "10:10")])
        self.assertEqual(found, [{**{k: v for k, v in timetable("N1234").items() if k not in ("raw", "seats")},
                                  "seen_date": "2026-11-20"}])

    def test_any_differing_or_unread_field_is_no_match(self):
        rows = [timetable("N1", departure="08:01"), timetable("N2", arrival="10:06"), timetable("N3", offset=1),
                timetable("N4", origin="上海"), timetable("N5", destination="南京"),
                {**timetable("N6"), "arrival_day_offset": None}, {**timetable("N7"), "from_station": None}]
        self.assertEqual(self.schedules.candidates("K1234", rows), [])
        self.assertEqual(self.schedules.candidates("K9999", [timetable("N1234")]), [])
        # The missing train itself, if listed under its own number, is never its own replacement.
        self.assertEqual(self.schedules.candidates("K1234", [timetable("K1234")]), [])

    def test_rows_without_a_full_timetable_are_not_remembered(self):
        self.schedules.observe([{**timetable("Z9"), "arrival_time": None}, {"train": "Z10"}], "2026-11-20")
        self.assertEqual(self.schedules.candidates("Z9", [timetable("N9")]), [])

    def test_flush_writes_only_changes_and_survives_a_restart(self):
        with patch("railwatch_train_schedules.atomic_write_json", wraps=train_schedules_module.atomic_write_json) as write:
            self.schedules.flush()
            self.schedules.observe([timetable("K1234")], "2026-11-20")
            self.schedules.flush()
            self.assertEqual(write.call_count, 1)
        restored = TrainSchedules(self.temp.name)
        self.assertEqual([entry["train"] for entry in restored.candidates("K1234", [timetable("N1234")])], ["N1234"])

    def test_flush_keeps_the_most_recently_seen_entries(self):
        with patch("railwatch_train_schedules.MAX_ENTRIES", 2), patch("railwatch_train_schedules.time.time", side_effect=[4e9, 4e9 + 1, 4e9 + 2]):
            for index, train in enumerate(("A1", "A2", "A3")):
                self.schedules.observe([timetable(train, departure=f"0{index}:00")], "2026-11-21")
            self.schedules.flush()
        restored = TrainSchedules(self.temp.name)
        self.assertEqual(restored.candidates("A1", [timetable("B1", departure="00:00")]), [])
        self.assertEqual([entry["train"] for entry in restored.candidates("A3", [timetable("B3", departure="02:00")])], ["B3"])

    def test_unreadable_file_starts_empty(self):
        with open(os.path.join(self.temp.name, train_schedules_module.FILE_NAME), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertEqual(TrainSchedules(self.temp.name).candidates("K1234", [timetable("N1234")]), [])


class RenumberSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_monitor_reports_and_logs_the_matching_new_number_once(self):
        schedules = TrainSchedules(self.temp.name)
        schedules.observe([timetable("K1234")], "2026-11-20")
        logs, events = [], []
        monitor = TicketMonitor(Mock(), {**CONFIG, "date": "2026-11-25", "date_range": "单日", "train_code": "K1234",
                                         "seat_keyword": "二等座", "query_timeout": 5},
                                log_callback=logs.append, run_id="run-one", progress_callback=events.append,
                                train_schedules=schedules)
        monitor.query_executor = Mock()
        monitor.query_executor.current.return_value = True
        monitor._sleep = Mock()
        monitor._fill_query_params = Mock(return_value=True)
        monitor._find_hit_row = Mock(return_value=None)
        rounds = TRAIN_CODE_TABLE["missing_target_rounds"]
        for loop in range(1, rounds + 2):
            monitor.query_executor.execute.return_value = {"status": "ok", "fetched_at": 90}
            monitor.row_parser.snapshot_rows = Mock(return_value=[timetable("N1234"), timetable("G101", "09:00")])
            monitor._run_single_loop(loop, 3)
        item = events[-1]["missing_targets"]["items"][0]
        self.assertEqual((item["train"], [entry["train"] for entry in item["candidates"]]), ("K1234", ["N1234"]))
        self.assertEqual(len([line for line in logs if "可能已改为 N1234" in line]), 1)
        # Every complete round is remembered, so the new number is known for later matches too.
        self.assertEqual([entry["train"] for entry in schedules.candidates("N1234", [timetable("X1234")])], ["X1234"])

    def test_manual_query_suggests_and_persists_without_a_threshold(self):
        from railwatch_bridge import RailWatchBridge
        events = []

        class FakeAnalyzer:
            def __init__(self, driver, log_callback=None, base_dir=None):
                pass

            def open_fill_query_and_analyze(self, config):
                return [timetable("N1234"), timetable("G101", "09:00")]

        bridge = RailWatchBridge(data_dir=self.temp.name, event_callback=events.append)
        bridge.train_schedules.observe([timetable("K1234")], "2026-11-20")
        bridge._ensure_driver = lambda: object()
        with patch("railwatch_bridge.PageAnalyzer", FakeAnalyzer), patch("railwatch_bridge.CORE_AVAILABLE", True), \
                patch("railwatch_bridge.beijing_now", return_value=dt.datetime(2026, 11, 20)):
            bridge.analyze_query({"from_station_cn": "上海", "to_station_cn": "南京", "date": "2026-11-25",
                                  "date_range": "单日", "train_code": "K1234, G101"})
        results = [event["payload"] for event in events if event.get("event") == "results"]
        self.assertEqual([(item["train"], item["date"], [entry["train"] for entry in item["candidates"]])
                          for item in results[-1]["renumber"]], [("K1234", "2026-11-25", ["N1234"])])
        restored = TrainSchedules(self.temp.name)
        self.assertEqual([entry["train"] for entry in restored.candidates("K1234", [timetable("N1234")])], ["N1234"])


if __name__ == "__main__":
    unittest.main()
