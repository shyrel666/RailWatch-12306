import os
import tempfile
import unittest
from unittest.mock import patch

from railwatch_system import detect_proxy, get_app_version, inspect_data_dir, probe_connectivity


class RailWatchSystemTests(unittest.TestCase):
    def test_get_app_version_prefers_runtime_env(self):
        with patch.dict(os.environ, {"RAILWATCH_APP_VERSION": "2.4.1"}, clear=False):
            self.assertEqual(get_app_version(), "2.4.1")

    def test_inspect_data_dir_reports_writable_path_and_free_space(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status = inspect_data_dir(temp_dir)

        self.assertTrue(status["data_dir_writable"])
        self.assertGreater(int(status["data_dir_free_bytes"]), 0)

    def test_detect_proxy_reads_environment_variables(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7890"}, clear=False):
            configured, value = detect_proxy()

        self.assertTrue(configured)
        self.assertEqual(value, "http://127.0.0.1:7890")

    def test_probe_connectivity_returns_labels(self):
        with patch("railwatch_system._probe_http", return_value=True), patch(
            "railwatch_system._probe_host", return_value=True
        ):
            status = probe_connectivity()

        self.assertTrue(status["network_ok"])
        self.assertEqual(status["network_label"], "正常")
        self.assertTrue(status["railway_ok"])
        self.assertEqual(status["railway_label"], "正常")


if __name__ == "__main__":
    unittest.main()
