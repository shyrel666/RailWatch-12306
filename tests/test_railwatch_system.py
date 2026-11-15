import os
import tempfile
import unittest
from unittest.mock import patch

from railwatch_system import detect_proxy, get_app_version, inspect_data_dir, pending_connectivity_snapshot, probe_connectivity


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

    def test_pending_connectivity_snapshot_returns_fast_labels_and_proxy(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://user:secret@127.0.0.1:7890"}, clear=False):
            status = pending_connectivity_snapshot()

        self.assertFalse(status["network_ok"])
        self.assertEqual(status["network_label"], "检测中")
        self.assertFalse(status["railway_ok"])
        self.assertEqual(status["railway_label"], "检测中")
        self.assertIs(status["connectivity_pending"], True)
        self.assertTrue(status["proxy_configured"])
        self.assertEqual(status["proxy_label"], "已配置")
        self.assertNotIn("secret", status["proxy_value"])


if __name__ == "__main__":
    unittest.main()
