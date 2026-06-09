import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from railwatch_time import ServerTimeSync, reset_server_time_sync


class ServerTimeSyncTests(unittest.TestCase):
    def setUp(self):
        reset_server_time_sync()

    def test_parse_target_datetime_rolls_to_next_day_when_past(self):
        sync = ServerTimeSync()
        reference = datetime(2026, 6, 9, 15, 0, 0)
        target = sync.parse_target_datetime("08:30:00", reference=reference)
        self.assertEqual(target.date().isoformat(), "2026-06-10")
        self.assertEqual(target.strftime("%H:%M:%S"), "08:30:00")

    def test_is_in_burst_window_uses_server_offset(self):
        sync = ServerTimeSync()
        reference = datetime(2026, 6, 9, 8, 29, 58)
        with patch.object(sync, "server_timestamp", return_value=reference.timestamp()):
            with patch.object(sync, "server_now", return_value=reference):
                self.assertTrue(sync.is_in_burst_window("08:30:00", prepare_seconds=2, burst_seconds=30))

    def test_is_prewarm_window_before_burst(self):
        sync = ServerTimeSync()
        reference = datetime(2026, 6, 9, 8, 28, 30)
        with patch.object(sync, "server_timestamp", return_value=reference.timestamp()):
            with patch.object(sync, "server_now", return_value=reference):
                self.assertTrue(sync.is_prewarm_window("08:30:00", prepare_seconds=2, prewarm_lead_seconds=120))

    def test_sync_reads_date_header(self):
        class FakeResponse:
            headers = {"Date": "Tue, 09 Jun 2026 00:30:00 GMT"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        sync = ServerTimeSync()
        with patch("railwatch_time.urllib.request.urlopen", return_value=FakeResponse()):
            with patch("railwatch_time.time.time", return_value=1_748_934_000.0):
                offset = sync.sync(force=True)
        self.assertIsInstance(offset, float)


if __name__ == "__main__":
    unittest.main()
