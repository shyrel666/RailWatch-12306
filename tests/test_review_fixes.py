"""Regression cases from the core review; no live railway requests."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from gui_12306_0 import SeatType
from railwatch_bridge import RailWatchBridge
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_row_parser import RowParser
from railwatch_task import MonitorTask, TaskCancelled


CONFIG = {"date":"2026-09-10", "from_station_cn":"北京", "to_station_cn":"上海",
          "train_code":"G101", "seat_keyword":"二等座", "passengers":"张三"}


class ReviewRegressionTests(unittest.TestCase):
    def test_readback_report_only_lists_mismatches_and_masks_both_passenger_lists(self):
        from railwatch_order_page import OrderPage
        page = OrderPage(Mock())
        intent = OrderIntent.from_config(CONFIG, "G101", "二等座", "regular")
        page.snapshot = lambda: {"regular": "G101次 2026-09-10 北京站 上海站 张三 李四",
                                 "passengers": ["李四"], "seats": ["二等座（500元）"]}
        report = page.form_mismatch_report(intent)
        self.assertIn("乘车人：期望 1 位指定乘客，实际 1 位，名单不一致", report)
        for value in ("车次：", "日期：", "出发站：", "到达站：", "席别：", "张三", "李四"):
            self.assertNotIn(value, report)

    def test_readback_report_identifies_reversed_route(self):
        from railwatch_order_page import OrderPage
        page = OrderPage(Mock())
        intent = OrderIntent.from_config(CONFIG, "G101", "二等座", "regular")
        page.snapshot = lambda: {"regular": "G101次 2026-09-10 上海站 北京站",
                                 "passengers": ["张三"], "seats": ["二等座"]}
        self.assertIn("出发站与到达站顺序不一致", page.form_mismatch_report(intent))

    def test_every_standard_seat_maps_to_its_own_column(self):
        for seat in SeatType:
            with self.subTest(seat=seat.value[0]):
                self.assertEqual(SeatType.get_prefix(seat.value[0]), seat.value[1])
        self.assertIsNone(SeatType.get_prefix("卧"))
        self.assertIsNone(SeatType.get_prefix(""))

    def test_train_field_supports_numeric_and_prefixed_codes_without_parsing_prices(self):
        for code in ("G101", "1461", "Y701", "L123", "S1234"):
            self.assertEqual(RowParser.extract_train_code(code + " 北京 上海"), code)
        for value in ("08:30 1461", "2026-09-10", "票价 1461 元", "1234.50", "G1010x"):
            self.assertIsNone(RowParser.extract_train_code(value))

    def test_cancellation_releases_recovery_but_never_erases_a_submit_marker(self):
        for submitted in (False, True):
            with self.subTest(submitted=submitted), tempfile.TemporaryDirectory() as directory:
                bridge = RailWatchBridge(directory)
                intent = OrderIntent.from_config(CONFIG, "G101", "二等座", "regular")
                bridge.order_journal.begin("original", intent, CONFIG)
                bridge._task = task = MonitorTask(CONFIG)
                page = Mock()
                page.result.return_value = OrderResult("unknown")
                page.snapshot.return_value = {"formReady":True}
                def cancelled(*args, **kwargs):
                    if submitted:
                        bridge.order_journal.mark(task.run_id, "regular_submit", intent.intent_id)
                    raise TaskCancelled()
                page.regular.side_effect = cancelled
                with patch.object(bridge, "_ensure_driver", return_value=Mock()), \
                     patch.object(bridge, "_start_monitor_heartbeat"), \
                     patch("railwatch_bridge.guard_browser", return_value=nullcontext()), \
                     patch("railwatch_bridge.OrderPage", return_value=page):
                    bridge._resume_order_worker(task, bridge.order_journal.pending())
                self.assertIsNotNone(bridge.order_journal.pending())
                self.assertEqual(bridge.order_journal.submission_started(intent.intent_id), submitted)
                try:
                    self.assertEqual(bridge.order_journal.claim_resume("retry", intent.intent_id), not submitted)
                finally:
                    bridge.order_journal.release_resume("retry", intent.intent_id)

    def test_a_live_recovery_cannot_be_cleared_by_another_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(Path(directory) / "orders.sqlite3")
            intent = OrderIntent.from_config(CONFIG, "G101", "二等座", "regular")
            journal.begin("original", intent, CONFIG)
            self.assertTrue(journal.claim_resume("owner", intent.intent_id))
            try:
                other = OrderJournal(journal.filename)
                self.assertTrue(other.submission_started(intent.intent_id))
                self.assertFalse(other.claim_resume("other", intent.intent_id))
            finally:
                journal.release_resume("owner", intent.intent_id)

    def test_process_crash_reclaims_only_the_recovery_lease(self):
        for submitted in (False, True):
            with self.subTest(submitted=submitted), tempfile.TemporaryDirectory() as directory:
                journal = OrderJournal(Path(directory) / "orders.sqlite3")
                intent = OrderIntent.from_config(CONFIG, "G101", "二等座", "regular")
                journal.begin("original", intent, CONFIG)
                code = "\n".join([
                    "import os, sys",
                    "from railwatch_orders import OrderJournal",
                    "journal = OrderJournal(sys.argv[1])",
                    "assert journal.claim_resume('crash', sys.argv[2])",
                    "if sys.argv[3] == '1': journal.mark('crash', 'regular_submit', sys.argv[2])",
                    "os._exit(0)",
                ])
                completed = subprocess.run([sys.executable, "-c", code, journal.filename, intent.intent_id, str(int(submitted))],
                    cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(completed.returncode, 0, completed.stderr)
                recovered = OrderJournal(journal.filename)
                self.assertEqual(recovered.submission_started(intent.intent_id), submitted)
                self.assertIsNotNone(recovered.pending())
                try:
                    self.assertEqual(recovered.claim_resume("retry", intent.intent_id), not submitted)
                finally:
                    recovered.release_resume("retry", intent.intent_id)


if __name__ == "__main__":
    unittest.main()
