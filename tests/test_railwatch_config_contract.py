import unittest
from pathlib import Path

from railwatch_config_contract import (
    AUTOMATION_ROUTE,
    default_config,
    redact_proxy_url,
    redact_sensitive_text,
    validate_config,
)


class RailWatchConfigContractTests(unittest.TestCase):
    def test_default_config_includes_query_jobs_and_route(self):
        config = default_config()
        self.assertEqual(config["automation_route"], AUTOMATION_ROUTE)
        self.assertEqual(len(config["query_jobs"]), 1)
        self.assertEqual(config["query_jobs"][0]["from_station_cn"], "北京")

    def test_validate_config_normalizes_primary_and_jobs(self):
        config = validate_config(
            {
                "from_station_cn": "北京",
                "to_station_cn": "上海",
                "date": "2026-06-10",
                "train_code": "g101",
                "interval": "6",
                "burst_window_seconds": 60,
            }
        )
        self.assertEqual(config["train_code"], "G101")
        self.assertEqual(config["interval"], 6.0)
        self.assertEqual(config["burst_window_seconds"], 60.0)
        self.assertEqual(config["query_jobs"][0]["train_code"], "G101")

    def test_redact_sensitive_text(self):
        self.assertEqual(redact_sensitive_text("张三丰"), "张三***丰")
        self.assertEqual(redact_sensitive_text("ab"), "**")

    def test_redact_proxy_url_masks_credentials(self):
        redacted = redact_proxy_url("http://user:secret@proxy.local:8080")
        self.assertIn("***", redacted)
        self.assertNotIn("secret", redacted)

    def test_setuptools_module_list_includes_split_runtime_modules(self):
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")

        for module_name in (
            "railwatch_alternate_flow",
            "railwatch_config_contract",
            "railwatch_dates",
            "railwatch_notify",
            "railwatch_row_parser",
            "railwatch_selectors",
            "railwatch_submit_flow",
            "railwatch_system",
            "railwatch_time",
            "railwatch_verification",
        ):
            self.assertIn(f'"{module_name}"', content)


if __name__ == "__main__":
    unittest.main()
