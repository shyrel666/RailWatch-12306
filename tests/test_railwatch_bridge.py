import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from scripts.keychain_isolation import isolate_system_keychain

setUpModule = isolate_system_keychain  # These bridges save notification settings and clear local data.


def temp_data_dir(test):
    """A data directory removed after the test, unlike a bare mkdtemp()."""
    directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    test.addCleanup(directory.cleanup)
    return directory.name


class RailWatchBridgeContractTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "DPAPI is available on Windows")
    def test_legacy_secret_migration_failure_preserves_settings_and_allows_startup(self):
        import pywintypes
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "notification_settings.json")
            payload = {"email_enabled": True, "email_password": "legacy-secret"}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            with patch("win32crypt.CryptProtectData", side_effect=pywintypes.error(5, "CryptProtectData", "access denied")):
                bridge = RailWatchBridge(data_dir=temp_dir)
            self.assertFalse(bridge.notification_service.settings["email_enabled"])
            self.assertTrue(any(entry["level"] == "WARN" and "通知设置无法读取" in entry["message"]
                                for entry in bridge.log_entries))
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), payload)

    @unittest.skipUnless(os.name == "nt", "DPAPI is available on Windows")
    def test_secret_encryption_failure_keeps_previous_saved_and_active_settings(self):
        import pywintypes
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir)
            bridge.save_preferences("dark", {"email_password": "previous-secret"})
            path = os.path.join(temp_dir, "notification_settings.json")
            with open(path, "rb") as handle:
                previous = handle.read()
            with patch("win32crypt.CryptProtectData", side_effect=pywintypes.error(5, "CryptProtectData", "access denied")):
                with self.assertRaisesRegex(RuntimeError, "密钥保护失败"):
                    bridge.save_preferences("dark", {"email_password": "new-secret"})
            self.assertEqual(bridge.notification_service.settings["email_password"], "previous-secret")
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), previous)

    @unittest.skipUnless(os.name == "nt", "DPAPI is available on Windows")
    def test_unreadable_notification_secret_does_not_prevent_startup_or_order_recovery(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_orders import OrderIntent, OrderResult

        with tempfile.TemporaryDirectory() as temp_dir:
            original = RailWatchBridge(data_dir=temp_dir)
            intent = OrderIntent("regular", "G101", "2026-09-10", "北京", "上海", "二等座", ("张三",), "18:00")
            original.order_journal.begin("test-run", intent, {})
            original.order_journal.record(intent, OrderResult("pending_payment", order_id="TEST123", evidence={"matched": True}))
            path = os.path.join(temp_dir, "notification_settings.json")
            payload = {"email_enabled": True, "email_password": "dpapi:YWJj"}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            restored = RailWatchBridge(data_dir=temp_dir)
            self.assertFalse(restored.notification_service.settings["email_enabled"])
            self.assertEqual(restored.state.order["order_id"], "TEST123")
            self.assertTrue(restored.state.order["recovery_required"])
            self.assertTrue(any(entry["level"] == "WARN" and "通知设置无法读取" in entry["message"]
                                for entry in restored.log_entries))
            self.assertFalse(restored.load_preferences()["notification_settings"]["email_password_configured"])
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), payload)

    def test_notification_secrets_are_protected_on_disk_and_redacted_from_renderer(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_config_contract import NOTIFICATION_FIELDS, NOTIFICATION_SECRET_FIELDS

        protect = lambda value, slot="": f"protected:{str(value)[::-1]}" if value else ""
        unprotect = lambda value, slot="": str(value).removeprefix("protected:")[::-1]
        # Every secret of the channel table, so a channel added later is covered without editing this test.
        secrets = {field: f"https://secret-{field}.example/hook" if NOTIFICATION_FIELDS[field].get("type") == "url"
                   else f"secret-{field}" for field in NOTIFICATION_SECRET_FIELDS}
        self.assertLessEqual({"server_chan_key", "email_password", "wecom_webhook_url", "bark_key", "ntfy_topic_url", "ntfy_token"},
                             set(secrets))
        # File protection on every system. On macOS secrets go to the keychain instead and
        # the file holds markers, which test_macos_keychain covers with an injected store.
        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("railwatch_bridge.uses_system_keychain", return_value=False), \
            patch("railwatch_bridge.protect_local_secret", side_effect=protect), \
            patch("railwatch_bridge.unprotect_local_secret", side_effect=unprotect):
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            result = bridge.save_preferences("dark", {"server_chan_enabled": True, **secrets})
            with open(os.path.join(temp_dir, "notification_settings.json"), encoding="utf-8") as handle:
                raw = handle.read()
            persisted = json.loads(raw)
            for field, value in secrets.items():
                with self.subTest(field=field):
                    self.assertNotIn(value, raw)
                    self.assertEqual(persisted[field], protect(value, field))
                    self.assertEqual(result["notification_settings"][field], "")
                    self.assertTrue(result["notification_settings"][f"{field}_configured"])

            bridge.save_preferences("dark", {"server_chan_key": ""})
            self.assertEqual(bridge.notification_service.settings["server_chan_key"], secrets["server_chan_key"])
            restored = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            loaded = restored.load_preferences()["notification_settings"]
            for field, value in secrets.items():
                with self.subTest(field=field):
                    self.assertEqual(restored.notification_service.settings[field], value)
                    self.assertEqual(loaded[field], "")
                    self.assertTrue(loaded[f"{field}_configured"])

    def test_default_config_uses_reliability_strategy_and_preserves_trip_defaults(self):
        from railwatch_bridge import default_config

        config = default_config(today=dt.date(2026, 6, 7))

        self.assertEqual(config["from_station_cn"], "北京")
        self.assertEqual(config["to_station_cn"], "上海")
        self.assertEqual(config["date"], "2026-06-08")
        self.assertEqual(config["train_code"], "")
        self.assertEqual(config["seat_keyword"], "")
        self.assertEqual(config["interval"], 6)
        self.assertEqual(config["query_priority"], "reliability")
        self.assertEqual(config["request_mode"], "conservative")
        self.assertEqual(config["passenger_count"], 1)
        self.assertEqual(config["seat_prefer"], "无偏好")
        self.assertEqual(config["prepare_time"], 2)
        self.assertTrue(config["keep_alive"])
        self.assertTrue(config["smart_rate"])
        self.assertFalse(config["timer_enabled"])
        self.assertFalse(config["auto_submit"])
        self.assertFalse(config["auto_alternate"])
        self.assertEqual(config["alternate_deadline"], "开车前1小时")

    def test_validate_config_matches_renderer_form_shape(self):
        from railwatch_bridge import validate_config

        config = validate_config(
            {
                "from_station_cn": "北京 ",
                "to_station_cn": " 上海",
                "date": "2026-06-08",
                "train_code": "g101, g103",
                "seat_keyword": "二等座",
                "interval": "6",
                "auto_submit": True,
                "auto_alternate": False,
                "target_time": "12:30:00",
            }
        )

        self.assertEqual(config["from_station_cn"], "北京")
        self.assertEqual(config["to_station_cn"], "上海")
        self.assertEqual(config["train_code"], "G101, G103")
        self.assertEqual(config["interval"], 6)
        self.assertEqual(config["passenger_count"], 1)
        self.assertEqual(config["target_time"], "12:30:00")

    def test_validate_config_rejects_required_route_fields(self):
        from railwatch_bridge import validate_config

        with self.assertRaisesRegex(ValueError, "出发站为必填项"):
            validate_config({"from_station_cn": "", "to_station_cn": "上海", "date": "2026-06-08"})

        with self.assertRaisesRegex(ValueError, "到达站为必填项"):
            validate_config({"from_station_cn": "北京", "to_station_cn": "", "date": "2026-06-08"})

        with self.assertRaisesRegex(ValueError, "出行日期为必填项"):
            validate_config({"from_station_cn": "北京", "to_station_cn": "上海", "date": ""})

    def test_save_config_persists_renderer_strategy_fields(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)

            saved = bridge.save_config(
                {
                    "from_station_cn": "北京",
                    "to_station_cn": "上海",
                    "date": "2026-06-10",
                    "date_range": "±2天",
                    "interval": 1.5,
                    "prefill_enabled": False,
                    "query_timeout": 25,
                    "smart_rate": False,
                    "timer_enabled": True,
                    "target_time": "08:30:00",
                    "keep_alive": False,
                }
            )

            self.assertEqual(saved["date_range"], "±2天")
            self.assertEqual(saved["interval"], 1.5)
            self.assertFalse(bridge.load_config()["prefill_enabled"])
            self.assertEqual(saved["query_timeout"], 25)
            self.assertFalse(saved["smart_rate"])
            self.assertTrue(saved["timer_enabled"])
            self.assertEqual(saved["target_time"], "08:30:00")

            with open(os.path.join(temp_dir, "user_config.json"), "r", encoding="utf-8") as handle:
                persisted = json.load(handle)

            self.assertEqual(persisted["date_range"], "±2天")
            self.assertEqual(persisted["interval"], 1.5)
            self.assertEqual(persisted["query_timeout"], 25)
            self.assertFalse(persisted["smart_rate"])
            self.assertTrue(persisted["timer_enabled"])
            self.assertEqual(persisted["target_time"], "08:30:00")
            self.assertFalse(persisted["keep_alive"])

    def test_load_config_returns_saved_trip_when_default_query_jobs_exist(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            bridge.save_config(
                {
                    "from_station_cn": "广州",
                    "to_station_cn": "成都",
                    "date": "2026-06-19",
                    "train_code": "G1015",
                    "seat_keyword": "二等座",
                }
            )

            loaded = bridge.load_config()

        self.assertEqual(loaded["from_station_cn"], "广州")
        self.assertEqual(loaded["to_station_cn"], "成都")
        self.assertEqual(loaded["date"], "2026-06-19")
        self.assertEqual(loaded["train_code"], "G1015")
        self.assertEqual(loaded["seat_keyword"], "二等座")

    def test_invalid_saved_trip_keeps_the_draft_accessible(self):
        from railwatch_bridge import RailWatchBridge, default_config

        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            path = bridge.config_manager.config_path
            invalid = {"date_strategy": "unknown-strategy"}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(invalid, handle)
            draft = bridge.save_trip_draft({"from_station_cn": "天津西"}, 1)
            loaded = bridge.load_trip_state()
            self.assertEqual(loaded["draft"]["status"], "available")
            self.assertEqual(loaded["draft"]["draft"], draft)
            self.assertEqual(loaded["saved_config"]["date_strategy"], default_config()["date_strategy"])
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), invalid)

    def test_start_monitor_requires_confirmation_when_dangerous_automation_enabled(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)

        result = bridge.start_monitor(
            {
                "from_station_cn": "北京",
                "to_station_cn": "上海",
                "date": "2026-06-08",
                "auto_submit": True,
                "passengers": "张三",
                "seat_keyword": "二等座",
                "train_code": "G101",
                "auto_alternate": True,
            },
            confirmed=False,
        )

        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["title"], "确认自动化")
        self.assertIn("自动提交", result["message"])
        self.assertIn("自动候补", result["message"])
        self.assertFalse(bridge.is_monitoring)

    def test_start_monitor_matches_shared_automation_readiness_cases_before_browser_work(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_seats import public_seat_capabilities

        path = os.path.join(os.path.dirname(__file__), "fixtures", "automation-readiness-cases.json")
        with open(path, encoding="utf-8") as handle:
            cases = json.load(handle)
        self.assertEqual(cases["capabilities"], public_seat_capabilities())
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(data_dir=directory, event_callback=lambda event: None)
            config = {"from_station_cn": "北京", "to_station_cn": "上海",
                      "date": (dt.date.today() + dt.timedelta(days=7)).isoformat(), **cases["base"]}
            for patch in cases["valid"]:
                with self.subTest(valid=patch):
                    self.assertTrue(bridge.start_monitor({**config, **patch}).get("requires_confirmation"))
            for case in cases["invalid"]:
                with self.subTest(patch=case["patch"]), self.assertRaisesRegex(ValueError, case["expected"]):
                    bridge.start_monitor({**config, **case["patch"]})
            self.assertFalse(bridge.is_monitoring)
            self.assertIsNone(bridge.driver)

    def test_open_login_opens_page_without_marking_login_ready(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.opened_url = ""

            def get(self, url):
                self.opened_url = url

        driver = FakeDriver()
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge._ensure_driver = lambda: driver

        state = bridge.open_login()

        self.assertIn("login.html", driver.opened_url)
        self.assertFalse(state["login_ready"])
        self.assertIn("登录页面已打开", state["status_message"])

    def test_check_login_marks_ready_when_12306_session_is_valid(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def set_script_timeout(self, value): pass
            def execute_async_script(self, script):
                return "ok"

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.driver = FakeDriver()

        state = bridge.check_login()

        self.assertTrue(state["login_ready"])
        self.assertEqual(state["status_message"], "登录已验证")

    def test_check_login_rejects_missing_browser_session(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)

        state = bridge.check_login()

        self.assertFalse(state["login_ready"])
        self.assertIn("请先打开登录页", state["error_message"])

    def test_check_login_uses_async_script_not_sync_script(self):
        from railwatch_bridge import RailWatchBridge

        class PromiseStyleDriver:
            """Mimics WebDriver: execute_script returns the unresolved value, only execute_async_script resolves."""

            def execute_script(self, script):
                return {}

            def set_script_timeout(self, value): pass
            def execute_async_script(self, script):
                return "ok"

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.driver = PromiseStyleDriver()

        state = bridge.check_login()

        self.assertTrue(state["login_ready"])

    def test_login_check_reports_expired_unknown_and_closed_sessions(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_query import LOGIN_CHECK_JS
        from unittest.mock import Mock
        from selenium.common.exceptions import InvalidSessionIdException
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            for reply, expected in [("expired", "未完成或已失效"), ("unknown", "暂时无法确认")]:
                bridge.driver = Mock()
                bridge.driver.execute_async_script.return_value = reply
                state = bridge.check_login()
                self.assertFalse(state["login_ready"])
                self.assertIn(expected, state["status_message"])
                bridge.driver.execute_async_script.assert_called_once_with(LOGIN_CHECK_JS)
                bridge.driver.set_script_timeout.assert_called_once_with(5)
            bridge.driver.execute_async_script.side_effect = InvalidSessionIdException()
            state = bridge.check_login()
            self.assertIn("浏览器已关闭", state["status_message"])
            self.assertIsNone(bridge.driver)

    def test_analyze_query_refuses_while_monitoring(self):
        from railwatch_bridge import RailWatchBridge
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge.is_monitoring = True
            with self.assertRaisesRegex(RuntimeError, "监控运行中"):
                bridge.analyze_query({"from_station_cn":"北京", "to_station_cn":"上海", "date":"2026-06-10"})
            self.assertTrue(bridge.is_monitoring)

    def test_browser_tasks_leave_a_pending_order_page_alone(self):
        from railwatch_bridge import RailWatchBridge
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._ensure_driver = Mock(side_effect=AssertionError("the browser must not be touched"))
            bridge.driver = Mock()
            bridge.order_journal.pending = Mock(return_value={"intent": {"intent_id": "i1"}})
            with self.assertRaisesRegex(RuntimeError, "待支付或待核对订单.*再查询"):
                bridge.analyze_query({"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-06-10"})
            with self.assertRaisesRegex(RuntimeError, "待支付或待核对订单.*再读取乘客"):
                bridge.read_passengers()
            bridge.driver.execute.assert_not_called()
            # The refusal releases the browser reservation, so other work is not blocked afterwards.
            self.assertFalse(bridge._browser_busy)
            bridge.driver = None
            bridge.notification_service.close()

    def test_analyze_query_expands_date_range_and_tags_rows(self):
        from railwatch_bridge import RailWatchBridge

        analyzed_dates = []
        emitted_events = []

        class FakeAnalyzer:
            def __init__(self, driver, log_callback=None, base_dir=None):
                self.driver = driver

            def open_fill_query_and_analyze(self, config):
                analyzed_dates.append(config["date"])
                return [{"train": "G101", "raw": f"G101 {config['date']} 二等座 有"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=emitted_events.append)
            bridge._ensure_driver = lambda: object()

            with patch("railwatch_bridge.PageAnalyzer", FakeAnalyzer), patch("railwatch_bridge.CORE_AVAILABLE", True), patch("railwatch_bridge.beijing_now", return_value=dt.datetime(2026,6,9)):
                result = bridge.analyze_query(
                    {
                        "from_station_cn": "北京",
                        "to_station_cn": "上海",
                        "date": "2026-06-10",
                        "date_range": "±1天",
                    }
                )

        self.assertEqual(analyzed_dates, ["2026-06-09", "2026-06-10", "2026-06-11"])
        self.assertTrue(result["query_ready"])
        self.assertEqual(bridge.query_results[0]["date"], "2026-06-09")
        self.assertEqual(bridge.query_results[2]["date"], "2026-06-11")

    def test_log_export_writes_existing_event_format(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            bridge.log("系统就绪", "INFO")
            bridge.log("登录已过期", "ERROR")

            path = os.path.join(temp_dir, "events.txt")
            result = bridge.export_log(path)

            self.assertEqual(result["path"], path)
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("[INFO] 系统就绪", content)
            self.assertIn("[ERROR] 登录已过期", content)

    def test_bridge_caps_in_memory_logs(self):
        from railwatch_bridge import MAX_LOG_ENTRIES, RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)

        for index in range(MAX_LOG_ENTRIES + 5):
            bridge.log(f"event-{index}")

        self.assertEqual(len(bridge.log_entries), MAX_LOG_ENTRIES)
        self.assertEqual(bridge.log_entries[0]["message"], "event-5")

    def test_clear_local_data_rejects_while_monitoring(self):
        from railwatch_bridge import APP_SLUG, RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = os.path.join(temp_dir, APP_SLUG)
            bridge = RailWatchBridge(data_dir=data_dir, event_callback=lambda event: None)
            bridge.is_monitoring = True

            with self.assertRaisesRegex(RuntimeError, "监控运行中"):
                bridge.clear_local_data(confirmed=True)

    def test_close_browser_rejects_while_monitoring(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.is_monitoring = True
        bridge.driver = object()

        with self.assertRaisesRegex(RuntimeError, "监控运行中"):
            bridge.close_browser(confirmed=True)

    def test_focus_browser_command_can_run_during_order_observation(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_runtime import RailWatchRuntime

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        runtime = RailWatchRuntime(bridge=bridge)
        self.addCleanup(runtime.shutdown)
        bridge.is_monitoring = True
        bridge._observing_intent_id = "pending-order"
        bridge.driver = Mock(current_window_handle="order-tab")
        with ThreadPoolExecutor(max_workers=1) as pool, bridge._driver_lock:
            result = pool.submit(runtime._dispatch, "focusBrowser", {}).result(timeout=3)
        self.assertEqual(result, {"focused": True})
        bridge.driver.switch_to.window.assert_called_once_with("order-tab")
        bridge.driver.execute_cdp_cmd.assert_called_once_with("Page.bringToFront", {})
        bridge.driver.execute_script.assert_not_called()
        self.assertTrue(bridge.is_monitoring)
        self.assertEqual(bridge._observing_intent_id, "pending-order")

    def test_focus_browser_falls_back_to_window_focus(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        bridge.driver = Mock(current_window_handle="verification-tab")
        bridge.driver.execute_cdp_cmd.side_effect = RuntimeError("unsupported CDP command")
        self.assertEqual(bridge.focus_browser(), {"focused": True})
        bridge.driver.switch_to.window.assert_called_once_with("verification-tab")
        bridge.driver.execute_script.assert_called_once_with("window.focus();")

    def test_focus_browser_reports_missing_and_disconnected_sessions(self):
        from railwatch_bridge import RailWatchBridge
        from selenium.common.exceptions import InvalidSessionIdException

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        message = "受控浏览器未打开，请先在系统设置中打开登录页。"
        with self.assertRaisesRegex(RuntimeError, message):
            bridge.focus_browser()
        bridge.driver = Mock(current_window_handle="disconnected-tab")
        bridge.driver.execute_cdp_cmd.side_effect = InvalidSessionIdException("driver-internal-details")
        with self.assertRaisesRegex(RuntimeError, message) as caught:
            bridge.focus_browser()
        bridge.driver.execute_script.assert_not_called()
        self.assertNotIn("driver-internal-details", str(caught.exception))

    def test_focus_browser_waits_for_active_order_probe_and_focuses_restored_tab(self):
        import threading
        from types import SimpleNamespace
        from railwatch_bridge import RailWatchBridge
        from railwatch_order_page import OrderPage
        from railwatch_orders import OrderIntent, OrderResult
        from railwatch_task import MonitorTask, guard_browser

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        task = MonitorTask({})
        probe_in_temp = threading.Event()
        release_probe = threading.Event()
        focus_done = threading.Event()
        focused_handles = []

        class StatefulDriver:
            def __init__(self):
                self.handles = ["payment-tab"]
                self.current_window_handle = "payment-tab"
                self.switch_to = SimpleNamespace(new_window=self.new_window, window=self.switch_window)
                self.closed = []

            @property
            def window_handles(self):
                return list(self.handles)

            def new_window(self, kind):
                assert kind == "tab"
                self.handles.append("probe-tab")
                self.current_window_handle = "probe-tab"

            def switch_window(self, handle):
                assert handle in self.handles
                self.current_window_handle = handle

            def close(self):
                self.closed.append(self.current_window_handle)
                self.handles.remove(self.current_window_handle)
                self.current_window_handle = self.handles[0] if self.handles else ""

            def execute(self, command, params=None):
                return {"value": None}

            def execute_cdp_cmd(self, cmd, params):
                assert cmd == "Page.bringToFront"
                focused_handles.append(self.current_window_handle)

        driver = StatefulDriver()
        bridge.driver = driver
        intent = OrderIntent("regular", "G101", "2026-09-10", "北京", "上海", "二等座", ("张三",))
        page = OrderPage(driver, task.cancel.is_set, lambda _seconds: None)

        def fake_reconcile(*_args, **_kwargs):
            self.assertEqual(driver.current_window_handle, "probe-tab")
            probe_in_temp.set()
            self.assertTrue(release_probe.wait(3))
            # Focusing must not steal the active handle before the temporary tab closes.
            self.assertEqual(driver.current_window_handle, "probe-tab")
            return OrderResult("pending_payment", order_id="E123456", evidence={"matched": True})

        page.reconcile = fake_reconcile
        focus_result = []

        def run_focus():
            focus_result.append(bridge.focus_browser())
            focus_done.set()

        with guard_browser(driver, task, lambda: None, call_lock=bridge._driver_call_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                probe_future = pool.submit(page.probe_known_order, intent, "E123456")
                self.assertTrue(probe_in_temp.wait(3))
                focus_future = pool.submit(run_focus)
                self.assertFalse(focus_done.wait(0.1))
                release_probe.set()
                probe_result = probe_future.result(timeout=3)
                focus_future.result(timeout=3)

        self.assertEqual(probe_result.status, "pending_payment")
        self.assertEqual(driver.closed, ["probe-tab"])
        self.assertEqual(driver.window_handles, ["payment-tab"])
        self.assertEqual(focus_result, [{"focused": True}])
        self.assertEqual(focused_handles, ["payment-tab"])

    def test_focus_browser_serializes_with_release_driver(self):
        import threading
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        quit_started = threading.Event()
        release_quit = threading.Event()
        driver = Mock(current_window_handle="order-tab", service=None)

        def slow_quit():
            quit_started.set()
            self.assertTrue(release_quit.wait(3))

        driver.quit.side_effect = slow_quit
        bridge.driver = driver
        focus_started = threading.Event()

        def run_focus():
            focus_started.set()
            return bridge.focus_browser()

        with ThreadPoolExecutor(max_workers=2) as pool:
            release_future = pool.submit(bridge._release_driver)
            self.assertTrue(quit_started.wait(3))
            focus_future = pool.submit(run_focus)
            self.assertTrue(focus_started.wait(3))
            release_quit.set()
            release_future.result(timeout=3)
            with self.assertRaisesRegex(RuntimeError, "受控浏览器未打开"):
                focus_future.result(timeout=3)

        driver.switch_to.window.assert_not_called()
        driver.execute_cdp_cmd.assert_not_called()

    def test_focus_browser_succeeds_while_guarded_task_is_cancelling(self):
        from types import SimpleNamespace
        from railwatch_bridge import RailWatchBridge
        from railwatch_task import MonitorTask, guard_browser

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        task = MonitorTask({})
        ticks = []
        commands = []

        class GuardedDriver:
            def __init__(self):
                self.switch_to = SimpleNamespace(window=lambda handle: self.execute("switchToWindow", {"handle": handle}))

            @property
            def current_window_handle(self):
                return self.execute("getCurrentWindowHandle")

            def execute_cdp_cmd(self, cmd, params):
                return self.execute("executeCdpCommand", {"cmd": cmd, "params": params})

            def execute(self, command, params=None):
                commands.append((command, params))
                return "order-tab" if command == "getCurrentWindowHandle" else {"value": None}

        driver = GuardedDriver()
        bridge.driver = driver
        with guard_browser(driver, task, lambda: ticks.append(1), call_lock=bridge._driver_call_lock):
            task.cancel.set()
            self.assertEqual(bridge.focus_browser(), {"focused": True})

        self.assertEqual(ticks, [])
        self.assertEqual([cmd for cmd, _ in commands], ["getCurrentWindowHandle", "switchToWindow", "executeCdpCommand"])

    def test_focus_browser_never_lets_background_thread_bypass_lock_or_cancellation(self):
        import threading
        from types import SimpleNamespace
        from railwatch_bridge import RailWatchBridge
        from railwatch_task import MonitorTask, TaskCancelled, guard_browser

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        task = MonitorTask({})
        focus_in_cdp = threading.Event()
        release_focus = threading.Event()
        click_done = threading.Event()
        delivered = []
        active_calls = []

        class GuardedDriver:
            def __init__(self):
                self.switch_to = SimpleNamespace(window=lambda handle: self.execute("switchToWindow", {"handle": handle}))

            @property
            def current_window_handle(self):
                return self.execute("getCurrentWindowHandle")

            def execute_cdp_cmd(self, cmd, params):
                return self.execute("executeCdpCommand", {"cmd": cmd, "params": params})

            def execute(self, command, params=None):
                # No two threads may ever enter raw execute concurrently.
                assert not active_calls, f"concurrent WebDriver call: {active_calls} + {command}"
                active_calls.append(command)
                try:
                    delivered.append(command)
                    if command == "executeCdpCommand":
                        focus_in_cdp.set()
                        assert release_focus.wait(3)
                    return "order-tab" if command == "getCurrentWindowHandle" else {"value": None}
                finally:
                    active_calls.pop()

        driver = GuardedDriver()
        bridge.driver = driver

        def background_click():
            try:
                driver.execute("clickElement", {"id": "submitOrder_id"})
            finally:
                click_done.set()

        with guard_browser(driver, task, lambda: None, call_lock=bridge._driver_call_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                focus_future = pool.submit(bridge.focus_browser)
                self.assertTrue(focus_in_cdp.wait(3))
                task.cancel.set()
                click_future = pool.submit(background_click)
                self.assertFalse(click_done.wait(0.1))
                self.assertNotIn("clickElement", delivered)
                release_focus.set()
                self.assertEqual(focus_future.result(timeout=3), {"focused": True})
                with self.assertRaises(TaskCancelled):
                    click_future.result(timeout=3)

        self.assertNotIn("clickElement", delivered)

    def test_focus_browser_times_out_cleanly_when_driver_lock_stays_busy(self):
        import threading
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        bridge.FOCUS_BROWSER_LOCK_TIMEOUT_SECONDS = 0.05
        bridge.driver = Mock(current_window_handle="order-tab")
        lock_held = threading.Event()
        release_lock = threading.Event()

        def hold_lock():
            with bridge._driver_call_lock:
                lock_held.set()
                release_lock.wait(3)

        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(hold_lock)
            self.assertTrue(lock_held.wait(3))
            try:
                with self.assertRaisesRegex(RuntimeError, "正在执行核对或操作"):
                    bridge.focus_browser()
            finally:
                release_lock.set()
            holder.result(timeout=3)

    def test_probe_known_order_caps_processing_queue_wait_and_closes_temp_tab(self):
        from types import SimpleNamespace
        from railwatch_order_page import OrderPage
        from railwatch_orders import OrderIntent

        clock = [100.0]

        class QueueDriver:
            def __init__(self):
                self.handles = ["payment-tab"]
                self.current_window_handle = "payment-tab"
                self.switch_to = SimpleNamespace(new_window=self.new_window, window=self.switch_window)
                self.closed = []
                self.visited = []

            @property
            def window_handles(self):
                return list(self.handles)

            def new_window(self, kind):
                self.handles.append("probe-tab")
                self.current_window_handle = "probe-tab"

            def switch_window(self, handle):
                self.current_window_handle = handle

            def close(self):
                self.closed.append(self.current_window_handle)
                self.handles.remove(self.current_window_handle)
                self.current_window_handle = self.handles[0] if self.handles else ""

            def get(self, url):
                self.visited.append((self.current_window_handle, url))

        driver = QueueDriver()
        intent = OrderIntent("regular", "G101", "2026-09-10", "北京", "上海", "二等座", ("张三",))
        page = OrderPage(driver, lambda: False, lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        page.RECOVERY_TAB_TIMEOUT = 5.0
        page.PROBE_TAB_MAX_WAIT = 20.0
        page.snapshot = lambda: {
            "url": "https://kyfw.12306.cn/otn/view/train_order.html",
            "processing": True,
            "orders": [],
            "dialogs": [],
            "verification": False,
        }

        with patch("railwatch_order_page.time.monotonic", lambda: clock[0]):
            result = page.probe_known_order(intent, "E123456")

        self.assertEqual(result.status, "unknown")
        self.assertLessEqual(clock[0] - 100.0, 20.5)
        self.assertEqual(driver.closed, ["probe-tab"])
        self.assertEqual(driver.window_handles, ["payment-tab"])
        self.assertEqual(driver.current_window_handle, "payment-tab")

    def test_probe_submitted_alternate_is_not_truncated_by_background_probe_cap(self):
        from types import SimpleNamespace
        from railwatch_order_page import OrderPage
        from railwatch_orders import OrderIntent

        clock = [100.0]

        class SlowCheckoutDriver:
            def __init__(self):
                self.handles = ["checkout-tab"]
                self.current_window_handle = "checkout-tab"
                self.switch_to = SimpleNamespace(new_window=self.new_window, window=self.switch_window)
                self.closed = []
                self.detail_opened = False

            @property
            def window_handles(self):
                return list(self.handles)

            def new_window(self, kind):
                self.handles.append("probe-tab")
                self.current_window_handle = "probe-tab"

            def switch_window(self, handle):
                self.current_window_handle = handle

            def close(self):
                self.closed.append(self.current_window_handle)
                self.handles.remove(self.current_window_handle)
                self.current_window_handle = self.handles[0] if self.handles else ""

            def get(self, url):
                pass

            def execute_script(self, script, *args):
                if "#J-payConfirm" in script:
                    return {"amount": "¥553.0", "rate": "85"}
                if not self.detail_opened:
                    self.detail_opened = True
                    return {
                        "url": "https://kyfw.12306.cn/otn/view/lineUp_order.html",
                        "error": False,
                        "choices": [{"train": "G101", "date": "2026-09-10", "from": "北京", "to": "上海", "seat": "二等座"}],
                        "close": Mock(),
                    }
                return None

        driver = SlowCheckoutDriver()
        intent = OrderIntent("alternate", "G101", "2026-09-10", "北京", "上海", "二等座", ("张三",))
        page = OrderPage(driver, lambda: False, lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        page.RECOVERY_TAB_TIMEOUT = 5.0
        page.PROBE_TAB_MAX_WAIT = 20.0

        def fake_snapshot():
            if driver.current_window_handle == "checkout-tab":
                return {
                    "url": "https://kyfw.12306.cn/otn/view/lineUp_pay.html",
                    "alternateCheckout": True,
                    "dialogs": [],
                    "verification": False,
                    "processing": False,
                    "text": "请在 30 分钟内完成支付",
                }
            # Simulate an official queue taking 25 seconds (longer than the 20s background probe cap).
            if clock[0] < 125.0:
                return {
                    "url": "https://kyfw.12306.cn/otn/view/lineUp_order.html",
                    "processing": True,
                    "orders": [],
                    "dialogs": [],
                    "verification": False,
                }
            return {
                "url": "https://kyfw.12306.cn/otn/view/lineUp_order.html",
                "processing": False,
                "dialogs": [],
                "verification": False,
                "orders": [{
                    "kind": "alternate",
                    "order_id": "E888888",
                    "state": "待支付",
                    "passengers": ["张三"],
                    "choices": [{"train": "G101", "date": "2026-09-10", "from": "北京", "to": "上海", "seat": "二等座"}],
                    "detail_button": Mock(),
                    "text": "E888888 待支付 G101 2026-09-10 北京 上海 二等座 张三",
                }],
            }

        page.snapshot = fake_snapshot
        with patch("railwatch_order_page.time.monotonic", lambda: clock[0]):
            result = page.probe_submitted_alternate(intent)

        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(result.order_id, "E888888")
        self.assertGreaterEqual(clock[0] - 100.0, 25.0)
        self.assertEqual(driver.closed, ["probe-tab"])
        self.assertEqual(driver.current_window_handle, "checkout-tab")

    def test_wait_for_target_time_sends_keep_alive_when_enabled(self):
        from railwatch_bridge import RailWatchBridge
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge.driver = Mock()
            bridge.driver.execute_async_script.return_value = "ok"
            bridge.is_monitoring = True
            clock = [1000.0]
            bridge.server_time_sync = Mock()
            bridge.server_time_sync.server_timestamp = lambda: clock[0]
            bridge._prewarm_query_page = Mock(return_value=True)
            bridge._task.cancel.wait = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
            with patch("railwatch_bridge.time.monotonic", lambda: clock[0]), patch("railwatch_bridge.time.time", lambda: clock[0]):
                bridge._wait_for_target_timestamp(1080, {"keep_alive":True})
            self.assertEqual(bridge.driver.execute_async_script.call_count, 1)

    def test_auto_stop_before_scheduled_sale_waits_only_until_deadline_without_browser(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_time import MONITOR_AUTO_STOP_MESSAGE, MONITOR_AUTO_STOP_TITLE

        events = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)
        bridge.is_monitoring = True
        bridge._ensure_driver = Mock()
        bridge._send_keep_alive = Mock()
        auto_stop = dt.datetime.fromisoformat("2026-06-10T08:00:00+08:00")
        bridge._task.cancel.wait = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        clock = [auto_stop.timestamp() - 1]
        config = {"timer_enabled": True, "sale_at": "2026-06-10T08:30:00+08:00",
                  "auto_stop_at": auto_stop.isoformat(), "auto_submit": True, "keep_alive": True}
        with patch("railwatch_bridge.time.time", lambda: clock[0]), patch("railwatch_bridge.time.monotonic", lambda: clock[0]):
            bridge._monitor_worker(config)
        self.assertEqual(clock[0], auto_stop.timestamp())
        bridge._ensure_driver.assert_not_called()
        bridge._send_keep_alive.assert_not_called()
        self.assertEqual([entry["message"] for entry in bridge.log_entries].count(MONITOR_AUTO_STOP_MESSAGE), 1)
        notices = [event["payload"] for event in events if event["event"] == "notify"]
        self.assertEqual([(note["title"], note["message"], note["priority"]) for note in notices],
                         [(MONITOR_AUTO_STOP_TITLE, MONITOR_AUTO_STOP_MESSAGE, "notice")])

    def test_auto_stop_at_sale_waits_for_wall_time_when_monotonic_is_ahead(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_time import MONITOR_AUTO_STOP_MESSAGE, MONITOR_AUTO_STOP_TITLE

        events = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)
        bridge.is_monitoring = True
        task = bridge._task
        scheduled = dt.datetime.fromisoformat("2026-06-10T08:00:00+08:00")
        wall = scheduled.timestamp() - 0.015625
        monotonic = 100.0
        wait_calls = []

        def wait(seconds):
            nonlocal wall, monotonic
            if not wait_calls:
                # The monotonic projection reaches the deadline while the wall clock still lags.
                wall += seconds - 0.00390625
                monotonic += seconds + 0.00390625
            else:
                wall += seconds
                monotonic += seconds
            wait_calls.append(seconds)

        task.cancel.wait = wait
        with patch("railwatch_bridge.time.time", lambda: wall), patch("railwatch_bridge.time.monotonic", lambda: monotonic), \
                patch.object(bridge, "_ensure_driver") as ensure, \
                patch.object(bridge.order_journal, "record_telemetry") as telemetry:
            bridge._monitor_worker({"timer_enabled": True, "sale_at": scheduled.isoformat(),
                                    "auto_stop_at": scheduled.isoformat()})

        self.assertEqual(wall, scheduled.timestamp())
        self.assertEqual(len(wait_calls), 2)
        ensure.assert_not_called()
        telemetry.assert_not_called()
        self.assertEqual([entry["message"] for entry in bridge.log_entries].count(MONITOR_AUTO_STOP_MESSAGE), 1)
        self.assertEqual([(event["payload"]["title"], event["payload"]["priority"])
                          for event in events if event["event"] == "notify"], [(MONITOR_AUTO_STOP_TITLE, "notice")])

    def test_monitor_startup_at_0200_delays_browser_and_automation_checks_until_0500(self):
        from railwatch_bridge import RailWatchBridge

        events = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)
        bridge.save_preferences(maintenance_sleep=True)
        bridge.is_monitoring = True
        task = bridge._task
        start = dt.datetime.fromisoformat("2026-06-10T02:00:00+08:00")
        resume = start.replace(hour=5).timestamp()
        wall = start.timestamp()
        wait_calls = []
        browser_calls = []

        def wait(seconds):
            nonlocal wall
            wait_calls.append((seconds, task.last_tick))
            wall += seconds

        def record(name, result):
            def invoke(*args):
                browser_calls.append((name, wall))
                return result
            return Mock(side_effect=invoke)

        task.cancel.wait = wait
        bridge._ensure_driver = record("driver", Mock())
        bridge._make_param_filler = Mock()
        bridge._prepare_query_page = record("query_page", True)
        bridge._send_keep_alive = record("login", "ok")
        bridge._existing_trip_blocks = record("existing_order", True)
        with patch("railwatch_bridge.time.time", lambda: wall), patch("railwatch_bridge.time.monotonic", lambda: wall):
            bridge._monitor_worker({"auto_submit": True, "maintenance_sleep": False})

        self.assertTrue(wait_calls)
        self.assertTrue(all(0 < seconds <= 30 for seconds, _ in wait_calls))
        self.assertEqual(wait_calls[0][1], start.timestamp())
        self.assertGreater(wait_calls[-1][1], wait_calls[0][1])
        self.assertEqual(browser_calls, [(name, resume) for name in ("driver", "query_page", "login", "existing_order")])
        waiting = [event["payload"] for event in events if event["event"] == "state"
                   and event["payload"].get("status_message") == "12306 夜间维护休眠中，05:00 恢复"]
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["task"]["next_query_at"], resume)

    def test_maintenance_startup_cancellation_or_earlier_auto_stop_skips_browser(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_time import MONITOR_AUTO_STOP_MESSAGE

        start = dt.datetime.fromisoformat("2026-06-10T02:00:00+08:00")
        stop = start + dt.timedelta(seconds=45)
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                events = []
                bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)
                bridge.save_preferences(maintenance_sleep=True)
                bridge.is_monitoring = True
                task = bridge._task
                wall = start.timestamp()
                wait_calls = []

                def wait(seconds):
                    nonlocal wall
                    wall += seconds
                    wait_calls.append(seconds)
                    if cancel:
                        task.cancel.set()

                task.cancel.wait = wait
                with patch("railwatch_bridge.time.time", lambda: wall), patch("railwatch_bridge.time.monotonic", lambda: wall), \
                        patch.object(bridge, "_ensure_driver") as ensure:
                    bridge._monitor_worker({"auto_submit": True, "auto_stop_at": stop.isoformat()})

                ensure.assert_not_called()
                self.assertEqual(wait_calls, [30.0] if cancel else [30.0, 15.0])
                self.assertEqual([entry["message"] for entry in bridge.log_entries].count(MONITOR_AUTO_STOP_MESSAGE),
                                 0 if cancel else 1)
                self.assertEqual([event["payload"]["priority"] for event in events if event["event"] == "notify"],
                                 [] if cancel else ["notice"])

    def test_monitor_default_ignores_legacy_maintenance_setting(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        bridge.is_monitoring = True
        now = dt.datetime.fromisoformat("2026-06-10T02:00:00+08:00").timestamp()
        bridge._ensure_driver = Mock()
        bridge._make_param_filler = Mock()
        bridge._prepare_query_page = Mock(return_value=False)
        with patch("railwatch_bridge.time.time", return_value=now), patch.object(bridge, "_wait_until_wall_time") as wait:
            bridge._monitor_worker({"maintenance_sleep": True})

        bridge._ensure_driver.assert_called_once()
        wait.assert_not_called()
        self.assertNotIn("maintenance_sleep", bridge._task.config)

    def test_monitor_freezes_global_maintenance_for_timer_prefill_and_polling(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_preferences import load_ui_preferences, save_ui_preferences

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        bridge.save_preferences(maintenance_sleep=True)
        bridge.is_monitoring = True
        now = dt.datetime.fromisoformat("2026-11-24T23:29:00+08:00").timestamp()
        trip = {"date": "2026-11-26", "timer_enabled": True, "sale_at": "2026-11-24T23:35:00+08:00"}

        def launch():
            save_ui_preferences(bridge.data_dir, {"maintenance_sleep": False})
            return Mock()

        bridge._ensure_driver = Mock(side_effect=launch)
        bridge._make_param_filler = Mock()
        bridge._prepare_query_page = Mock(return_value=True)
        bridge._existing_trip_blocks = Mock(return_value=False)
        bridge._wait_for_target_time = Mock(return_value=True)
        monitor = Mock()
        with (
            patch("railwatch_bridge.time.time", return_value=now),
            patch("railwatch_bridge.load_ui_preferences", wraps=load_ui_preferences) as load,
            patch("railwatch_bridge.TicketMonitor", return_value=monitor) as create,
            patch("railwatch_bridge.prefill_eligible_reason", return_value=None),
            patch("railwatch_bridge.PrefillAdapter") as prefill,
        ):
            bridge._monitor_worker(trip)

        load.assert_called_once_with(bridge.data_dir)
        self.assertFalse(load_ui_preferences(bridge.data_dir)["maintenance_sleep"])
        self.assertNotIn("maintenance_sleep", trip)
        self.assertNotIn("maintenance_sleep", bridge._task.config)
        self.assertIs(create.call_args.args[1]["maintenance_sleep"], True)
        self.assertIs(bridge._wait_for_target_time.call_args.args[0]["maintenance_sleep"], True)
        prefill.assert_not_called()
        monitor.wait_for_monitoring_window.assert_called_once()
        monitor.run.assert_called_once()

    def test_maintenance_sleep_skips_prefill_when_presale_window_falls_in_maintenance(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_time import maintenance_resume_timestamp

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        bridge.save_preferences(maintenance_sleep=True)
        bridge.is_monitoring = True
        # Thursday 00:50 and 05:00 are both outside maintenance, while 04:59 (T-60) is inside it.
        now = dt.datetime.fromisoformat("2026-06-11T00:50:00+08:00").timestamp()
        sale = dt.datetime.fromisoformat("2026-06-11T05:00:00+08:00").timestamp()
        self.assertIsNone(maintenance_resume_timestamp(now))
        self.assertIsNone(maintenance_resume_timestamp(sale))
        self.assertIsNotNone(maintenance_resume_timestamp(sale - 60))
        trip = {
            "date": "2026-06-25",
            "timer_enabled": True,
            "auto_submit": True,
            "sale_at": "2026-06-11T05:00:00+08:00",
        }
        bridge._ensure_driver = Mock(return_value=Mock())
        bridge._make_param_filler = Mock()
        bridge._prepare_query_page = Mock(return_value=True)
        bridge._send_keep_alive = Mock(return_value="ok")
        bridge._existing_trip_blocks = Mock(return_value=False)
        bridge._wait_for_target_time = Mock(return_value=True)
        monitor = Mock()
        with (
            patch("railwatch_bridge.time.time", return_value=now),
            patch("railwatch_bridge.TicketMonitor", return_value=monitor),
            patch("railwatch_bridge.prefill_eligible_reason", return_value=None),
            patch("railwatch_bridge.PrefillAdapter") as prefill,
        ):
            bridge._monitor_worker(trip)

        prefill.assert_not_called()
        self.assertEqual(bridge.state.prefill_notice, "起售时间处于夜间维护休眠时段")
        monitor.run.assert_called_once()

    def test_monitor_date_window_preserves_custom_date_order(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=temp_data_dir(self))
        now = dt.datetime.fromisoformat("2026-06-10T08:00:00+08:00").timestamp()
        config = {"date": "2026-06-12", "date_range": "自定义",
                  "custom_dates": ["2026-06-20", "2026-06-09", "2026-06-12", "2026-06-30"]}
        self.assertEqual(bridge._valid_dates(config, now, announce=True), ["2026-06-20", "2026-06-12"])
        self.assertEqual([entry["message"] for entry in bridge.log_entries],
                         ["跳过 2026-06-09：已过期", "跳过 2026-06-30：超出可查询窗口"])

    def test_wait_for_target_time_skips_keep_alive_when_disabled(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.keep_alive_calls = 0

            def execute_script(self, script):
                self.keep_alive_calls += 1

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.is_monitoring = True

        with patch.object(bridge.server_time_sync, "server_timestamp", side_effect=[0, 61, 62]), patch(
            "railwatch_bridge.time.sleep", lambda seconds: None
        ):
            bridge._wait_for_target_timestamp(62, {"keep_alive": False})

        self.assertEqual(bridge.driver.keep_alive_calls, 0)

    def test_monitor_worker_skips_late_prewarm_after_timer_wait(self):
        from railwatch_bridge import RailWatchBridge

        created_kwargs = []

        class FakeMonitor:
            def __init__(self, *args, **kwargs):
                created_kwargs.append(kwargs)

            def prepare(self):
                return True

            def run(self):
                return None

        class FakeResolver:
            def load(self):
                return {}

        class FakeAnalyzer:
            def __init__(self, driver, log_callback=None, base_dir=None):
                self.resolver = FakeResolver()

            def fill_query_form(self, from_cn, to_cn, date, timeout=10):
                return True

        prewarm_calls = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.is_monitoring = True
        bridge.server_time_sync.sync = lambda force=False: 0
        bridge._wait_for_target_time = lambda config: True
        bridge._ensure_driver = lambda: Mock()
        bridge._prewarm_query_page = lambda driver, config: prewarm_calls.append((driver, config))
        bridge._valid_dates = lambda *args, **kwargs: ["2026-06-10"]
        bridge._prepare_query_page = lambda *args: True
        bridge._start_monitor_heartbeat = lambda: None
        bridge._stop_monitor_heartbeat = lambda: None

        with patch("railwatch_bridge.CORE_AVAILABLE", True), patch(
            "railwatch_bridge.TicketMonitor", FakeMonitor
        ), patch("railwatch_bridge.PageAnalyzer", FakeAnalyzer):
            bridge._monitor_worker({"timer_enabled": True, "target_time":"08:30:00", "sale_at":"2026-06-10T08:30:00+08:00"})

        self.assertEqual(prewarm_calls, [])
        # 定时路径必须把填参回调传给监控核心（开抢前预热时同步查询参数）
        self.assertIsNotNone(created_kwargs[0].get("param_filler"))

    def test_monitor_worker_ensures_driver_before_timer_wait(self):
        # 定时模式要先创建浏览器再等待，否则等待期无法保活/预热，开抢瞬间是冷启动
        from railwatch_bridge import RailWatchBridge

        order = []

        class FakeMonitor:
            def __init__(self, *args, **kwargs):
                order.append("create_monitor")

            def prepare(self):
                order.append("prepare_monitor")
                return True

            def run(self):
                order.append("monitor")

        class FakeResolver:
            def load(self):
                return {}

        class FakeAnalyzer:
            def __init__(self, driver, log_callback=None, base_dir=None):
                self.resolver = FakeResolver()

            def fill_query_form(self, from_cn, to_cn, date, timeout=10):
                return True

        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.is_monitoring = True
        bridge.server_time_sync.sync = lambda force=False: 0
        bridge._wait_for_target_time = lambda config: order.append("wait") or True
        bridge._ensure_driver = lambda: order.append("driver") or Mock()
        bridge._valid_dates = lambda *args, **kwargs: ["2026-06-10"]
        bridge._prepare_query_page = lambda *args: True
        bridge._start_monitor_heartbeat = lambda: None
        bridge._stop_monitor_heartbeat = lambda: None

        with patch("railwatch_bridge.CORE_AVAILABLE", True), patch(
            "railwatch_bridge.TicketMonitor", FakeMonitor
        ), patch("railwatch_bridge.PageAnalyzer", FakeAnalyzer):
            bridge._monitor_worker({"timer_enabled": True, "target_time":"08:30:00", "sale_at":"2026-06-10T08:30:00+08:00"})

        self.assertEqual(order, ["driver", "create_monitor", "prepare_monitor", "wait", "monitor"])

    def test_prewarm_query_page_navigates_and_syncs_params(self):
        from railwatch_bridge import QUERY_URL, RailWatchBridge

        class Driver:
            def __init__(self):
                self.opened = []

            def get(self, url):
                self.opened.append(url)

        fills = []
        driver = Driver()
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge._param_filler = lambda from_cn, to_cn, date: fills.append((from_cn, to_cn, date)) or True

        bridge._prewarm_query_page(
            driver,
            {"from_station_cn": "北京", "to_station_cn": "上海", "date": "2026-06-10"},
        )

        self.assertEqual(driver.opened, [QUERY_URL])
        self.assertEqual(fills, [("北京", "上海", "2026-06-10")])

    def test_fill_query_page_from_config_skips_incomplete_config(self):
        from railwatch_bridge import RailWatchBridge

        fills = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge._param_filler = lambda from_cn, to_cn, date: fills.append((from_cn, to_cn, date)) or True

        bridge._fill_query_page_from_config({"date": "2026-06-10"})
        bridge._fill_query_page_from_config({"from_station_cn": "北京", "to_station_cn": "上海"})

        self.assertEqual(fills, [])

    def test_keep_alive_warns_once_when_login_expired(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def set_script_timeout(self, value): pass
            def execute_async_script(self, script): return "expired"

        events = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)
        bridge.driver = FakeDriver()
        bridge.notification_service = Mock()

        bridge._send_keep_alive()
        bridge._send_keep_alive()

        warns = [
            event
            for event in events
            if event["event"] == "log" and event["payload"]["level"] == "WARN" and "登录" in event["payload"]["message"]
        ]
        self.assertEqual(len(warns), 1)

    def test_get_runtime_info_includes_live_system_facts(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            info = bridge.get_runtime_info()

        self.assertEqual(info["data_dir"], temp_dir)
        self.assertIn("app_version", info)
        self.assertTrue(info["data_dir_writable"])
        self.assertGreater(info["data_dir_free_bytes"], 0)
        self.assertIn("network_label", info)
        self.assertIn("railway_label", info)
        self.assertIn("proxy_label", info)

    def test_get_runtime_info_nonblocking_returns_immediately_and_emits_labels(self):
        import threading
        import time
        from railwatch_bridge import RailWatchBridge

        probe_started = threading.Event()
        release_probe = threading.Event()
        probe_calls = 0
        chrome_calls = 0
        emitted = []

        def fake_probe():
            nonlocal probe_calls
            probe_calls += 1
            probe_started.set()
            release_probe.wait(timeout=5)
            return {
                "network_ok": True,
                "network_label": "正常",
                "railway_ok": True,
                "railway_label": "正常",
                "proxy_configured": False,
                "proxy_label": "未配置",
                "proxy_value": "",
            }

        def fake_chrome_info():
            nonlocal chrome_calls
            chrome_calls += 1
            return "Chrome 137"

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("railwatch_bridge.probe_connectivity", side_effect=fake_probe), \
            patch("railwatch_bridge.get_chrome_version_info", side_effect=fake_chrome_info):
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=emitted.append)
            t0 = time.monotonic()
            initial = bridge.get_runtime_info(probe=False)
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 0.5)
            self.assertEqual(initial["network_label"], "检测中")
            self.assertEqual(initial["railway_label"], "检测中")
            self.assertIs(initial["connectivity_pending"], True)
            self.assertEqual(initial["chrome_version"], "Chrome 137")
            self.assertTrue(probe_started.wait(timeout=2))
            # Repeated probe=False while inflight reuses single background probe.
            second = bridge.get_runtime_info(probe=False)
            self.assertEqual(second["network_label"], "检测中")
            release_probe.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(ev.get("event") == "labels" for ev in emitted):
                    break
                time.sleep(0.01)

            labels_events = [ev["payload"] for ev in emitted if ev.get("event") == "labels"]
            self.assertEqual(len(labels_events), 1)
            self.assertTrue(labels_events[0]["network_ok"])
            self.assertEqual(labels_events[0]["network_label"], "正常")
            self.assertIs(labels_events[0]["connectivity_pending"], False)
            self.assertEqual(probe_calls, 1)

            cached = bridge.get_runtime_info(probe=False)
            self.assertEqual(cached["network_label"], "正常")
            self.assertIs(cached["connectivity_pending"], False)
            self.assertEqual(probe_calls, 1)
            self.assertEqual(chrome_calls, 1)

            forced = bridge.get_runtime_info(probe=True, force=True)
            self.assertEqual(forced["network_label"], "正常")
            self.assertEqual(probe_calls, 2)
            self.assertEqual(chrome_calls, 2)

    def test_connectivity_cache_ttl_stays_below_polling_interval(self):
        import threading
        import time
        from railwatch_bridge import CONNECTIVITY_CACHE_TTL_SECONDS, RailWatchBridge

        self.assertLess(CONNECTIVITY_CACHE_TTL_SECONDS, 180.0)

        probe_calls = 0
        second_probe_done = threading.Event()
        emitted = []

        def fake_probe():
            nonlocal probe_calls
            probe_calls += 1
            if probe_calls >= 2:
                second_probe_done.set()
            return {
                "network_ok": True,
                "network_label": "正常",
                "railway_ok": True,
                "railway_label": "正常",
                "proxy_configured": False,
                "proxy_label": "未配置",
                "proxy_value": "",
            }

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("railwatch_bridge.probe_connectivity", side_effect=fake_probe), \
            patch("railwatch_bridge.get_chrome_version_info", return_value="Chrome 137"):
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=emitted.append)
            bridge.get_runtime_info(probe=True)
            self.assertEqual(probe_calls, 1)

            # Simulate 180s poll interval after a ~5s initial probe (~175s since completion).
            with bridge._runtime_cache_lock:
                cached_at, cached_val = bridge._connectivity_cache
                bridge._connectivity_cache = (cached_at - 175.0, cached_val)

            polled = bridge.get_runtime_info(probe=False)
            self.assertEqual(polled["network_label"], "正常")
            self.assertTrue(second_probe_done.wait(timeout=2))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(ev.get("event") == "labels" for ev in emitted):
                    break
                time.sleep(0.01)
            self.assertEqual(probe_calls, 2)
            self.assertTrue(any(ev.get("event") == "labels" for ev in emitted))

    def test_runtime_forwards_get_runtime_info_probe_and_force_flags(self):
        from railwatch_runtime import RailWatchRuntime

        bridge = Mock()
        bridge.get_runtime_info.return_value = {"app": "RailWatch 12306"}
        runtime = RailWatchRuntime(bridge=bridge, writer=lambda payload: None)
        try:
            runtime.handle_line('{"id":"1","command":"getRuntimeInfo","payload":{"probe":false,"force":true}}').result(timeout=5)
            bridge.get_runtime_info.assert_called_once_with(probe=False, force=True)
        finally:
            runtime.shutdown()

    def test_clear_local_data_invalidates_runtime_caches_and_discards_inflight_probe(self):
        import threading
        import time
        from railwatch_bridge import RailWatchBridge

        probe_started = threading.Event()
        release_probe = threading.Event()
        emitted = []
        calls = 0

        def fake_probe():
            nonlocal calls
            calls += 1
            if calls == 1:
                probe_started.set()
                release_probe.wait(timeout=5)
                return {
                    "network_ok": False,
                    "network_label": "异常",
                    "railway_ok": False,
                    "railway_label": "异常",
                    "proxy_configured": False,
                    "proxy_label": "未配置",
                    "proxy_value": "",
                }
            return {
                "network_ok": True,
                "network_label": "正常",
                "railway_ok": True,
                "railway_label": "正常",
                "proxy_configured": False,
                "proxy_label": "未配置",
                "proxy_value": "",
            }

        from railwatch_state import APP_SLUG

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("railwatch_bridge.probe_connectivity", side_effect=fake_probe):
            data_dir = os.path.join(os.path.realpath(temp_dir), APP_SLUG)
            bridge = RailWatchBridge(data_dir=data_dir, event_callback=emitted.append)
            bridge.get_runtime_info(probe=False)
            self.assertTrue(probe_started.wait(timeout=2))

            bridge.clear_local_data(confirmed=True)
            release_probe.set()
            time.sleep(0.05)

            self.assertFalse(any(ev.get("event") == "labels" for ev in emitted))
            refreshed = bridge.get_runtime_info(probe=True)
            self.assertTrue(refreshed["network_ok"])
            self.assertEqual(refreshed["network_label"], "正常")

    def test_json_runtime_dispatches_command_response_and_events(self):
        from railwatch_runtime import RailWatchRuntime

        bridge = Mock()
        bridge.get_runtime_info.return_value = {"app": "RailWatch 12306"}
        emitted = []
        runtime = RailWatchRuntime(bridge=bridge, writer=lambda payload: emitted.append(payload))

        runtime.handle_line('{"id":"1","command":"getRuntimeInfo","payload":{}}').result(timeout=5)

        self.assertEqual(
            emitted,
            [
                {
                    "type": "response",
                    "id": "1",
                    "ok": True,
                    "result": {"app": "RailWatch 12306"},
                }
            ],
        )

    def test_json_runtime_dispatches_check_login(self):
        from railwatch_runtime import RailWatchRuntime

        bridge = Mock()
        bridge.check_login.return_value = {"login_ready": True}
        emitted = []
        runtime = RailWatchRuntime(bridge=bridge, writer=lambda payload: emitted.append(payload))

        runtime.handle_line('{"id":"1","command":"checkLogin","payload":{}}').result(timeout=5)

        self.assertEqual(emitted[0]["result"], {"login_ready": True})
        bridge.check_login.assert_called_once_with()

    def test_runtime_does_not_block_fast_command_behind_slow_command(self):
        import threading

        from railwatch_runtime import RailWatchRuntime

        slow_started = threading.Event()
        release_slow = threading.Event()
        order = []
        order_lock = threading.Lock()

        class SlowBridge:
            def check_environment(self):
                slow_started.set()
                release_slow.wait(timeout=5)
                return {"slow": True}

            def get_runtime_info(self):
                return {"fast": True}

        def writer(payload):
            with order_lock:
                order.append(payload["id"])

        runtime = RailWatchRuntime(bridge=SlowBridge(), writer=writer)

        slow_future = runtime.handle_line('{"id":"slow","command":"checkEnvironment","payload":{}}')
        self.assertTrue(slow_started.wait(timeout=5))

        fast_future = runtime.handle_line('{"id":"fast","command":"getRuntimeInfo","payload":{}}')
        fast_future.result(timeout=5)

        self.assertEqual(order, ["fast"])
        release_slow.set()
        slow_future.result(timeout=5)
        runtime.shutdown()
        self.assertEqual(order, ["fast", "slow"])

    def test_check_login_records_device_id_after_verified_login(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def set_script_timeout(self, value): pass
            def execute_async_script(self, script):
                return "ok"

        class FakeDeviceIdTracker:
            def __init__(self):
                self.saved = False

            def save_device_id(self):
                self.saved = True
                return True

        tracker = FakeDeviceIdTracker()
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.device_id_protector = tracker

        bridge.check_login()

        self.assertTrue(tracker.saved)

    def test_keep_alive_checks_device_id_consistency(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def set_script_timeout(self, value): pass
            def execute_async_script(self, script): return "ok"

        class FakeDeviceIdTracker:
            def __init__(self):
                self.checked = False

            def check_consistency(self):
                self.checked = True
                return True

        tracker = FakeDeviceIdTracker()
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.device_id_protector = tracker

        bridge._send_keep_alive()

        self.assertTrue(tracker.checked)

    def test_handle_progress_emits_monitor_tick_and_results(self):
        from railwatch_bridge import RailWatchBridge

        events = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)

        bridge._handle_progress({"loop": 3, "date": "2026-06-10", "rows": [{"train": "G7", "raw": "G7 有"}]})

        tick = [event for event in events if event["event"] == "monitorTick"][0]
        self.assertEqual(tick["payload"]["loop"], 3)
        self.assertEqual(tick["payload"]["rows"], [{"train": "G7", "raw": "G7 有"}])
        self.assertEqual(bridge.query_results, [{"train": "G7", "raw": "G7 有"}])

    def test_handle_hit_emits_structured_hit_and_state(self):
        from railwatch_bridge import RailWatchBridge

        events = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)

        bridge._handle_hit(
            {
                "train_code": "G101",
                "seat_type": "二等座",
                "status": "有",
                "source": "regular",
                "title": "命中",
                "message": "命中：G101",
            }
        )

        notify = [event for event in events if event["event"] == "notify"][0]
        self.assertEqual(notify["payload"]["hit"]["seat_type"], "二等座")
        self.assertEqual(notify["payload"]["hit"]["status"], "有")
        state = [event for event in events if event["event"] == "state"][-1]
        self.assertEqual(state["payload"]["hits"][-1]["seat_type"], "二等座")

    def test_handle_human_action_emits_human_action_event(self):
        from railwatch_bridge import RailWatchBridge

        events = []
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=events.append)

        bridge._handle_human_action({"train_code": "G101", "title": "需要人工操作", "message": "请完成核验"})

        human = [event for event in events if event["event"] == "humanAction"][0]
        self.assertEqual(human["payload"]["title"], "需要人工操作")
        self.assertIn("核验", human["payload"]["message"])
        self.assertEqual(human["payload"]["train_code"], "G101")

        # 同时发出非错误的警示状态，让界面在停止后仍显示需要人工核验
        state = [event for event in events if event["event"] == "state"][-1]
        self.assertNotEqual(state["payload"]["phase"], "error")
        self.assertEqual(state["payload"]["risk_level"], "warning")
        self.assertIn("核验", state["payload"]["status_message"])

    def test_check_environment_repairs_mismatched_chromedriver(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def quit(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            events = []
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=events.append)
            bridge._start_connectivity_probe = lambda: None
            stale_path = os.path.join(temp_dir, "stale", "chromedriver.exe")
            os.makedirs(os.path.dirname(stale_path))
            with open(stale_path, "wb") as handle:
                handle.write(b"stub")
            bridge.chromedriver_path = stale_path
            captured = {}

            def fake_install(target_dir, major_version, log_callback, progress_callback=None):
                captured["target_dir"] = target_dir
                captured["major_version"] = major_version
                progress_callback({"stage": "downloading", "message": "正在下载 ChromeDriver…",
                                   "source": "npmmirror 镜像", "downloaded_bytes": 1024,
                                   "total_bytes": 4096, "bytes_per_second": 512, "eta_seconds": 6})
                progress_callback({"stage": "complete", "message": "驱动安装完成"})
                self.assertFalse(any(event["payload"].get("status") == "success"
                                     for event in events if event["event"] == "environmentProgress"))
                return os.path.join(target_dir, "chromedriver.exe")

            bridge._ensure_driver = lambda test_only=False: FakeDriver()

            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", lambda: "152"), \
                patch("railwatch_bridge.detect_chromedriver_version", lambda path: "148.0.7778.178"), \
                patch("railwatch_bridge.download_and_install_chromedriver", fake_install):
                payload = bridge.check_environment()

            self.assertEqual(captured["major_version"], "152")
            self.assertEqual(captured["target_dir"], temp_dir)
            self.assertEqual(bridge.chromedriver_path, os.path.join(temp_dir, "chromedriver.exe"))
            self.assertTrue(payload["environment_ready"])
            progress = [event["payload"] for event in events if event["event"] == "environmentProgress"]
            self.assertEqual(progress[0]["stage"], "checking")
            download = next(item for item in progress if item["stage"] == "downloading")
            self.assertEqual(download["downloaded_bytes"], 1024)
            self.assertEqual(download["total_bytes"], 4096)
            self.assertEqual(download["eta_seconds"], 6)
            self.assertEqual(download["source"], "npmmirror 镜像")
            self.assertEqual(progress[-2]["stage"], "verifying")
            self.assertNotIn("total_bytes", progress[-2])
            self.assertEqual(progress[-1]["status"], "success")
            self.assertTrue(all(item["operation"] == "checkEnvironment" for item in progress))
            self.assertEqual(len({item["started_at"] for item in progress}), 1)
            self.assertTrue(all(item["updated_at"] >= item["started_at"] for item in progress))

    def test_check_environment_skips_repair_when_chromedriver_matches(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def quit(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            driver_path = os.path.join(temp_dir, "chromedriver.exe")
            with open(driver_path, "wb") as handle:
                handle.write(b"stub")
            bridge.chromedriver_path = driver_path
            install_called = []

            bridge._ensure_driver = lambda test_only=False: FakeDriver()

            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", lambda: "152"), \
                patch("railwatch_bridge.detect_chromedriver_version", lambda path: "152.0.7977.65"), \
                patch("railwatch_bridge.download_and_install_chromedriver", lambda **kwargs: install_called.append(kwargs)):
                payload = bridge.check_environment()

            self.assertEqual(install_called, [])
            self.assertEqual(bridge.chromedriver_path, driver_path)
            self.assertTrue(payload["environment_ready"])

    def test_chromedriver_repair_failure_is_retried_only_when_forced(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            calls = []

            def fake_install(target_dir, major_version, log_callback, progress_callback=None):
                calls.append(major_version)
                raise RuntimeError("network down")

            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", lambda: "152"), \
                patch("railwatch_bridge.detect_chromedriver_version", lambda path: None), \
                patch("railwatch_bridge.download_and_install_chromedriver", fake_install):
                bridge._ensure_matching_chromedriver()
                bridge._ensure_matching_chromedriver()

                self.assertEqual(len(calls), 1)

                bridge._ensure_matching_chromedriver(force=True)

                self.assertEqual(len(calls), 2)

    def test_download_chromedriver_targets_writable_data_dir(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            bridge.chromedriver_path = os.path.join("C:\\", "Program Files", "packaged", "chromedriver.exe")
            captured = {}

            def fake_install(target_dir, major_version, log_callback, progress_callback=None):
                captured["target_dir"] = target_dir
                return os.path.join(target_dir, "chromedriver.exe")

            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", lambda: "148"), \
                patch("railwatch_bridge.download_and_install_chromedriver", fake_install):
                result = bridge.download_chromedriver()

            self.assertEqual(captured["target_dir"], temp_dir)
            self.assertEqual(os.path.dirname(result["chromedriver_path"]), temp_dir)

    def test_missing_chrome_and_manual_driver_hints_prefer_china_urls(self):
        import chromedriver_manager
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("chromedriver_manager.detect_chrome_version", lambda: None):
                with self.assertRaises(RuntimeError) as cm:
                    chromedriver_manager.download_and_install_chromedriver(temp_dir)
            self.assertIn("https://www.google.cn/chrome/", str(cm.exception))
            self.assertNotIn("google.com/chrome", str(cm.exception))

            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=lambda event: None)
            bridge.chromedriver_path = os.path.join(temp_dir, "missing", "chromedriver.exe")
            bridge._start_connectivity_probe = lambda: None

            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.detect_chrome_version", lambda: None):
                result = bridge.download_chromedriver()
            self.assertEqual(result["chrome_version"], "")
            messages = "\n".join(entry["message"] for entry in bridge.log_entries)
            self.assertIn("https://www.google.cn/chrome/", messages)
            self.assertNotIn("google.com/chrome", messages)

            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", False):
                with self.assertRaises(RuntimeError) as manual_err:
                    bridge.download_chromedriver()
            self.assertIn("registry.npmmirror.com", str(manual_err.exception))

            bridge.log_entries.clear()
            with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", False), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True):
                bridge._ensure_driver = lambda test_only=False: (_ for _ in ()).throw(RuntimeError("session not created: version"))
                bridge.check_environment()
            env_messages = "\n".join(entry["message"] for entry in bridge.log_entries)
            self.assertIn("https://www.google.cn/chrome/", env_messages)
            self.assertIn("registry.npmmirror.com", env_messages)
            self.assertNotIn("google.com/chrome", env_messages)

    def test_browser_uses_persistent_profile_bounded_transport_and_hygiene_only(self):
        from railwatch_bridge import RailWatchBridge
        driver = Mock()
        bridge = RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)
        options = Mock(arguments=[], experimental_options={})
        options.add_argument.side_effect = options.arguments.append

        def add_exp(key, value):
            options.experimental_options[key] = value

        options.add_experimental_option.side_effect = add_exp
        chrome = Mock(return_value=driver)
        with patch.object(bridge, "_ensure_matching_chromedriver"), patch("railwatch_bridge.SELENIUM_AVAILABLE", True), patch("railwatch_bridge.webdriver", Mock(Chrome=chrome, ChromeOptions=Mock(return_value=options))):
            self.assertIs(bridge._ensure_driver(), driver)
        self.assertTrue(any(value.startswith("--user-data-dir=") for value in chrome.call_args.kwargs["options"].arguments))
        self.assertEqual(driver.command_executor.client_config.timeout, 35)
        # Launch hygiene only: no full fingerprint overwrite via execute_script.
        driver.execute_script.assert_not_called()
        self.assertTrue(driver.execute_cdp_cmd.called)
        command, payload = driver.execute_cdp_cmd.call_args[0]
        self.assertEqual(command, "Page.addScriptToEvaluateOnNewDocument")
        source = payload["source"]
        self.assertIn("webdriver", source)
        self.assertIn("cdc_", source)
        self.assertNotIn("toDataURL", source)
        self.assertNotIn("WebGLRenderingContext", source)
        self.assertNotIn("devicePixelRatio", source)
        self.assertIn("--disable-blink-features=AutomationControlled", options.arguments)
        self.assertIn("enable-automation", options.experimental_options.get("excludeSwitches", []))

    def test_runtime_process_outputs_utf8_json(self):
        # An actual pending order in the user's data directory is valid state;
        # this encoding test must use its own empty profile.
        with tempfile.TemporaryDirectory() as data_home:
            completed = subprocess.run(
                [sys.executable, "railwatch_runtime.py"],
                input=b'{"id":"1","command":"getRuntimeInfo","payload":{}}\n',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=True,
                env={**os.environ, "LOCALAPPDATA": data_home, "XDG_DATA_HOME": data_home, "HOME": data_home},
            )

        response = json.loads(completed.stdout.decode("utf-8"))

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["state"]["status_message"], "就绪")


class ClosedBrowserDriver:
    """A cached WebDriver handle whose Chrome window was closed outside the app.

    ChromeDriver answers every command on such a handle with the same
    InvalidSessionIdException a real driver raises once its browser is gone.
    """

    class InvalidSessionIdException(Exception):
        pass

    def __init__(self):
        self.quit_calls = 0
        self.service = Mock()

    @property
    def window_handles(self):
        raise self.InvalidSessionIdException("Message: invalid session id")

    def get(self, url):
        raise self.InvalidSessionIdException("Message: invalid session id")

    def quit(self):
        self.quit_calls += 1
        raise self.InvalidSessionIdException("Message: invalid session id")


class StaleBrowserSessionTests(unittest.TestCase):
    """Closing the controlled Chrome window must not wedge the cached driver handle."""

    def _bridge(self):
        from railwatch_bridge import RailWatchBridge

        return RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)

    def test_session_probe_only_treats_lost_sessions_as_dead(self):
        from railwatch_bridge import driver_session_alive, is_session_lost

        class TimeoutException(Exception):
            pass

        class PartialDriver:
            """A test double without window_handles must keep its old meaning."""

        self.assertTrue(is_session_lost(ClosedBrowserDriver.InvalidSessionIdException("invalid session id")))
        self.assertTrue(is_session_lost(Exception("Message: invalid session id; For documentation on this error, please visit")))
        self.assertTrue(is_session_lost(Exception("Message: disconnected: not connected to DevTools")))
        self.assertFalse(is_session_lost(TimeoutException("timeout: Timed out receiving message from renderer")))

        self.assertFalse(driver_session_alive(None))
        self.assertFalse(driver_session_alive(ClosedBrowserDriver()))
        self.assertTrue(driver_session_alive(PartialDriver()))

    def test_ensure_driver_restarts_chrome_when_the_cached_browser_is_gone(self):
        bridge = self._bridge()
        closed = ClosedBrowserDriver()
        bridge.driver = closed
        replacement = Mock()
        webdriver_module = Mock()
        webdriver_module.Chrome.return_value = replacement

        with patch.object(bridge, "_ensure_matching_chromedriver"), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True), \
                patch("railwatch_bridge.webdriver", webdriver_module), \
                patch("railwatch_bridge.Service", None):
            driver = bridge._ensure_driver()

        self.assertIs(driver, replacement)
        self.assertIs(bridge.driver, replacement)
        self.assertEqual(closed.quit_calls, 1)
        self.assertTrue(closed.service.stop.called)

    def test_open_login_reopens_the_browser_after_the_window_was_closed(self):
        bridge = self._bridge()
        closed = ClosedBrowserDriver()

        class FreshDriver:
            def __init__(self):
                self.opened = []

            def get(self, url):
                self.opened.append(url)

        fresh = FreshDriver()
        pending = [closed, fresh]

        def ensure(test_only=False):
            driver = pending.pop(0)
            bridge.driver = driver
            return driver

        bridge._ensure_driver = ensure
        state = bridge.open_login()

        self.assertEqual(pending, [])
        self.assertIn("login.html", fresh.opened[-1])
        self.assertIn("登录页面已打开", state["status_message"])
        self.assertEqual(closed.quit_calls, 1)
        self.assertTrue(closed.service.stop.called)

    def test_open_login_surfaces_non_session_failures_without_relaunching(self):
        bridge = self._bridge()
        launches = []

        class TimeoutDriver:
            def get(self, url):
                raise RuntimeError("timeout: Timed out receiving message from renderer: 30.000")

        def ensure(test_only=False):
            launches.append(1)
            bridge.driver = TimeoutDriver()
            return bridge.driver

        bridge._ensure_driver = ensure
        state = bridge.open_login()

        self.assertEqual(len(launches), 1)
        self.assertIn("打开登录页失败", state["error_message"])
        self.assertIsNotNone(bridge.driver)

    def test_close_browser_releases_a_handle_whose_session_is_already_gone(self):
        bridge = self._bridge()
        closed = ClosedBrowserDriver()
        bridge.driver = closed
        bridge.state = bridge.state.__class__(login_ready=True, query_ready=True)

        result = bridge.close_browser(confirmed=True)

        self.assertEqual(result, {"closed": True})
        self.assertFalse(bridge.state.login_ready or bridge.state.query_ready)
        self.assertIsNone(bridge.driver)
        self.assertEqual(closed.quit_calls, 1)
        self.assertTrue(closed.service.stop.called)

    def test_close_browser_still_releases_the_handle_when_quit_fails(self):
        bridge = self._bridge()

        class StubbornDriver:
            service = None

            def quit(self):
                raise RuntimeError("user data directory is busy")

        bridge.driver = StubbornDriver()

        with self.assertRaisesRegex(RuntimeError, "busy"):
            bridge.close_browser(confirmed=True)
        self.assertIsNone(bridge.driver)

    def test_check_environment_recovers_after_the_browser_was_closed(self):
        bridge = self._bridge()
        closed = ClosedBrowserDriver()

        class ProbeDriver:
            def __init__(self):
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        probe = ProbeDriver()
        bridge.driver = closed
        bridge._ensure_driver = lambda test_only=False: probe

        with patch("railwatch_bridge.CD_MANAGER_AVAILABLE", False), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True):
            state = bridge.check_environment()

        self.assertTrue(state["environment_ready"])
        self.assertEqual(state["error_message"], "")
        self.assertEqual(closed.quit_calls, 1)
        self.assertTrue(closed.service.stop.called)
        self.assertTrue(probe.quit_called)
        self.assertIsNone(bridge.driver)

    def test_environment_error_does_not_blame_the_chromedriver_version_for_a_lost_session(self):
        bridge = self._bridge()

        def explode(test_only=False):
            raise RuntimeError("Message: invalid session id")

        bridge._ensure_driver = explode

        with patch.object(bridge, "_ensure_matching_chromedriver"), \
                patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True):
            state = bridge.check_environment()

        self.assertIn("invalid session id", state["error_message"])
        self.assertNotIn("版本与 Chrome 不匹配", state["error_message"])

    def test_environment_error_keeps_the_version_hint_for_a_real_version_mismatch(self):
        bridge = self._bridge()

        def explode(test_only=False):
            raise RuntimeError("session not created: This version of ChromeDriver only supports Chrome version 152")

        bridge._ensure_driver = explode

        with patch.object(bridge, "_ensure_matching_chromedriver"), \
                patch("railwatch_bridge.CD_MANAGER_AVAILABLE", True), \
                patch("railwatch_bridge.SELENIUM_AVAILABLE", True):
            state = bridge.check_environment()

        self.assertIn("版本与 Chrome 不匹配", state["error_message"])

    def test_check_environment_restarts_connectivity_probe_after_success(self):
        import threading
        import time
        from railwatch_bridge import RailWatchBridge

        probe_calls = 0
        emitted = []
        second_probe_done = threading.Event()

        def fake_probe():
            nonlocal probe_calls
            probe_calls += 1
            label = "正常" if probe_calls == 1 else "已恢复"
            if probe_calls >= 2:
                second_probe_done.set()
            return {
                "network_ok": True,
                "network_label": label,
                "railway_ok": True,
                "railway_label": "正常",
                "proxy_configured": False,
                "proxy_label": "未配置",
                "proxy_value": "",
            }

        class ProbeDriver:
            def quit(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("railwatch_bridge.probe_connectivity", side_effect=fake_probe), \
            patch("railwatch_bridge.get_chrome_version_info", return_value="Chrome 137"), \
            patch("railwatch_bridge.CD_MANAGER_AVAILABLE", False), \
            patch("railwatch_bridge.SELENIUM_AVAILABLE", True):
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=emitted.append)
            bridge._ensure_driver = lambda test_only=False: ProbeDriver()
            bridge.get_runtime_info(probe=True)
            emitted.clear()

            state = bridge.check_environment()
            self.assertTrue(state["environment_ready"])
            self.assertTrue(second_probe_done.wait(timeout=2))

            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(ev.get("event") == "labels" for ev in emitted):
                    break
                time.sleep(0.01)

            labels_events = [ev["payload"] for ev in emitted if ev.get("event") == "labels"]
            self.assertEqual(len(labels_events), 1)
            self.assertEqual(labels_events[0]["network_label"], "已恢复")
            self.assertEqual(bridge.get_runtime_info(probe=False)["network_label"], "已恢复")

    def test_check_environment_restarts_connectivity_probe_after_failure(self):
        import threading
        import time
        from railwatch_bridge import RailWatchBridge

        emitted = []
        probe_done = threading.Event()

        def fake_probe():
            probe_done.set()
            return {
                "network_ok": True,
                "network_label": "正常",
                "railway_ok": True,
                "railway_label": "正常",
                "proxy_configured": False,
                "proxy_label": "未配置",
                "proxy_value": "",
            }

        def explode(test_only=False):
            raise RuntimeError("driver failed")

        with tempfile.TemporaryDirectory() as temp_dir, \
            patch("railwatch_bridge.probe_connectivity", side_effect=fake_probe), \
            patch("railwatch_bridge.get_chrome_version_info", return_value="Chrome 137"), \
            patch("railwatch_bridge.CD_MANAGER_AVAILABLE", False), \
            patch("railwatch_bridge.SELENIUM_AVAILABLE", True):
            bridge = RailWatchBridge(data_dir=temp_dir, event_callback=emitted.append)
            bridge._ensure_driver = explode

            state = bridge.check_environment()
            self.assertIn("driver failed", state["error_message"])
            self.assertTrue(probe_done.wait(timeout=2))

            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(ev.get("event") == "labels" for ev in emitted):
                    break
                time.sleep(0.01)

            self.assertTrue(any(ev.get("event") == "labels" for ev in emitted))
            self.assertEqual(bridge.get_runtime_info(probe=False)["network_label"], "正常")


class DriverLaunchRecoveryTests(unittest.TestCase):
    def make_bridge(self):
        from railwatch_bridge import RailWatchBridge
        return RailWatchBridge(data_dir=temp_data_dir(self), event_callback=lambda event: None)

    def test_profile_locked_start_signature(self):
        from railwatch_bridge import RailWatchBridge
        crashed = Exception("session not created: Chrome failed to start: crashed. "
                            "(session not created: DevToolsActivePort file doesn't exist)")
        self.assertTrue(RailWatchBridge._is_profile_locked_start(crashed))
        self.assertFalse(RailWatchBridge._is_profile_locked_start(Exception("element not interactable")))

    def test_stale_profile_chrome_is_cleaned_and_launch_retried(self):
        bridge = self.make_bridge()
        bridge._ensure_matching_chromedriver = lambda: None
        attempts = []

        class FakeClientConfig:
            timeout = 0

        class FakeExecutor:
            client_config = FakeClientConfig()

        class FakeDriver:
            command_executor = FakeExecutor()

        def flaky_launch(options):
            attempts.append(1)
            if len(attempts) == 1:
                raise Exception("session not created: Chrome failed to start: crashed. "
                                "(session not created: DevToolsActivePort file doesn't exist)")
            return FakeDriver()

        swept = []
        bridge._launch_chrome = flaky_launch
        bridge._terminate_profile_chrome = lambda: swept.append(1) and 1
        driver = bridge._ensure_driver()
        self.assertIsInstance(driver, FakeDriver)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(swept), 1)
        self.assertIs(bridge.driver, driver)
        self.assertEqual(driver.command_executor.client_config.timeout, 35)

    def test_unrelated_launch_failure_is_reraised_without_sweep(self):
        bridge = self.make_bridge()
        bridge._ensure_matching_chromedriver = lambda: None

        def broken(options):
            raise ValueError("bad proxy")

        bridge._launch_chrome = broken
        bridge._terminate_profile_chrome = lambda: self.fail("不匹配的启动失败不应清理浏览器")
        with self.assertRaises(ValueError):
            bridge._ensure_driver()

    def test_terminate_profile_chrome_targets_only_app_profile(self):
        bridge = self.make_bridge()
        issued = []

        class Result:
            returncode = 0
            stdout = "2\n"

        def fake_run(command, **kwargs):
            issued.append((command, kwargs))
            return Result()

        profile = os.path.join(bridge.data_dir, "chrome_profile_12306")
        with patch("railwatch_bridge.subprocess.run", fake_run), patch("railwatch_bridge.sys.platform", "win32"):
            killed = bridge._terminate_profile_chrome()
        self.assertEqual(killed, 2)
        command, options = issued[-1]
        self.assertEqual(options["env"]["RAILWATCH_CLEANUP_PROFILE"], profile)
        self.assertNotIn(bridge.data_dir, command[-1])

        # macOS has no count to read back: pkill matches the whole argument and reports success.
        with patch("railwatch_bridge.subprocess.run", fake_run), patch("railwatch_bridge.sys.platform", "darwin"):
            killed = bridge._terminate_profile_chrome()
        self.assertEqual(killed, 1)
        command, _options = issued[-1]
        self.assertEqual(command, ["pkill", "-f", "(^|[[:space:]])--user-data-dir=" + re.escape(profile) + "([[:space:]]|$)"])

    @unittest.skipUnless(os.name == "nt", "Windows command-line matching")
    def test_cleanup_matches_exact_profile_argument_without_evaluating_path(self):
        import subprocess
        bridge = self.make_bridge()
        calls = []
        with patch("railwatch_bridge.subprocess.run", side_effect=lambda command, **kwargs:
                   calls.append((command, kwargs)) or Mock(stdout="0")):
            bridge._terminate_profile_chrome()
        command, options = calls[0]
        for folder in (r"C:\Users\Test User\railwatch", r"C:\Users\O'Brien [work] $()\railwatch",
                       r"C:\Users\张三 的电脑\AppData\Local\railwatch"):
            profile = folder + r"\chrome_profile_12306"
            lines = [
                f'chrome.exe "--user-data-dir={profile}" --test',
                f'chrome.exe --user-data-dir="{profile}" --test',
                f'chrome.exe "--user-data-dir={profile}-backup" --test',
                f'chrome.exe "--user-data-dir={profile}2" --test',
                f'chrome.exe "--log-file={profile}"',
                'chrome.exe --user-data-dir=C:\\unrelated',
                f'chrome.exe "--user-data-dir={profile.replace(chr(92), chr(47))}"',
            ]
            fake_processes = json.dumps([{"ProcessId": i + 1, "CommandLine": line}
                                         for i, line in enumerate(lines)])
            # Replace enumeration and termination with in-process test doubles;
            # exercise the actual matcher without terminating any processes.
            prelude = '''
function Get-CimInstance { param($ClassName, $Filter) $items = $env:RAILWATCH_TEST_PROCESSES | ConvertFrom-Json; foreach ($item in $items) { $item } }
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) Write-Output "matched:$Id" }
'''
            # Include Windows PowerShell startup time on shared CI runners.
            # Keep a finite test deadline without changing the runtime timeout.
            result = subprocess.run(command[:-1] + [prelude + command[-1]],
                                    capture_output=True, text=True, timeout=60,
                                    env={**options["env"], "RAILWATCH_CLEANUP_PROFILE": profile,
                                         "RAILWATCH_TEST_PROCESSES": fake_processes},
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.split(), ["matched:1", "matched:2", "matched:7", "3"])


if __name__ == "__main__":
    unittest.main()
