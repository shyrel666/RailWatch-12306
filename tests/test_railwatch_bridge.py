import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock


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
