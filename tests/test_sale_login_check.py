"""Exercise the actual sale scheduler with fake clocks and no network."""
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_task import MonitorTask


class SaleLoginCheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bridge = RailWatchBridge(directory.name, event_callback=lambda _: None)
        self.addCleanup(self.bridge.notification_service.close)
        self.bridge.driver = Mock()
        self.bridge.driver.execute_async_script.return_value = "ok"
        self.bridge._check_device_id_consistency = Mock()
        self.bridge._task = self.task = MonitorTask({})
        self.addCleanup(self.task.done.set)
        self.clock = 1000.0
        self.probes = []
        self.task.cancel.wait = lambda seconds: setattr(self, "clock", self.clock + seconds)
        original = self.bridge._send_keep_alive
        def probe():
            self.probes.append(self.clock)
            original()
        self.bridge._send_keep_alive = probe

    def wait(self, target, config):
        self.task.config = dict(config)
        self.task.target_timestamp = target
        with patch("railwatch_bridge.time.time", lambda: self.clock), \
             patch("railwatch_bridge.time.monotonic", lambda: self.clock):
            return self.bridge._wait_for_target_timestamp(target, config)

    def test_automated_sale_gets_one_final_check_without_periodic_keep_alive(self):
        for mode in ("auto_submit", "auto_alternate"):
            with self.subTest(mode=mode):
                self.probes.clear()
                self.clock = 1000
                self.task.sale_login_checked = False
                self.assertTrue(self.wait(1180, {mode: True, "keep_alive": False}))
                self.assertEqual(len(self.probes), 1)
                self.assertAlmostEqual(self.probes[0], 1120, delta=0.21)
                self.assertGreaterEqual(self.clock, 1180)

    def test_unknown_final_check_cannot_reuse_stale_login_ready(self):
        self.bridge.state = replace(self.bridge.state, login_ready=True)
        self.bridge.driver.execute_async_script.return_value = "unknown"
        self.assertFalse(self.wait(1060, {"auto_submit": True}))
        self.assertFalse(self.bridge.state.login_ready)
        self.assertTrue(self.task.cancel.is_set())
        self.assertEqual(len(self.probes), 1)

    def test_expired_login_stops_before_sale(self):
        self.bridge.driver.execute_async_script.return_value = "expired"
        self.assertFalse(self.wait(1060, {"auto_alternate": True}))
        self.assertLess(self.clock, 1060)
        self.assertTrue(self.task.cancel.is_set())

    def test_monitor_only_with_keep_alive_disabled_does_not_probe(self):
        self.assertTrue(self.wait(1060, {"keep_alive": False}))
        self.assertEqual(self.probes, [])

    def test_final_ten_seconds_remain_free_of_login_probes(self):
        self.assertTrue(self.wait(1010, {"auto_submit": True, "keep_alive": True}))
        self.assertEqual(self.probes, [])

    def test_periodic_and_final_check_do_not_probe_twice_on_same_tick(self):
        self.assertTrue(self.wait(1180, {"auto_submit": True, "keep_alive": True}))
        self.assertEqual(len(self.probes), 2)
        self.assertGreaterEqual(self.probes[1] - self.probes[0], 59.9)
        self.assertTrue(all(1180 - tick > 10 for tick in self.probes))

    def test_cancel_before_wait_does_not_probe(self):
        self.task.cancel.set()
        self.assertFalse(self.wait(1060, {"auto_submit": True}))
        self.assertEqual(self.probes, [])

    def test_keep_alive_stays_quiet_through_the_whole_burst_window(self):
        self.task.config = {"keep_alive": True, "burst_window_seconds": 45}
        self.task.target_timestamp = 1000.0
        self.task.last_login_check = float("-inf")
        for now in (995.0, 1006.0, 1030.0, 1045.0):
            with self.subTest(now=now), patch("railwatch_bridge.time.time", return_value=now):
                self.assertTrue(self.bridge._check_session_for_task(self.task))
        self.assertEqual(self.probes, [])
        with patch("railwatch_bridge.time.time", return_value=1046.0):
            self.assertTrue(self.bridge._check_session_for_task(self.task))
        self.assertEqual(len(self.probes), 1)

    def test_clock_jump_cannot_trigger_a_late_order(self):
        self.task.cancel.wait = lambda seconds: setattr(self, "clock", self.clock + 20)
        with patch("railwatch_bridge.time.time", lambda: self.clock), \
             patch("railwatch_bridge.time.monotonic", return_value=1000):
            self.assertFalse(self.bridge._wait_for_target_timestamp(1180, {"auto_submit": True}))
        self.assertTrue(self.task.cancel.is_set())


if __name__ == "__main__":
    unittest.main()
