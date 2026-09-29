import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from railwatch_time import ServerTimeSync, reset_server_time_sync


class ServerTimeSyncTests(unittest.TestCase):
    def setUp(self):
        reset_server_time_sync()

    def test_parse_target_datetime_does_not_silently_roll_to_next_day(self):
        sync = ServerTimeSync()
        reference = datetime(2026, 6, 9, 15, 0, 0)
        target = sync.parse_target_datetime("08:30:00", reference=reference)
        self.assertEqual(target.date().isoformat(), "2026-06-09")
        self.assertEqual(target.strftime("%H:%M:%S"), "08:30:00")

    def test_is_in_burst_window_uses_the_selected_clock(self):
        sync = ServerTimeSync()
        reference = datetime(2026, 6, 9, 8, 29, 58)
        with patch.object(sync, "server_timestamp", return_value=reference.timestamp()):
            with patch.object(sync, "server_now", return_value=reference):
                self.assertTrue(sync.is_in_burst_window("08:30:00", prepare_seconds=2, burst_seconds=30))

    def test_is_in_burst_window_remains_active_after_target_second(self):
        sync = ServerTimeSync()
        reference = datetime(2026, 6, 9, 8, 30, 1)
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

    def response(self, **headers):
        response = Mock()
        response.headers = {"Date": "Tue, 09 Jun 2026 00:30:00 GMT", **headers}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_slow_http_sample_exposes_uncertainty_without_changing_scheduler_clock(self):
        sync = ServerTimeSync()
        server = datetime.fromisoformat("2026-06-09T00:30:00+00:00").timestamp()
        with patch("railwatch_time.urllib.request.urlopen", return_value=self.response()), \
             patch("railwatch_time.time.monotonic", side_effect=[100, 100, 110]), \
             patch("railwatch_time.time.time", side_effect=[server - 10, server - 10, server]):
            self.assertEqual(sync.sync(force=True), 5.5)
        self.assertEqual(sync.uncertainty_seconds, 5.5)
        self.assertEqual(sync.rtt_seconds, 10)
        with patch("railwatch_time.time.time", return_value=server):
            self.assertEqual(sync.server_timestamp(), server)

    def test_wall_clock_change_during_sample_invalidates_old_offset(self):
        sync = ServerTimeSync()
        sync._offset_seconds = 3
        sync.uncertainty_seconds = .5
        with patch("railwatch_time.urllib.request.urlopen", return_value=self.response()), \
             patch("railwatch_time.time.monotonic", side_effect=[100, 100, 101]), \
             patch("railwatch_time.time.time", side_effect=[1000, 1000, 1003]):
            self.assertEqual(sync.sync(force=True), 0)
        self.assertIsNone(sync.uncertainty_seconds)
        self.assertIn("系统时间发生变化", sync.last_error)

    def test_cached_invalid_or_failed_sample_never_reuses_an_old_estimate(self):
        for headers in ({"Age": "1"}, {"Age": "NaN"}, {"Age": "-1"},
                        {"Date": "invalid"}, {"Date": None}):
            with self.subTest(headers=headers):
                sync = ServerTimeSync()
                sync._offset_seconds = 9
                with patch("railwatch_time.urllib.request.urlopen", return_value=self.response(**headers)):
                    self.assertEqual(sync.sync(force=True), 0)
                self.assertIsNone(sync.uncertainty_seconds)
                self.assertTrue(sync.last_error)
        sync._offset_seconds, sync.rtt_seconds = 9, .1
        with patch("railwatch_time.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertEqual(sync.sync(force=True), 0)
        self.assertIsNone(sync.rtt_seconds)
        self.assertIsNone(sync.uncertainty_seconds)


if __name__ == "__main__":
    unittest.main()
