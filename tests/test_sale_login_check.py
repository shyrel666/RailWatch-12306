"""Exercise the actual sale scheduler with fake clocks and no network."""
import datetime as dt
import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_dates import beijing_now
from railwatch_policies import QUERY_STRATEGIES
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
        # The first probe plus the two packaged rechecks, five seconds apart.
        self.assertEqual(len(self.probes), 3)
        self.assertAlmostEqual(self.probes[1] - self.probes[0], 5, delta=0.21)
        self.assertAlmostEqual(self.probes[2] - self.probes[1], 5, delta=0.21)
        self.assertTrue(all(1060 - tick > 10 for tick in self.probes))
        self.assertLess(self.clock, 1060)

    def test_one_inconclusive_probe_is_rechecked_and_the_sale_continues(self):
        self.bridge.driver.execute_async_script.side_effect = ["unknown", "ok"]
        self.assertTrue(self.wait(1060, {"auto_submit": True}))
        self.assertEqual(len(self.probes), 2)
        self.assertTrue(self.bridge.state.login_ready)
        self.assertFalse(self.task.cancel.is_set())
        self.assertGreaterEqual(self.clock, 1060)

    def test_probe_exception_counts_as_inconclusive_and_is_rechecked(self):
        self.bridge.driver.execute_async_script.side_effect = [TimeoutError("script timeout"), "ok"]
        self.assertTrue(self.wait(1060, {"auto_alternate": True}))
        self.assertEqual(len(self.probes), 2)

    def test_recheck_that_finds_an_expired_login_stops_before_sale(self):
        self.bridge.driver.execute_async_script.side_effect = ["unknown", "expired"]
        self.assertFalse(self.wait(1060, {"auto_submit": True}))
        self.assertEqual(len(self.probes), 2)
        self.assertLess(self.clock, 1060)
        self.assertTrue(self.task.cancel.is_set())

    def test_no_recheck_when_it_could_not_finish_before_the_final_ten_seconds(self):
        self.bridge.driver.execute_async_script.return_value = "unknown"
        # 18 seconds left: a recheck five seconds later could still be running at T-10.
        self.assertFalse(self.wait(1018, {"auto_submit": True}))
        self.assertEqual(len(self.probes), 1)
        self.assertTrue(self.task.cancel.is_set())

    def test_recheck_limit_zero_stops_on_the_first_inconclusive_probe(self):
        self.bridge.driver.execute_async_script.return_value = "unknown"
        with patch.dict(QUERY_STRATEGIES["sale_start"], {"login_recheck_limit": 0}):
            self.assertFalse(self.wait(1060, {"auto_submit": True}))
        self.assertEqual(len(self.probes), 1)
        self.assertTrue(self.task.cancel.is_set())

    def test_rechecks_do_not_add_periodic_keep_alive_probes(self):
        self.bridge.driver.execute_async_script.side_effect = ["ok", "unknown", "ok"]
        self.assertTrue(self.wait(1180, {"auto_submit": True, "keep_alive": True}))
        # Periodic probe at T-120, final check at T-60, one recheck at T-55.
        self.assertEqual(len(self.probes), 3)
        self.assertAlmostEqual(self.probes[2] - self.probes[1], 5, delta=0.21)

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

    def test_maintenance_deferred_final_login_check_runs_at_five_am_boundary(self):
        resume = dt.datetime.fromisoformat("2026-06-10T05:00:00+08:00").timestamp()
        for probe_result, expected in (("ok", True), ("expired", False), ("unknown", False)):
            with self.subTest(probe_result=probe_result):
                self.probes.clear()
                self.task.cancel.clear()
                self.task.sale_login_checked = False
                self.task.sale_login_rechecks = 0
                self.task.sale_login_retry_at = float("-inf")
                self.bridge._keep_alive_last_state = None
                self.bridge._keep_alive_unknown_count = 0
                self.bridge.state = replace(self.bridge.state, login_ready=True)
                self.bridge.driver.execute_async_script.side_effect = None
                self.bridge.driver.execute_async_script.return_value = probe_result
                self.clock = resume - 70.0
                self.assertEqual(
                    self.wait(resume, {"auto_submit": True, "maintenance_sleep": True, "keep_alive": False}),
                    expected,
                )
                self.assertEqual(len(self.probes), 1)
                self.assertGreaterEqual(self.probes[0], resume)
                self.assertTrue(self.task.sale_login_checked)
                self.assertEqual(self.bridge.state.login_ready, expected)
                self.assertEqual(self.task.cancel.is_set(), not expected)

    def test_maintenance_deferred_final_login_check_runs_when_maintenance_ends_inside_final_ten_seconds(self):
        resume = dt.datetime.fromisoformat("2026-06-10T05:00:00+08:00").timestamp()
        target = resume + 5.0
        for probe_result, expected in (("ok", True), ("expired", False)):
            with self.subTest(probe_result=probe_result):
                self.probes.clear()
                self.task.cancel.clear()
                self.task.sale_login_checked = False
                self.task.sale_login_rechecks = 0
                self.task.sale_login_retry_at = float("-inf")
                self.bridge._keep_alive_last_state = None
                self.bridge._keep_alive_unknown_count = 0
                self.bridge.state = replace(self.bridge.state, login_ready=True)
                self.bridge.driver.execute_async_script.side_effect = None
                self.bridge.driver.execute_async_script.return_value = probe_result
                self.clock = resume - 60.0
                self.assertEqual(
                    self.wait(target, {"auto_alternate": True, "maintenance_sleep": True, "keep_alive": False}),
                    expected,
                )
                self.assertEqual(len(self.probes), 1)
                self.assertAlmostEqual(self.probes[0], resume, delta=0.25)
                self.assertTrue(self.task.sale_login_checked)
                if expected:
                    self.assertGreaterEqual(self.clock, target)
                else:
                    self.assertLess(self.clock, target)
                    self.assertTrue(self.task.cancel.is_set())

    def test_maintenance_target_persists_deferred_login_check_past_burst_window_before_first_query(self):
        from gui_12306_0 import TicketMonitor

        resume = dt.datetime.fromisoformat("2026-06-11T05:00:00+08:00").timestamp()
        target = resume - 1.0  # 04:59:59: still inside maintenance, with 05:00:00 inside the 45s burst window.
        for keep_alive in (True, False):
            for probe_result, expected in (("expired", False), ("ok", True)):
                with self.subTest(keep_alive=keep_alive, probe_result=probe_result):
                    self.probes.clear()
                    self.task.cancel.clear()
                    self.task.sale_login_checked = False
                    self.task.deferred_sale_login_check = False
                    self.task.sale_login_rechecks = 0
                    self.task.sale_login_retry_at = float("-inf")
                    self.task.last_login_check = float("-inf")
                    self.bridge._keep_alive_last_state = None
                    self.bridge._keep_alive_unknown_count = 0
                    self.bridge.state = replace(self.bridge.state, login_ready=True)
                    self.bridge.driver.execute_async_script.side_effect = None
                    self.bridge.driver.execute_async_script.return_value = probe_result
                    self.clock = target - 65.0
                    wait_cfg = {
                        "auto_submit": True,
                        "maintenance_sleep": True,
                        "keep_alive": keep_alive,
                        "burst_window_seconds": 45,
                    }
                    self.assertTrue(self.wait(target, wait_cfg))
                    # Target itself fell inside maintenance, so no probe fired yet and deferral stayed on task.
                    self.assertEqual(self.probes, [])
                    self.assertTrue(self.task.deferred_sale_login_check)
                    self.assertFalse(self.task.sale_login_checked)

                    # Simulate maintenance ending at 05:00:00 and TicketMonitor entering its first query loop.
                    self.task.config = {"auto_submit": True, "keep_alive": keep_alive, "burst_window_seconds": 45}
                    self.task.target_timestamp = target
                    monitor = TicketMonitor(
                        self.bridge.driver,
                        {**wait_cfg, "_target_timestamp": target, "date": "2026-06-25"},
                        log_callback=lambda *_: None,
                        stop_check=self.task.cancel.is_set,
                        wait_callback=lambda seconds: setattr(self, "clock", self.clock + seconds),
                        session_check=lambda: self.bridge._check_session_for_task(self.task),
                    )
                    monitor._prepared = True
                    monitor._fill_query_params = Mock(return_value=True)
                    monitor._apply_loop_date = Mock()
                    with (
                        patch("railwatch_bridge.time.time", lambda: self.clock),
                        patch("railwatch_bridge.time.monotonic", lambda: self.clock),
                        patch("gui_12306_0.time.time", lambda: self.clock),
                        patch("gui_12306_0.time.monotonic", lambda: self.clock),
                    ):
                        self.assertTrue(monitor.wait_for_monitoring_window())
                        self.assertGreaterEqual(self.clock, resume)
                        # Confirm 05:00:00 is still inside the 45s burst window that normally suppresses keep_alive.
                        self.assertLessEqual(self.clock, target + 45)
                        if not expected:
                            # Expired login must abort _query_loop before any query parameters or requests run.
                            self.assertTrue(monitor._query_loop(1, 1.0))
                            monitor._fill_query_params.assert_not_called()
                            self.assertFalse(self.bridge.state.login_ready)
                            self.assertTrue(self.task.cancel.is_set())
                        else:
                            self.assertTrue(self.bridge._check_session_for_task(self.task))
                            self.assertTrue(self.task.sale_login_checked)
                            self.assertFalse(self.task.deferred_sale_login_check)
                            # Subsequent burst-window checks remain quiet.
                            self.clock = target + 20.0
                            self.assertTrue(self.bridge._check_session_for_task(self.task))
                    self.assertEqual(len(self.probes), 1)
                    self.assertGreaterEqual(self.probes[0], resume)

    def test_auto_stop_reached_during_post_maintenance_login_check_blocks_first_query(self):
        from gui_12306_0 import TicketMonitor
        from railwatch_time import MONITOR_AUTO_STOP_MESSAGE

        resume = dt.datetime.fromisoformat("2026-06-11T05:00:00+08:00").timestamp()
        auto_stop = dt.datetime.fromisoformat("2026-06-11T05:00:01+08:00").isoformat()
        target = resume - 1.0  # 04:59:59

        # Case 1: Deferred check runs inside TicketMonitor._query_loop at 05:00:00 and takes 2s -> finishes at 05:00:02.
        self.probes.clear()
        self.task.cancel.clear()
        self.task.sale_login_checked = False
        self.task.deferred_sale_login_check = False
        self.task.last_login_check = float("-inf")
        self.bridge._keep_alive_last_state = None
        self.bridge._keep_alive_unknown_count = 0
        self.clock = target - 65.0

        def slow_ok(*_args, **_kwargs):
            self.clock += 2.0
            return "ok"

        self.bridge.driver.execute_async_script.side_effect = slow_ok
        wait_cfg = {
            "auto_submit": True,
            "maintenance_sleep": True,
            "keep_alive": True,
            "auto_stop_at": auto_stop,
            "burst_window_seconds": 45,
        }
        self.assertTrue(self.wait(target, wait_cfg))
        self.assertTrue(self.task.deferred_sale_login_check)

        logs = []
        self.task.config = {"auto_submit": True, "keep_alive": True, "burst_window_seconds": 45}
        self.task.target_timestamp = target
        monitor = TicketMonitor(
            self.bridge.driver,
            {**wait_cfg, "_target_timestamp": target, "date": "2026-06-25"},
            log_callback=lambda msg, *_: logs.append(msg),
            stop_check=self.task.cancel.is_set,
            wait_callback=lambda seconds: setattr(self, "clock", self.clock + seconds),
            session_check=lambda: self.bridge._check_session_for_task(self.task),
        )
        monitor._prepared = True
        monitor._fill_query_params = Mock(return_value=True)
        monitor._apply_loop_date = Mock()
        monitor.query_executor = Mock()
        with (
            patch("railwatch_bridge.time.time", lambda: self.clock),
            patch("railwatch_bridge.time.monotonic", lambda: self.clock),
            patch("gui_12306_0.time.time", lambda: self.clock),
            patch("gui_12306_0.time.monotonic", lambda: self.clock),
        ):
            self.assertTrue(monitor.wait_for_monitoring_window())
            self.assertEqual(self.clock, resume)
            # session_check finishes at 05:00:02 (> 05:00:01 auto_stop_at), so _query_loop stops before querying.
            self.assertTrue(monitor._query_loop(1, 1.0))
        self.assertEqual(len(self.probes), 1)
        self.assertGreaterEqual(self.clock, resume + 2.0)
        monitor._fill_query_params.assert_not_called()
        monitor.query_executor.execute.assert_not_called()
        self.assertIn(MONITOR_AUTO_STOP_MESSAGE, logs)

        # Case 2: Target is 05:00:00 and deferred check inside _wait_for_target_timestamp takes 2s past 05:00:01.
        self.probes.clear()
        self.task.cancel.clear()
        self.task.sale_login_checked = False
        self.task.deferred_sale_login_check = False
        self.bridge._keep_alive_last_state = None
        self.clock = resume - 65.0
        self.assertFalse(self.wait(resume, {**wait_cfg, "keep_alive": False}))
        self.assertEqual(len(self.probes), 1)

    def test_pre_maintenance_login_check_is_invalidated_when_target_falls_in_maintenance(self):
        from gui_12306_0 import TicketMonitor

        target = dt.datetime.fromisoformat("2026-06-11T01:00:50+08:00").timestamp()
        resume = dt.datetime.fromisoformat("2026-06-11T05:00:00+08:00").timestamp()
        self.probes.clear()
        self.task.cancel.clear()
        self.task.sale_login_checked = False
        self.task.deferred_sale_login_check = False
        self.task.last_login_check = float("-inf")
        self.bridge._keep_alive_last_state = None
        self.bridge._keep_alive_unknown_count = 0
        self.bridge.state = replace(self.bridge.state, login_ready=True)
        # First probe at 00:59:50 succeeds; session expires during 01:00-05:00 maintenance.
        self.bridge.driver.execute_async_script.side_effect = ["ok", "expired"]
        self.clock = target - 110.0  # 00:59:00

        wait_cfg = {"auto_submit": True, "maintenance_sleep": True, "keep_alive": False}
        self.assertTrue(self.wait(target, wait_cfg))
        self.assertEqual(len(self.probes), 1)
        self.assertLess(self.probes[0], dt.datetime.fromisoformat("2026-06-11T01:00:00+08:00").timestamp())
        # Reaching target inside maintenance invalidates the pre-maintenance check for post-05:00 recovery.
        self.assertFalse(self.task.sale_login_checked)
        self.assertTrue(self.task.deferred_sale_login_check)

        self.task.config = {"auto_submit": True, "keep_alive": False}
        self.task.target_timestamp = target
        monitor = TicketMonitor(
            self.bridge.driver,
            {**wait_cfg, "_target_timestamp": target, "date": "2026-06-25"},
            log_callback=lambda *_: None,
            stop_check=self.task.cancel.is_set,
            wait_callback=lambda seconds: setattr(self, "clock", self.clock + seconds),
            session_check=lambda: self.bridge._check_session_for_task(self.task),
        )
        monitor._prepared = True
        monitor._fill_query_params = Mock(return_value=True)
        monitor._apply_loop_date = Mock()
        with (
            patch("railwatch_bridge.time.time", lambda: self.clock),
            patch("railwatch_bridge.time.monotonic", lambda: self.clock),
            patch("gui_12306_0.time.time", lambda: self.clock),
            patch("gui_12306_0.time.monotonic", lambda: self.clock),
        ):
            self.assertTrue(monitor.wait_for_monitoring_window())
            self.assertGreaterEqual(self.clock, resume)
            self.assertTrue(monitor._query_loop(1, 1.0))

        self.assertEqual(len(self.probes), 2)
        self.assertGreaterEqual(self.probes[1], resume)
        monitor._fill_query_params.assert_not_called()
        self.assertFalse(self.bridge.state.login_ready)
        self.assertTrue(self.task.cancel.is_set())

    def test_monitor_rechecks_login_when_preparation_waits_through_maintenance(self):
        from gui_12306_0 import TicketMonitor

        resume = dt.datetime.fromisoformat("2026-06-11T05:00:00+08:00")
        started_at = dt.datetime.fromisoformat("2026-06-11T00:59:59+08:00").timestamp()
        bridge = self.bridge
        bridge.save_preferences(maintenance_sleep=True)
        bridge._ensure_driver = Mock(return_value=bridge.driver)
        bridge._start_monitor_heartbeat = Mock()
        bridge._prepare_query_page = Mock(return_value=True)
        bridge._make_param_filler = Mock()
        bridge._notify_async = Mock()
        bridge._send_keep_alive = RailWatchBridge._send_keep_alive.__get__(bridge)

        scenarios = (
            (0, "expired", False, 2, False),
            (5, "expired", False, 2, False),
            (5, "ok", False, 2, True),
            (0, "ok", True, 2, False),
            (61, "ok", False, 3, True),
        )
        for seconds_to_target, resume_login, auto_stop, expected_probes, expect_query in scenarios:
            with self.subTest(seconds_to_target=seconds_to_target, resume_login=resume_login, auto_stop=auto_stop):
                target = resume + dt.timedelta(seconds=seconds_to_target)
                config = {
                    "sale_at": target.isoformat(), "timer_enabled": True, "auto_submit": True,
                    "date": "2026-06-25", "from_station_cn": "北京南", "to_station_cn": "上海虹桥",
                    "train_code": "G1", "seat_keyword": "二等座", "passengers": "张三", "keep_alive": False,
                }
                if auto_stop:
                    config["auto_stop_at"] = (resume + dt.timedelta(seconds=1)).isoformat()
                task = MonitorTask(config)
                bridge._task = task
                elapsed = 0.0
                probes = []
                monitors = []

                def advance(seconds):
                    nonlocal elapsed
                    elapsed += seconds

                def now():
                    return started_at + elapsed

                def read_orders(*_args, **_kwargs):
                    self.assertEqual(now(), started_at)
                    advance(2)
                    return []

                def login_result(*_args, **_kwargs):
                    probes.append(now())
                    if now() < resume.timestamp():
                        return "ok"
                    if auto_stop:
                        advance(2)
                    return resume_login

                def make_monitor(*args, **kwargs):
                    monitor = TicketMonitor(*args, **kwargs)
                    monitor._prepared = True
                    monitor.prepare = Mock(return_value=True)
                    monitor._fill_query_params = Mock(return_value=True)
                    monitor._apply_loop_date = Mock()
                    monitor.query_executor = Mock()
                    monitor.query_executor.execute.return_value = {"status": "cancelled"}
                    monitors.append(monitor)
                    return monitor

                task.cancel.wait = advance
                bridge.driver.execute_async_script.side_effect = login_result
                with (
                    patch("railwatch_bridge.time.time", now),
                    patch("railwatch_bridge.time.monotonic", lambda: elapsed),
                    patch("railwatch_bridge.beijing_now", lambda timestamp=None: beijing_now(now() if timestamp is None else timestamp)),
                    patch("railwatch_bridge.guard_browser", return_value=nullcontext()),
                    patch("railwatch_bridge.read_existing_orders", side_effect=read_orders) as read_existing,
                    patch("railwatch_bridge.TicketMonitor", side_effect=make_monitor),
                ):
                    bridge._monitor_worker(config, task)

                read_existing.assert_called_once()
                self.assertEqual(len(probes), expected_probes)
                self.assertEqual(probes[:2], [started_at, resume.timestamp()])
                if expected_probes == 3:
                    self.assertAlmostEqual(probes[2], target.timestamp() - 60, delta=0.25)
                self.assertEqual(len(monitors), 1)
                self.assertEqual(monitors[0].prepare.called, expect_query)
                self.assertEqual(monitors[0].query_executor.execute.called, expect_query, bridge.log_entries[-8:])


if __name__ == "__main__":
    unittest.main()
