import json
import os
import tempfile
import unittest

from railwatch_preferences import load_trip_draft, save_trip_draft


class DraftPersistenceTests(unittest.TestCase):
    def test_incomplete_draft_survives_restart_and_rejects_stale_revision(self):
        with tempfile.TemporaryDirectory() as data_dir:
            first = save_trip_draft(data_dir, {"from_station_cn": "", "date": "bad-date",
                                               "auto_submit": False}, 1)
            self.assertGreater(first["saved_at"], 0)
            self.assertEqual(load_trip_draft(data_dir)["draft"]["config"]["date"], "bad-date")
            save_trip_draft(data_dir, {"from_station_cn": "北京"}, 2)
            with self.assertRaisesRegex(ValueError, "已过期"):
                save_trip_draft(data_dir, {"from_station_cn": "旧值"}, 1)
            self.assertEqual(load_trip_draft(data_dir)["draft"]["config"]["from_station_cn"], "北京")

    def test_invalid_draft_is_archived_before_new_write(self):
        with tempfile.TemporaryDirectory() as data_dir:
            path = os.path.join(data_dir, "trip_draft.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{damaged")
            self.assertEqual(load_trip_draft(data_dir)["status"], "invalid")
            save_trip_draft(data_dir, {"to_station_cn": "上海"}, 1)
            backups = [name for name in os.listdir(data_dir) if name.startswith("trip_draft.json.invalid-")]
            self.assertEqual(len(backups), 1)
            with open(os.path.join(data_dir, backups[0]), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "{damaged")
            self.assertEqual(load_trip_draft(data_dir)["status"], "available")

    def test_bad_passenger_metadata_does_not_overwrite_draft(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_trip_draft(data_dir, {"passengers": "张三"}, 1)
            with self.assertRaises(ValueError):
                save_trip_draft(data_dir, {"passenger_selections": [{"name": "张三", "ticket_type": "invalid"}]}, 2)
            self.assertEqual(load_trip_draft(data_dir)["draft"]["revision"], 1)

    def test_start_rejects_dates_changed_since_summary_before_browser_work(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_config_contract import default_config

        with tempfile.TemporaryDirectory() as data_dir:
            bridge = RailWatchBridge(data_dir=data_dir)
            with self.assertRaisesRegex(ValueError, "重新核对启动摘要"):
                bridge.start_monitor(default_config(), confirmed=True, expected_dates=["2000-01-01"])
            self.assertFalse(bridge.is_monitoring)


if __name__ == "__main__":
    unittest.main()
