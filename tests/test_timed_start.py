"""Scheduled-start latency and safety, using fake time and isolated state."""
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from gui_12306_0 import TicketMonitor
from railwatch_bridge import RailWatchBridge
from railwatch_orders import OrderJournal
from railwatch_query import QueryExecutor
from railwatch_task import MonitorTask
from railwatch_dates import beijing_now


CONFIG = {"timer_enabled": True, "_target_timestamp": 1000.0, "burst_window_seconds": 45,
          "date": "2026-09-10", "date_range": "±1天", "from_station_cn": "北京",
          "to_station_cn": "上海", "interval": 3, "smart_rate": True, "request_mode": "fast"}


class TimedStartTests(unittest.TestCase):
    def monitor(self, **changes):
        clock = Mock()
        clock.server_timestamp.return_value = 1000.0
        monitor = TicketMonitor(Mock(), {**CONFIG, **changes}, server_time_sync=clock,
                                log_callback=lambda _: None)
        return monitor

    def test_focus_keeps_selected_date_and_snapshot_throughout_sale_window(self):
        monitor = self.monitor()
        for now, loop in ((900, 1), (1000, 2), (1045, 3)):
            monitor.server_time_sync.server_timestamp.return_value = now
            monitor._apply_loop_date(loop)
            self.assertEqual(monitor.cfg["date"], CONFIG["date"])
        monitor.driver.execute_script.assert_called_once()
        monitor.server_time_sync.server_timestamp.return_value = 1046
        monitor._apply_loop_date(4)
        self.assertEqual(monitor.cfg["date"], "2026-09-09")

    def test_expired_target_does_not_silently_buy_another_date(self):
        monitor = self.monitor()
        monitor.date_provider = lambda: ["2026-09-11"]
        with self.assertRaisesRegex(ValueError, "定时目标乘车日期"):
            monitor._apply_loop_date(1)
        monitor.driver.execute_script.assert_not_called()

    def test_untimed_rotation_and_original_order_fallback_are_preserved(self):
        monitor = self.monitor(timer_enabled=False)
        monitor._apply_loop_date(1)
        self.assertEqual(monitor.cfg["date"], "2026-09-09")
        monitor.cfg["timer_enabled"] = True
        monitor._prefer_alternate, monitor._fallback_date = True, "2026-09-11"
        monitor._apply_loop_date(2)
        self.assertEqual(monitor.cfg["date"], "2026-09-11")

    def test_prewarming_fills_once_without_click_and_start_reuses_preparation(self):
        monitor = self.monitor()
        monitor._fill_query_params = Mock(return_value=True)
        monitor.click_query_button = Mock()
        with patch("gui_12306_0.WebDriverWait") as wait:
            self.assertTrue(monitor.prepare())
            monitor.should_stop = lambda: True
            monitor.run()
            self.assertEqual(wait.call_count, 1)
        monitor._fill_query_params.assert_called_once()
        monitor.click_query_button.assert_not_called()

    def test_failed_or_cancelled_preparation_does_not_arm_the_monitor(self):
        monitor = self.monitor()
        monitor._fill_query_params = Mock(return_value=False)
        with patch("gui_12306_0.WebDriverWait"), self.assertRaises(ValueError):
            monitor.prepare()
        self.assertFalse(monitor._prepared)
        monitor.should_stop = lambda: True
        monitor.driver.reset_mock()
        self.assertFalse(monitor.prepare())
        monitor.driver.execute_script.assert_not_called()

    def test_sale_cadence_counts_response_time_but_never_catches_up_in_parallel(self):
        monitor = self.monitor()
        monitor._sleep = Mock()
        monitor._last_query_started = 20
        for now, expected in ((21.2, 1.8), (25, 0)):
            with patch("gui_12306_0.time.monotonic", return_value=now):
                monitor._wait_next_query(3)
            self.assertAlmostEqual(monitor._sleep.call_args.args[0], expected)
        monitor.server_time_sync.server_timestamp.return_value = 1046
        monitor._wait_next_query(3)
        monitor._sleep.assert_called_with(3)

    def test_button_wait_does_not_consume_the_request_interval(self):
        monitor = self.monitor()
        elapsed = [10.0]
        def click():
            elapsed[0] += 5
            return True
        monitor.click_query_button = click
        monitor._sleep = Mock()
        with patch("gui_12306_0.time.monotonic", lambda: elapsed[0]):
            monitor._timed_query_click()
            monitor._wait_next_query(3)
        monitor._sleep.assert_called_once_with(3)

    def test_http_cooldown_is_not_shortened_by_the_sale_cadence(self):
        monitor = self.monitor()
        monitor.query_executor = Mock()
        monitor._fill_query_params = Mock(return_value=True)
        monitor._sleep = Mock()
        monitor._wait_next_query = Mock(side_effect=AssertionError("cooldown bypassed"))
        monitor.query_executor.execute.return_value = {
            "status": "rate_limited", "retry_after_seconds": 120, "reason": "HTTP 429"}
        self.assertFalse(monitor._run_single_loop(1, 3))
        monitor._sleep.assert_called_once_with(120)
        monitor._wait_next_query.assert_not_called()

    def test_scheduler_wake_does_not_commit_and_timestamp_survives_later_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory, event_callback=lambda _: None)
            try:
                bridge._task = MonitorTask({})
                with patch("railwatch_bridge.time.time", return_value=1000), \
                     patch("railwatch_bridge.time.monotonic", return_value=20), \
                     patch.object(bridge.order_journal, "connection", side_effect=AssertionError("disk on deadline")):
                    self.assertTrue(bridge._wait_for_target_timestamp(1000, {}))
                bridge.order_journal.flush_telemetry()
                with bridge.order_journal.connection() as db:
                    self.assertEqual(db.execute("SELECT stage,at,monotonic FROM order_events").fetchall(),
                                     [("scheduler_wake", 1000, 20)])
            finally:
                bridge._task.done.set()
                bridge.notification_service.close()

    def test_small_telemetry_batch_cannot_force_a_deadline_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3", telemetry_batch_size=1)
            with patch.object(journal, "connection", side_effect=AssertionError("disk on deadline")):
                journal.record_telemetry("run", "scheduler_wake")
            journal.flush_telemetry()
            with self.assertRaises(ValueError):
                journal.record_telemetry("run", "regular_submit")


class OvernightWorkerTests(unittest.TestCase):
    def run_worker(self, date_range, *, wake_at="2026-10-04T08:00:00+08:00"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        bridge = RailWatchBridge(directory.name, event_callback=lambda _: None)
        self.addCleanup(bridge.notification_service.close)
        target = datetime.fromisoformat("2026-10-04T08:00:00+08:00").timestamp()
        clock = [datetime.fromisoformat("2026-10-03T23:50:00+08:00").timestamp()]
        config = {**CONFIG, "date": "2026-10-18", "date_range": date_range,
                  "_target_timestamp": target, "sale_at": "2026-10-04T08:00:00+08:00"}
        task = MonitorTask(config, target)
        bridge._task = task
        bridge.driver = Mock()
        bridge.driver.execute_script.return_value = {
            "page": "prepared", "values": ["北京", "BJP", "上海", "SHH", config["date"]]}
        bridge._ensure_driver = Mock(return_value=bridge.driver)
        fill = Mock(return_value=True)
        bridge._make_param_filler = Mock(return_value=fill)
        bridge._prepare_query_page = Mock(return_value=True)
        bridge._start_monitor_heartbeat = Mock()
        bridge.server_time_sync = Mock()
        bridge.server_time_sync.server_timestamp.side_effect = lambda: clock[0]
        monitors, queries = [], []

        def make_monitor(*args, **kwargs):
            monitor = TicketMonitor(*args, **kwargs)
            def query(*_):
                queries.append((clock[0], monitor.cfg["date"]))
                task.cancel.set()
                return {"status": "cancelled"}
            monitor.query_executor.execute = Mock(side_effect=query)
            monitors.append(monitor)
            return monitor

        def wake(*_):
            self.assertEqual(queries, [])
            self.assertTrue(monitors[0]._prepared)
            self.assertEqual(fill.call_args.args[-1], "2026-10-18")
            clock[0] = datetime.fromisoformat(wake_at).timestamp()
            return True

        bridge._wait_for_target_timestamp = Mock(side_effect=wake)
        with patch("railwatch_bridge.time.time", side_effect=lambda: clock[0]), \
             patch("railwatch_bridge.beijing_now", side_effect=lambda stamp=None: beijing_now(clock[0] if stamp is None else stamp)), \
             patch("railwatch_bridge.TicketMonitor", side_effect=make_monitor), \
             patch("gui_12306_0.WebDriverWait"):
            self.assertIn(config["date"], bridge._valid_dates(config, target))
            bridge._monitor_worker(dict(config), task)
        return bridge, task, queries, target

    def test_tomorrow_sale_prepares_and_queries_selected_date_only_at_deadline(self):
        for date_range in ("单日", "±1天"):
            with self.subTest(date_range=date_range):
                bridge, task, queries, target = self.run_worker(date_range)
                bridge._wait_for_target_timestamp.assert_called_once()
                self.assertEqual(queries, [(target, "2026-10-18")])
                self.assertNotEqual(task.status, "error")

    def test_prepared_date_is_revalidated_after_waiting(self):
        bridge, task, queries, _ = self.run_worker("单日", wake_at="2026-10-19T08:00:00+08:00")
        bridge._wait_for_target_timestamp.assert_called_once()
        self.assertEqual(queries, [])
        self.assertEqual(task.status, "error")
        self.assertIn("所有出行日期均无效", bridge.state.status_message)


class QueryArmingTests(unittest.TestCase):
    def test_one_browser_command_arms_before_click_and_still_waits_for_fresh_result(self):
        driver, clicks = Mock(), []
        form = {"page": "one", "values": ["北京", "BJP", "上海", "SHH", "2026-09-10"]}
        driver.execute_script.side_effect = [
            {"form": form, "dialog": {"kind": "none"}, "armed": True},
            {"form": form, "dialog": {"kind": "none"}, "status": {"status": "ok", "revision": 1}},
        ]
        result = QueryExecutor(driver).execute(lambda: clicks.append(driver.execute_script.call_count) or True, 1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(clicks, [1])
        self.assertEqual(driver.execute_script.call_count, 2)

    def test_blockers_incomplete_form_and_cancellation_never_click(self):
        form = {"page": "one", "values": ["北京", "BJP", "上海", "SHH", "2026-09-10"]}
        for armed in (
            {"form": form, "dialog": {"kind": "human_action", "text": "核验"}, "armed": False},
            {"form": {"values": [None] * 5}, "dialog": {"kind": "none"}, "armed": False},
            {"form": form, "dialog": {"kind": "none"}, "armed": False},
        ):
            driver, click = Mock(), Mock()
            driver.execute_script.return_value = armed
            self.assertIn(QueryExecutor(driver).execute(click, 1)["status"], ("human_action", "invalid"))
            click.assert_not_called()
        driver, click = Mock(), Mock()
        self.assertEqual(QueryExecutor(driver, stop_check=lambda: True).execute(click, 1)["status"], "cancelled")
        driver.execute_script.assert_not_called()
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
