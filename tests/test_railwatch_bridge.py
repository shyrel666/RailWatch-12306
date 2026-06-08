import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


class RailWatchBridgeContractTests(unittest.TestCase):
    def test_default_config_preserves_existing_ui_defaults(self):
        from railwatch_bridge import default_config

        config = default_config(today=dt.date(2026, 6, 7))

        self.assertEqual(config["from_station_cn"], "北京")
        self.assertEqual(config["to_station_cn"], "上海")
        self.assertEqual(config["date"], "2026-06-08")
        self.assertEqual(config["train_code"], "")
        self.assertEqual(config["seat_keyword"], "")
        self.assertEqual(config["interval"], 5)
        self.assertEqual(config["passenger_count"], 1)
        self.assertEqual(config["seat_prefer"], "无偏好")
        self.assertEqual(config["prepare_time"], 2)
        self.assertTrue(config["keep_alive"])
        self.assertTrue(config["smart_rate"])
        self.assertFalse(config["timer_enabled"])
        self.assertFalse(config["auto_submit"])
        self.assertFalse(config["auto_alternate"])
        self.assertEqual(config["alternate_deadline"], "18:00")

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
                    "query_timeout": 25,
                    "smart_rate": False,
                    "timer_enabled": True,
                    "target_time": "08:30:00",
                    "keep_alive": False,
                }
            )

            self.assertEqual(saved["date_range"], "±2天")
            self.assertEqual(saved["interval"], 1.5)
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

    def test_start_monitor_requires_confirmation_when_dangerous_automation_enabled(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)

        result = bridge.start_monitor(
            {
                "from_station_cn": "北京",
                "to_station_cn": "上海",
                "date": "2026-06-08",
                "auto_submit": True,
                "auto_alternate": True,
            },
            confirmed=False,
        )

        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["title"], "确认自动化")
        self.assertIn("自动提交", result["message"])
        self.assertIn("自动候补", result["message"])
        self.assertFalse(bridge.is_monitoring)

    def test_open_login_opens_page_without_marking_login_ready(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.opened_url = ""

            def get(self, url):
                self.opened_url = url

        driver = FakeDriver()
        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge._ensure_driver = lambda: driver

        state = bridge.open_login()

        self.assertIn("login.html", driver.opened_url)
        self.assertFalse(state["login_ready"])
        self.assertIn("登录页面已打开", state["status_message"])

    def test_check_login_marks_ready_when_12306_session_is_valid(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def execute_script(self, script):
                return {"data": {"flag": True}}

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()

        state = bridge.check_login()

        self.assertTrue(state["login_ready"])
        self.assertEqual(state["status_message"], "登录已验证")

    def test_check_login_rejects_missing_browser_session(self):
        from railwatch_bridge import RailWatchBridge

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)

        state = bridge.check_login()

        self.assertFalse(state["login_ready"])
        self.assertIn("请先打开登录页", state["error_message"])

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

            with patch("railwatch_bridge.PageAnalyzer", FakeAnalyzer), patch("railwatch_bridge.CORE_AVAILABLE", True):
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

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)

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

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.is_monitoring = True
        bridge.driver = object()

        with self.assertRaisesRegex(RuntimeError, "监控运行中"):
            bridge.close_browser(confirmed=True)

    def test_wait_for_target_time_sends_keep_alive_when_enabled(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.keep_alive_calls = 0

            def execute_script(self, script):
                if "checkUser" in script:
                    self.keep_alive_calls += 1
                return None

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.is_monitoring = True

        with patch("railwatch_bridge.time.time", side_effect=[0, 61, 62]), patch("railwatch_bridge.time.sleep", lambda seconds: None):
            bridge._wait_for_target_timestamp(62, {"keep_alive": True})

        self.assertEqual(bridge.driver.keep_alive_calls, 1)

    def test_wait_for_target_time_skips_keep_alive_when_disabled(self):
        from railwatch_bridge import RailWatchBridge

        class FakeDriver:
            def __init__(self):
                self.keep_alive_calls = 0

            def execute_script(self, script):
                self.keep_alive_calls += 1

        bridge = RailWatchBridge(data_dir=tempfile.mkdtemp(), event_callback=lambda event: None)
        bridge.driver = FakeDriver()
        bridge.is_monitoring = True

        with patch("railwatch_bridge.time.time", side_effect=[0, 61, 62]), patch("railwatch_bridge.time.sleep", lambda seconds: None):
            bridge._wait_for_target_timestamp(62, {"keep_alive": False})

        self.assertEqual(bridge.driver.keep_alive_calls, 0)

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

    def test_json_runtime_dispatches_command_response_and_events(self):
        from railwatch_runtime import RailWatchRuntime

        bridge = Mock()
        bridge.get_runtime_info.return_value = {"app": "RailWatch 12306"}
        emitted = []
        runtime = RailWatchRuntime(bridge=bridge, writer=lambda payload: emitted.append(payload))

        runtime.handle_line('{"id":"1","command":"getRuntimeInfo","payload":{}}')

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

        runtime.handle_line('{"id":"1","command":"checkLogin","payload":{}}')

        self.assertEqual(emitted[0]["result"], {"login_ready": True})
        bridge.check_login.assert_called_once_with()

    def test_runtime_process_outputs_utf8_json(self):
        completed = subprocess.run(
            [sys.executable, "railwatch_runtime.py"],
            input=b'{"id":"1","command":"getRuntimeInfo","payload":{}}\n',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=True,
        )

        response = json.loads(completed.stdout.decode("utf-8"))

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["state"]["status_message"], "就绪")


if __name__ == "__main__":
    unittest.main()
