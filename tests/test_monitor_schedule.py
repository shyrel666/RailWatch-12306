import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from gui_12306_0 import QueryConfig, TicketMonitor
from railwatch_time import MONITOR_AUTO_STOP_MESSAGE, MONITOR_AUTO_STOP_TITLE


class MonitorScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = self.timestamp("04:58:55")
        self.sleeps = []
        self.logs = []
        self.cancelled = False
        self.notify = Mock()
        self.tick = Mock()

    @staticmethod
    def timestamp(local_time):
        return datetime.fromisoformat(f"2026-11-24T{local_time}+08:00").timestamp()

    def advance(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def monitor(self, **config):
        monitor = TicketMonitor(
            Mock(), config, log_callback=self.logs.append, notify_callback=self.notify,
            tick_callback=self.tick, wait_callback=self.advance, stop_check=lambda: self.cancelled,
        )
        monitor.prepare = Mock(return_value=True)
        monitor._run_single_loop = Mock(return_value=True)
        return monitor

    def run_monitor(self, monitor):
        with patch("gui_12306_0.time.time", side_effect=lambda: self.now):
            monitor.run()

    def test_night_maintenance_pauses_in_short_steps_and_resumes_without_backoff(self):
        monitor = self.monitor(maintenance_sleep=True, smart_rate=True)
        monitor._prepared = True
        monitor.rate_limiter.on_timeout()
        monitor._temporary_query_failures = 2

        def check_query(loop, interval):
            self.assertEqual(self.now, self.timestamp("05:00:00"))
            self.assertEqual(monitor.rate_limiter.fail_count, 0)
            self.assertEqual(monitor._temporary_query_failures, 0)
            return True

        monitor._run_single_loop.side_effect = check_query
        self.run_monitor(monitor)

        self.assertEqual(self.sleeps, [30, 30, 5])
        self.tick.assert_called_once_with(
            status="waiting", next_query_at=self.timestamp("05:00:00"),
            message="12306 夜间维护休眠中，05:00 恢复",
        )
        self.assertEqual(sum("当前处于 12306 夜间维护时段" in log for log in self.logs), 1)
        self.assertIn("12306 维护时段结束，恢复余票监控。", self.logs)
        monitor._run_single_loop.assert_called_once()
        self.notify.assert_not_called()

    def test_auto_stop_during_maintenance_does_not_resume_or_query(self):
        monitor = self.monitor(maintenance_sleep=True, auto_stop_at="2026-11-24T04:59:30+08:00")
        self.run_monitor(monitor)

        self.assertEqual(self.sleeps, [30, 5])
        self.assertEqual(self.logs.count(MONITOR_AUTO_STOP_MESSAGE), 1)
        self.assertNotIn("12306 维护时段结束，恢复余票监控。", self.logs)
        self.notify.assert_called_once_with(MONITOR_AUTO_STOP_TITLE, MONITOR_AUTO_STOP_MESSAGE)
        monitor.prepare.assert_not_called()
        monitor._run_single_loop.assert_not_called()

    def test_maintenance_sleep_honors_cancellation(self):
        monitor = self.monitor(maintenance_sleep=True)

        def cancel_during_wait(seconds):
            self.advance(1)
            self.cancelled = True

        monitor._wait_callback = cancel_during_wait
        self.run_monitor(monitor)

        self.assertEqual(self.sleeps, [1])
        self.assertNotIn("12306 维护时段结束，恢复余票监控。", self.logs)
        self.notify.assert_not_called()
        monitor.prepare.assert_not_called()
        monitor._run_single_loop.assert_not_called()

    def test_maintenance_checks_cancellation_without_a_custom_wait(self):
        monitor = self.monitor(maintenance_sleep=True)
        monitor._wait_callback = None

        def cancel_during_wait(seconds):
            self.advance(seconds)
            self.cancelled = True

        with patch("gui_12306_0.time.sleep", side_effect=cancel_during_wait):
            self.run_monitor(monitor)

        self.assertEqual(self.sleeps, [0.2])
        self.notify.assert_not_called()
        monitor._run_single_loop.assert_not_called()

    def test_deadline_bounds_query_backoff(self):
        monitor = self.monitor(auto_stop_at="2026-11-24T04:59:00+08:00")

        def query_then_backoff(loop, interval):
            monitor._sleep(60)
            return False

        monitor._run_single_loop.side_effect = query_then_backoff
        self.run_monitor(monitor)

        self.assertEqual(self.sleeps, [5])
        self.tick.assert_called_once_with(status="backoff", next_query_at=self.timestamp("04:59:00"))
        self.notify.assert_called_once_with(MONITOR_AUTO_STOP_TITLE, MONITOR_AUTO_STOP_MESSAGE)
        monitor._run_single_loop.assert_called_once()

    def test_reached_deadline_precedes_maintenance_and_preparation(self):
        monitor = self.monitor(maintenance_sleep=True, auto_stop_at="2026-11-24T04:58:55+08:00")
        self.run_monitor(monitor)

        self.assertEqual(self.sleeps, [])
        self.notify.assert_called_once_with(MONITOR_AUTO_STOP_TITLE, MONITOR_AUTO_STOP_MESSAGE)
        self.tick.assert_not_called()
        monitor.prepare.assert_not_called()
        monitor._run_single_loop.assert_not_called()

    def test_old_config_queries_during_maintenance_hours_by_default(self):
        config = QueryConfig.from_dict({"date": "2026-11-25"}).to_dict()
        self.assertFalse(config["maintenance_sleep"])
        self.assertEqual(config["auto_stop_at"], "")
        self.assertEqual(config["custom_dates"], [])
        monitor = self.monitor(**config)
        self.run_monitor(monitor)

        self.assertEqual(self.sleeps, [])
        monitor._run_single_loop.assert_called_once()

    def test_query_config_round_trips_schedule_and_custom_dates(self):
        config = QueryConfig(
            date="2026-11-25", date_range="自定义", custom_dates=["2026-11-29", "2026-11-26"],
            maintenance_sleep=True, auto_stop_at="2026-11-24T06:00:00+08:00",
        )
        restored = QueryConfig.from_dict(config.to_dict())
        self.assertEqual(restored, config)
        self.assertEqual(
            self.monitor(**restored.to_dict()).travel_dates,
            ["2026-11-25", "2026-11-29", "2026-11-26"],
        )
