"""Regression evidence for the risk-control review; no external service calls."""
import tempfile
import unittest
from unittest.mock import Mock, patch

from anti_detect import AdaptiveRateLimiter
from gui_12306_0 import TicketMonitor
from railwatch_bridge import RailWatchBridge


class RateLimitReviewTests(unittest.TestCase):
    def test_jitter_respects_both_interval_bounds(self):
        limiter = AdaptiveRateLimiter(3, 3, 30)
        for current, endpoint in ((3, "low"), (30, "high")):
            with self.subTest(current=current):
                limiter.current_interval = current
                with patch("anti_detect.random.uniform", side_effect=lambda low, high: low if endpoint == "low" else high):
                    interval = limiter.get_interval()
                self.assertGreaterEqual(interval, 3)
                self.assertLessEqual(interval, 30)

    def test_invalid_interval_configuration_is_rejected(self):
        for values in ((0, 0, 30), (5, 10, 3), (float("nan"), 3, 30), (5, 3, float("inf"))):
            with self.subTest(values=values), self.assertRaises(ValueError):
                AdaptiveRateLimiter(*values)

    def test_initial_and_reset_interval_respect_bounds(self):
        for base, expected in ((1, 3), (60, 30)):
            with self.subTest(base=base):
                limiter = AdaptiveRateLimiter(base, 3, 30, log_callback=lambda _: None)
                self.assertEqual(limiter.current_interval, expected)
                limiter.on_timeout()
                limiter.reset()
                self.assertEqual(limiter.current_interval, expected)

    def test_risk_signal_requires_sustained_success_to_clear(self):
        limiter = AdaptiveRateLimiter(5, 3, 30, log_callback=lambda _: None)
        limiter.on_error("操作过快")
        backed_off = limiter.current_interval
        for _ in range(4):
            limiter.on_success()
            self.assertTrue(limiter.risk_detected)
            self.assertEqual(limiter.current_interval, backed_off)
        limiter.on_success()
        self.assertFalse(limiter.risk_detected)
        self.assertGreater(limiter.current_interval, limiter.base_interval)


class MonitorRiskReviewTests(unittest.TestCase):
    def make_monitor(self, **config):
        return TicketMonitor(Mock(), {"interval": 5, "smart_rate": True, **config},
                             log_callback=lambda _: None, server_time_sync=Mock())

    def test_slow_user_interval_is_not_accelerated_by_timeout(self):
        monitor = self.make_monitor(interval=60)
        monitor.rate_limiter.on_timeout()
        self.assertGreaterEqual(monitor.rate_limiter.current_interval, 60)

    def test_exception_sleeps_using_updated_backoff(self):
        monitor = self.make_monitor()
        monitor.should_stop = Mock(side_effect=[False, True])
        monitor._run_single_loop = Mock(side_effect=RuntimeError("connection interrupted"))
        monitor._sleep = Mock()
        with patch("gui_12306_0.WebDriverWait"), patch("anti_detect.random.uniform", return_value=0):
            monitor.run()
        monitor._sleep.assert_called_once_with(7.5)

    def test_compatibility_query_timeout_sleeps_using_updated_backoff(self):
        monitor = self.make_monitor()
        monitor._is_burst_mode = Mock(return_value=False)
        monitor.click_query_button = Mock(return_value=False)
        monitor._sleep = Mock()
        with patch("anti_detect.random.uniform", return_value=0):
            self.assertFalse(monitor._run_single_loop(1, 5))
        monitor._sleep.assert_called_once_with(6.5)

    def test_smart_rate_applies_during_not_on_sale_burst(self):
        monitor = self.make_monitor()
        monitor.query_executor = Mock()
        monitor.query_executor.execute.return_value = {"status": "not_on_sale"}
        monitor._is_burst_mode = Mock(return_value=True)
        monitor._dismiss_query_blockers = Mock(return_value="未到起售时间")
        monitor._sleep = Mock()
        self.assertFalse(monitor._run_single_loop(1, 5))
        monitor._sleep.assert_called_once_with(5)

    def test_invalidated_result_waits_before_next_query(self):
        for checkpoint in range(3):
            with self.subTest(checkpoint=checkpoint):
                monitor = self.make_monitor()
                monitor.query_executor = Mock()
                monitor.query_executor.execute.return_value = {"status": "ok"}
                monitor.query_executor.current.side_effect = [True] * checkpoint + [False]
                monitor.row_parser.snapshot_rows = Mock(return_value=[])
                monitor._find_hit_row = Mock(return_value=("G101", "二等座", "有", Mock(), Mock(), "book"))
                monitor._is_burst_mode = Mock(return_value=False)
                monitor._sleep = Mock()
                self.assertFalse(monitor._run_single_loop(1, 5))
                monitor._sleep.assert_called_once_with(5)
                self.assertTrue(monitor._needs_navigation)
                if checkpoint == 0:
                    self.assertEqual(monitor.rate_limiter.success_streak, 0)


class DeviceTrackerWiringReviewTests(unittest.TestCase):
    def test_real_creation_path_tracks_login_and_cookie_change(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            bridge = RailWatchBridge(directory, event_callback=events.append)
            driver = Mock()
            driver.get_cookies.return_value = [{"name": "RAIL_DEVICEID", "value": "initial-device-secret"}]
            with patch.object(bridge, "_ensure_matching_chromedriver"), patch("railwatch_bridge.webdriver.Chrome", return_value=driver):
                bridge._ensure_driver()
            self.assertIsNotNone(bridge.device_id_protector)
            self.assertIs(bridge.device_id_protector.driver, driver)
            driver.execute_async_script.return_value = {"data": {"flag": True}}
            bridge.check_login()
            self.assertEqual(bridge.device_id_protector.saved_device_id, "initial-device-secret")
            driver.get_cookies.return_value = [{"name": "RAIL_DEVICEID", "value": "changed-device-secret"}]
            driver.execute_async_script.return_value = "ok"
            bridge._send_keep_alive()
            self.assertIn("会话设备标识发生变化", str(events))
            self.assertNotIn("initial-device-secret", str(events))
            self.assertNotIn("changed-device-secret", str(events))
            driver.add_cookie.assert_not_called()

    def test_release_discards_tracker_for_old_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            bridge.driver = Mock()
            bridge.device_id_protector = Mock()
            with patch.object(bridge, "_dispose_driver"):
                bridge._release_driver()
            self.assertIsNone(bridge.device_id_protector)

    def test_environment_probe_does_not_replace_active_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            bridge.driver = active = Mock()
            bridge.device_id_protector = tracker = Mock()
            with patch.object(bridge, "_ensure_matching_chromedriver"), patch("railwatch_bridge.webdriver.Chrome", return_value=Mock()):
                bridge._ensure_driver(test_only=True)
            self.assertIs(bridge.driver, active)
            self.assertIs(bridge.device_id_protector, tracker)


if __name__ == "__main__":
    unittest.main()
