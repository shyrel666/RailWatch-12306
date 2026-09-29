import json
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from railwatch_bridge import RailWatchBridge, default_config
from railwatch_orders import OrderJournal
from railwatch_rehearsal import CHECKS, RehearsalRunner, verdict
from railwatch_preferences import load_ui_preferences, save_ui_preferences


class RehearsalRunnerTests(unittest.TestCase):
    def test_timed_rehearsal_requires_clock_evidence_without_claiming_clock_failure(self):
        for timer, clock_status, expected in ((True, "unknown", "risky"), (True, "skipped", "risky"),
                                               (True, "fail", "risky"), (True, "pass", "ready"),
                                               (False, "unknown", "ready")):
            with self.subTest(timer=timer, clock_status=clock_status):
                checks = {key: (lambda *_: {"status": "pass", "summary": "ok"}) for key, _ in CHECKS}
                checks["clock"] = lambda *_: {"status": clock_status, "summary": "clock"}
                with patch("railwatch_rehearsal.sample_scheduler_lateness", return_value={}):
                    report = RehearsalRunner({"timer_enabled": timer}, checks).run()
                self.assertEqual(report["verdict"], expected)
                self.assertFalse(next(c for c in report["checks"] if c["id"] == "clock")["critical"])

    def test_rehearsal_defaults_off_and_preserves_explicit_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(load_ui_preferences(directory)["auto_rehearsal"])
            save_ui_preferences(directory, {"theme": "dark"})
            self.assertFalse(load_ui_preferences(directory)["auto_rehearsal"])
            save_ui_preferences(directory, {"auto_rehearsal": True})
            save_ui_preferences(directory, {"close_to_tray": True})
            self.assertTrue(load_ui_preferences(directory)["auto_rehearsal"])
            save_ui_preferences(directory, {"auto_rehearsal": False})
            self.assertFalse(load_ui_preferences(directory)["auto_rehearsal"])

    def test_dependencies_events_redaction_and_exception(self):
        events, called = [], []
        def check(key):
            def run(*_):
                called.append(key)
                if key == "clock":
                    raise ValueError("秘密姓名和证件号")
                return {"status": "fail" if key == "browser" else "pass", "summary": key}
            return run
        runner = RehearsalRunner({"passengers": "秘密姓名", "auto_submit": True}, {key: check(key) for key, _ in CHECKS}, emit=lambda *e: events.append(e))
        with patch("railwatch_rehearsal.sample_scheduler_lateness", return_value={"p95": 0}):
            report = runner.run()
        self.assertEqual(report["verdict"], "blocked")
        self.assertNotIn("login", called)
        self.assertNotIn("秘密", json.dumps(report, ensure_ascii=False))
        self.assertTrue(all("run_id" not in payload for _, payload in events))
        self.assertEqual([c["id"] for c in report["checks"]], [key for key, _ in CHECKS])
        self.assertEqual(report["checks"][7]["status"], "unknown")

    def test_cancel_and_failed_persistence_return_report(self):
        cancel = threading.Event()
        cancel.set()
        log = Mock()
        with patch("railwatch_rehearsal.sample_scheduler_lateness", return_value={}):
            report = RehearsalRunner({}, {}, save=Mock(side_effect=OSError()), log=log).run(cancel=cancel)
        self.assertEqual(report["verdict"], "cancelled")
        log.assert_called_once()
        self.assertEqual(verdict([{"critical": True, "status": "unknown"}]), "risky")
        self.assertEqual(verdict([{"critical": False, "status": "fail"}]), "risky")

    def test_retention_and_no_order_events(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            for i in range(25):
                journal.save_rehearsal({"rehearsal_id": str(i), "trigger": "manual", "started_at": i,
                                        "finished_at": i + 1, "verdict": "ready"})
            self.assertEqual(len(journal.rehearsal_history()["items"]), 20)
            with journal.connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM orders").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM order_events").fetchone()[0], 0)

    def test_clear_reports_persists_and_preserves_orders_events_and_cooldown(self):
        from railwatch_orders import OrderIntent
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            journal = bridge.order_journal
            config = default_config()
            intent = OrderIntent.from_config(config, "G9", "二等座", "regular")
            journal.begin("test-run", intent, config)
            journal.save_rehearsal({"rehearsal_id": "one", "trigger": "manual", "started_at": 1,
                                    "finished_at": 2, "verdict": "ready"})
            bridge._last_rehearsal_at = time.monotonic()
            cooldown = bridge._last_rehearsal_at
            bridge._browser_busy = True
            with self.assertRaises(RuntimeError):
                bridge.clear_rehearsal_history()
            self.assertEqual(len(journal.rehearsal_history()["items"]), 1)
            bridge._browser_busy = False
            self.assertEqual(bridge.clear_rehearsal_history(), {"cleared": 1})
            self.assertEqual(OrderJournal(journal.filename).rehearsal_history()["items"], [])
            self.assertIsNotNone(journal.pending())
            with journal.connection() as db:
                self.assertGreater(db.execute("SELECT count(*) FROM order_events").fetchone()[0], 0)
            self.assertEqual(bridge._last_rehearsal_at, cooldown)
            bridge.notification_service.close()

    def test_admission_cooldown_and_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            bridge._run_rehearsal = Mock(return_value={"verdict": "ready"})
            config = default_config()
            bridge.rehearse(config)
            with self.assertRaisesRegex(RuntimeError, "冷却"):
                bridge.rehearse(config)
            bridge._last_rehearsal_at = float("-inf")
            bridge.order_journal.pending = Mock(return_value={"pending": True})
            with self.assertRaisesRegex(RuntimeError, "待支付"):
                bridge.rehearse(config)
            bridge.order_journal.pending = Mock(return_value=None)
            from railwatch_dates import beijing_now
            config.update(timer_enabled=True, sale_at=beijing_now(time.time() + 200).isoformat())
            with self.assertRaisesRegex(RuntimeError, "五分钟"):
                bridge.rehearse(config)
            bridge._browser_busy = True
            with self.assertRaises(RuntimeError):
                bridge.rehearse(default_config())
            bridge.notification_service.close()

    def test_shutdown_requests_rehearsal_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            bridge._rehearsal_cancel = threading.Event()
            self.assertTrue(bridge.prepare_shutdown("quit")["ready"])
            self.assertTrue(bridge._rehearsal_cancel.is_set())
            bridge.notification_service.close()

    def test_auto_rehearsal_admission_and_report_binding(self):
        from railwatch_task import MonitorTask
        from railwatch_preferences import save_ui_preferences
        for remaining, enabled, cooldown, expected in [(1800, True, False, True), (900, True, False, False),
                                                       (1800, False, False, False), (1800, None, False, False), (1800, True, True, False)]:
            with self.subTest(remaining=remaining, enabled=enabled, cooldown=cooldown), tempfile.TemporaryDirectory() as directory:
                bridge = RailWatchBridge(directory)
                if enabled is not None:
                    save_ui_preferences(directory, {"auto_rehearsal": enabled})
                bridge.driver = Mock()
                bridge._ensure_driver = Mock(return_value=bridge.driver)
                bridge._start_monitor_heartbeat = Mock()
                bridge._stop_monitor_heartbeat = Mock()
                bridge._make_param_filler = Mock()
                bridge._prepare_query_page = Mock(return_value=False)
                bridge._handle_human_action = Mock(wraps=bridge._handle_human_action)
                bridge._notify_async = Mock()
                bridge._run_rehearsal = Mock(return_value={"verdict": "blocked"})
                if cooldown:
                    bridge._last_rehearsal_at = time.monotonic()
                config = {**default_config(), "timer_enabled": True}
                task = MonitorTask(config, target_timestamp=time.time() + remaining)
                with patch("railwatch_bridge.CORE_AVAILABLE", True), patch("railwatch_bridge.TicketMonitor", Mock()):
                    bridge._monitor_worker(config, task)
                self.assertEqual(bridge._run_rehearsal.called, expected)
                if expected:
                    bridge._run_rehearsal.assert_called_once_with(config, task.cancel, run_id=task.run_id)
                    bridge._handle_human_action.assert_called_once()
                bridge._prepare_query_page.assert_called_once()
                self.assertFalse(task.cancel.is_set())
                self.assertIsNone(bridge._rehearsal_cancel)
                bridge.notification_service.close()

    def test_login_check_updates_only_the_login_flag(self):
        from dataclasses import replace
        from railwatch_rehearsal_checks import make_checks
        from railwatch_state import AppPhase
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            bridge.driver = Mock()
            checks, _ = make_checks(bridge, default_config())
            for answer, ready, status in [("unknown", True, "unknown"), ("expired", False, "fail"), ("ok", True, "pass")]:
                with self.subTest(answer=answer):
                    bridge.state = replace(bridge.state, phase=AppPhase.MONITORING, login_ready=True, error_message="")
                    bridge._verify_login_session = Mock(return_value=answer)
                    self.assertEqual(checks["login"]({}, threading.Event(), None)["status"], status)
                    self.assertEqual((bridge.state.phase, bridge.state.login_ready, bridge.state.error_message),
                                     (AppPhase.MONITORING, ready, ""))
            bridge.notification_service.close()

    def test_cooldown_skip_is_logged_and_task_cancel_is_not_exposed(self):
        from railwatch_task import MonitorTask
        with tempfile.TemporaryDirectory() as directory:
            save_ui_preferences(directory, {"auto_rehearsal": True})
            bridge = RailWatchBridge(directory)
            bridge.driver = Mock()
            bridge._ensure_driver = Mock(return_value=bridge.driver)
            bridge._start_monitor_heartbeat = Mock()
            bridge._prepare_query_page = Mock(return_value=False)
            bridge._last_rehearsal_at = time.monotonic()
            bridge.log = Mock()
            config = {**default_config(), "timer_enabled": True}
            task = MonitorTask(config, target_timestamp=time.time() + 1800)
            with patch("railwatch_bridge.CORE_AVAILABLE", True), patch("railwatch_bridge.TicketMonitor", Mock()):
                bridge._monitor_worker(config, task)
            self.assertTrue(any("跳过自动彩排" in call.args[0] for call in bridge.log.call_args_list))
            seen = []
            bridge._run_rehearsal = Mock(side_effect=lambda *a, **k: seen.append(bridge.cancel_rehearsal()) or {"verdict": "ready"})
            bridge._last_rehearsal_at = float("-inf")
            bridge._task = None
            task = MonitorTask(config, target_timestamp=time.time() + 1800)
            with patch("railwatch_bridge.CORE_AVAILABLE", True), patch("railwatch_bridge.TicketMonitor", Mock()):
                bridge._monitor_worker(config, task)
            self.assertEqual(seen, [{"cancelled": False}])
            self.assertFalse(task.cancel.is_set())
            bridge.notification_service.close()

    def test_stop_during_auto_rehearsal_skips_query_preparation(self):
        from railwatch_task import MonitorTask
        with tempfile.TemporaryDirectory() as directory:
            save_ui_preferences(directory, {"auto_rehearsal": True})
            bridge = RailWatchBridge(directory)
            bridge.driver = Mock()
            bridge._ensure_driver = Mock(return_value=bridge.driver)
            bridge._start_monitor_heartbeat = Mock()
            bridge._stop_monitor_heartbeat = Mock()
            bridge._prepare_query_page = Mock()
            config = {**default_config(), "timer_enabled": True}
            task = MonitorTask(config, target_timestamp=time.time() + 1800)
            def cancel(*args, **kwargs):
                task.cancel.set()
                return {"verdict": "cancelled"}
            bridge._run_rehearsal = Mock(side_effect=cancel)
            with patch("railwatch_bridge.CORE_AVAILABLE", True), patch("railwatch_bridge.TicketMonitor", Mock()):
                bridge._monitor_worker(config, task)
            bridge._prepare_query_page.assert_not_called()
            self.assertTrue(task.done.is_set())
            bridge.notification_service.close()
