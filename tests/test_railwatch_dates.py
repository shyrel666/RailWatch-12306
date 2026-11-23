import unittest
from datetime import date

from railwatch_dates import eligible_travel_dates, expand_travel_dates


class RailWatchDateRangeTests(unittest.TestCase):
    def test_expands_supported_presets(self):
        self.assertEqual(expand_travel_dates("2026-06-10", "单日"), ["2026-06-10"])
        self.assertEqual(
            expand_travel_dates("2026-06-10", "±1天"),
            ["2026-06-09", "2026-06-10", "2026-06-11"],
        )
        self.assertEqual(
            expand_travel_dates("2026-06-10", "±2天"),
            ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"],
        )

    def test_unknown_or_invalid_range_falls_back_to_selected_date(self):
        self.assertEqual(expand_travel_dates("2026-06-10", "自定义"), ["2026-06-10"])
        self.assertEqual(expand_travel_dates("2026-06-10", "自定义", []), ["2026-06-10"])
        with self.assertRaises(ValueError):
            expand_travel_dates("bad-date", "±2天")

    def test_custom_dates_preserve_order_deduplicate_and_include_primary(self):
        dates = ["2026-06-14", "2026-06-18", "2026-06-14", "2026-06-15", "2026-06-11", "2026-06-20"]
        self.assertEqual(expand_travel_dates("2026-06-18", "自定义", dates),
                         ["2026-06-14", "2026-06-18", "2026-06-15", "2026-06-11", "2026-06-20"])
        self.assertEqual(expand_travel_dates("2026-06-10", "自定义", dates),
                         ["2026-06-10", "2026-06-14", "2026-06-18", "2026-06-15", "2026-06-11"])
        self.assertEqual(expand_travel_dates("2026-06-10", "单日", dates), ["2026-06-10"])

    def test_custom_dates_validate_each_entry_before_truncating(self):
        dates = ["2026-06-14", "2026-06-18", "2026-06-15", "2026-06-11", "2026-06-20"]
        for invalid in ("2026-02-29", "2026-6-20", "", None, 20260620, date(2026, 6, 20)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                expand_travel_dates("2026-06-10", "自定义", [*dates, invalid])

    def test_custom_dates_presale_filter_keeps_requested_order(self):
        dates = ["2026-06-20", "2026-06-09", "2026-06-25", "2026-06-14"]
        valid, skipped = eligible_travel_dates("2026-06-14", "自定义", date(2026, 6, 10), dates)
        self.assertEqual(valid, ["2026-06-20", "2026-06-14"])
        self.assertEqual(skipped, [{"date": "2026-06-09", "reason": "已过期"},
                                   {"date": "2026-06-25", "reason": "超出可查询窗口"}])


if __name__ == "__main__":
    unittest.main()
