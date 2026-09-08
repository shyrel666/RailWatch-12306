"""Regression tests for failure combinations, without a live railway session."""
import tempfile
import unittest
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui_12306_0 import TicketMonitor
from railwatch_bridge import RailWatchBridge
from railwatch_time import ServerTimeSync
from railwatch_task import MonitorTask, TaskCancelled, guard_browser
from railwatch_query import FillResult
from railwatch_dates import beijing_now, eligible_travel_dates, validate_travel_date


class ReliabilityTests(unittest.TestCase):
    def test_failed_fill_never_clicks_query(self):
        monitor = TicketMonitor(
            Mock(), {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-09-10"},
            log_callback=lambda message: None, param_filler=lambda *args: False,
        )
        monitor.click_query_button = Mock(return_value=True)
        monitor.wait_for_rows = Mock(return_value=False)
        with patch("gui_12306_0.time.sleep"):
            monitor._run_single_loop(1, 3)
        monitor.click_query_button.assert_not_called()

    def test_exact_target_second_is_today(self):
        reference = datetime(2026, 9, 6, 8, 30, 0)
        self.assertEqual(ServerTimeSync().parse_target_datetime("08:30:00", reference), reference)

    def test_login_probe_returns_result_before_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge.driver = Mock()
            bridge.driver.execute_async_script.return_value = "expired"
            bridge.notification_service = Mock()
            bridge._send_keep_alive()
            bridge.driver.execute_async_script.assert_called_once()
            self.assertFalse(bridge.state.login_ready)
            self.assertIn("失效", bridge.state.status_message)

    def test_fill_prewarm_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._param_filler = lambda *args: False
            result = bridge._fill_query_page_from_config({
                "from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-09-10",
            })
            self.assertIsNotNone(result)
            self.assertFalse(result)

    def test_initialize_across_target_retains_original_day(self):
        for initialized_time in ("2026-09-06T08:30:01+08:00", "2026-09-06T08:31:00+08:00"):
            with self.subTest(initialized_time=initialized_time), tempfile.TemporaryDirectory() as tmp:
                bridge = RailWatchBridge(tmp)
                requested = datetime.fromisoformat("2026-09-06T08:29:58+08:00").timestamp()
                clock = [requested]
                bridge.server_time_sync = Mock(offset_seconds=0)
                bridge.server_time_sync.parse_target_datetime = ServerTimeSync().parse_target_datetime
                bridge.server_time_sync.server_timestamp = lambda: clock[0]
                def ensure_driver():
                    clock[0] = datetime.fromisoformat(initialized_time).timestamp()
                    return Mock()
                bridge._ensure_driver = ensure_driver
                bridge._check_session_for_task = lambda task: True
                bridge._make_param_filler = lambda driver: lambda *args: FillResult("success")
                bridge._valid_dates = lambda *args, **kwargs: ["2026-09-10"]
                captured = []
                class Monitor:
                    def __init__(self, driver, config, **kwargs): captured.append(config["_target_timestamp"])
                    def run(self): pass
                with patch("railwatch_bridge.time.time", lambda: clock[0]), patch("railwatch_bridge.TicketMonitor", Monitor), patch("railwatch_bridge.CORE_AVAILABLE", True):
                    bridge.start_monitor({"from_station_cn":"北京", "to_station_cn":"上海", "date":"2026-09-10", "timer_enabled":True, "target_time":"08:30:00", "sale_at":"2026-09-06T08:30:00+08:00"})
                    bridge._task.thread.join(2)
                self.assertEqual(captured, [datetime.fromisoformat("2026-09-06T08:30:00+08:00").timestamp()])
                if "08:31" in initialized_time:
                    self.assertTrue(any("普通监控" in row["message"] for row in bridge.log_entries))

    def test_stop_keeps_browser_reserved_until_thread_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            entered, release = threading.Event(), threading.Event()
            def worker(config, task):
                entered.set()
                release.wait(2)
                task.done.set()
            bridge._monitor_worker = worker
            config = {"from_station_cn":"北京", "to_station_cn":"上海", "date":beijing_now().date().isoformat()}
            bridge.start_monitor(config)
            self.assertTrue(entered.wait(1))
            try:
                state = bridge.stop_monitor()
                self.assertEqual(state["task"]["status"], "stopping")
                self.assertTrue(state["monitoring"])
                with self.assertRaises(RuntimeError): bridge.start_monitor(config)
                with self.assertRaises(RuntimeError): bridge.close_browser(confirmed=True)
                with self.assertRaises(RuntimeError): bridge.clear_local_data(confirmed=True)
            finally:
                release.set()
                bridge._task.thread.join(2)
            self.assertFalse(bridge.is_monitoring)

    def test_duplicate_start_and_browser_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._browser_busy = True
            with self.assertRaises(RuntimeError):
                bridge.start_monitor({"from_station_cn":"北京", "to_station_cn":"上海", "date":beijing_now().date().isoformat()})

    def test_old_task_callbacks_and_finalizer_cannot_change_current_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            old, current = MonitorTask({}), MonitorTask({})
            bridge._task = current
            bridge._event_context.run_id = old.run_id
            bridge._handle_progress({"rows":[{"train":"OLD"}]})
            bridge._handle_human_action({"message":"old"})
            bridge._handle_hit({"train_code":"OLD"})
            bridge._monitor_worker({}, old)
            self.assertIs(bridge._task, current)
            self.assertFalse(current.cancel.is_set())
            self.assertEqual(bridge.query_results, [])
            self.assertEqual(bridge.state.hits, ())

    def test_cancellation_interrupts_wait_and_no_keep_alive_after_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._task = MonitorTask({"keep_alive":True})
            bridge._task.cancel.set()
            bridge.driver = Mock()
            bridge._task_wait(bridge._task, 3600)
            self.assertFalse(bridge._wait_for_target_timestamp(10**12, {"keep_alive":True}))
            bridge.driver.execute_async_script.assert_not_called()

    def test_login_unknown_is_not_expired_and_third_failure_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._task = MonitorTask({})
            bridge.driver = Mock()
            bridge.driver.execute_async_script.return_value = "unknown"
            bridge.notification_service = Mock()
            for _ in range(2): bridge._send_keep_alive()
            self.assertFalse(bridge._task.cancel.is_set())
            bridge._send_keep_alive()
            self.assertTrue(bridge._task.cancel.is_set())
            self.assertNotIn("已失效", bridge.state.status_message)
            self.assertIn("无法确认", bridge.state.status_message)
            bridge.notification_service.notify.assert_called_once()

    def test_wait_checks_login_without_repeated_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._task = MonitorTask({})
            bridge.driver = Mock()
            bridge.driver.execute_async_script.side_effect = ["ok", "expired"]
            bridge.notification_service = Mock()
            bridge._prewarm_query_page = Mock(return_value=True)
            bridge.server_time_sync = Mock()
            clock = [1000.0]
            bridge.server_time_sync.server_timestamp = lambda: clock[0]
            bridge._task.cancel.wait = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
            with patch("railwatch_bridge.time.monotonic", lambda: clock[0]), patch("railwatch_bridge.time.time", lambda: clock[0]):
                self.assertFalse(bridge._wait_for_target_timestamp(1180, {"keep_alive":True}))
            self.assertEqual(bridge.driver.execute_async_script.call_count, 2)
            bridge._prewarm_query_page.assert_not_called()
            self.assertIn("失效", bridge.state.status_message)

    def test_date_validation_filters_ranges_in_beijing_time(self):
        today = datetime.fromisoformat("2026-09-06T00:00:00+08:00").date()
        self.assertEqual(eligible_travel_dates("2026-09-06", "±1天", today)[0], ["2026-09-06", "2026-09-07"])
        self.assertEqual(eligible_travel_dates("2026-09-20", "±1天", today)[0], ["2026-09-19", "2026-09-20"])
        self.assertEqual(beijing_now(datetime.fromisoformat("2026-09-05T16:00:00+00:00").timestamp()).date(), today)
        for value in ("2026-02-30", "2026-2-1", "bad-date"):
            with self.assertRaises(ValueError): validate_travel_date(value)

    def test_failed_fill_retries_then_stops_and_recovery_resets_counter(self):
        monitor = TicketMonitor(Mock(), {"from_station_cn":"北京", "to_station_cn":"上海", "date":"2026-09-10"}, log_callback=lambda message: None, param_filler=Mock(side_effect=[False, True, False, False, False]))
        self.assertFalse(monitor._fill_query_params())
        self.assertTrue(monitor._fill_query_params())
        self.assertFalse(monitor._fill_query_params(force=True))
        self.assertFalse(monitor._fill_query_params())
        with self.assertRaises(ValueError): monitor._fill_query_params()

    def test_burst_uses_fixed_target_across_midnight(self):
        target = datetime.fromisoformat("2026-09-07T00:00:00+08:00").timestamp()
        monitor = TicketMonitor(Mock(), {"timer_enabled":True, "_target_timestamp":target, "prepare_time":2}, log_callback=lambda message: None)
        with patch.object(monitor.server_time_sync, "server_timestamp", return_value=target-1):
            self.assertTrue(monitor._is_burst_mode(1))
        with patch.object(monitor.server_time_sync, "server_timestamp", return_value=target+46):
            self.assertFalse(monitor._is_burst_mode(1))

    def test_cancel_blocks_selenium_commands_inside_order_helpers(self):
        task, driver = MonitorTask({}), Mock()
        original = driver.execute
        with guard_browser(driver, task, lambda: None):
            driver.execute("first")
            task.cancel.set()
            with self.assertRaises(TaskCancelled):
                driver.execute("clickElement", {"id":"submitOrder_id"})
        original.assert_called_once_with("first", None)
        self.assertIs(driver.execute, original)

    def test_heartbeat_cancels_but_does_not_release_blocked_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            task = MonitorTask({})
            task.last_tick = 0
            task.done = Mock()
            task.done.is_set.return_value = False
            task.done.wait.return_value = False
            bridge._task = task
            with patch("railwatch_bridge.time.monotonic", return_value=181):
                bridge._start_monitor_heartbeat()
                bridge._monitor_heartbeat_thread.join(1)
            self.assertTrue(task.cancel.is_set())
            self.assertEqual(task.status, "error")
            self.assertTrue(bridge.is_monitoring)


if __name__ == "__main__":
    unittest.main()
