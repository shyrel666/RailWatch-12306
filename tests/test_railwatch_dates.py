import unittest


class RailWatchDateRangeTests(unittest.TestCase):
    def test_expands_supported_presets(self):
        from railwatch_dates import expand_travel_dates

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
        from railwatch_dates import expand_travel_dates

        self.assertEqual(expand_travel_dates("2026-06-10", "自定义"), ["2026-06-10"])
        self.assertEqual(expand_travel_dates("bad-date", "±2天"), ["bad-date"])


if __name__ == "__main__":
    unittest.main()
