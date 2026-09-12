import tempfile
import unittest
from unittest.mock import Mock, patch

from gui_12306_0 import ConfigManager, QueryConfig, TicketMonitor
from railwatch_bridge import RailWatchBridge
from railwatch_config_contract import default_config, validate_config
from railwatch_policies import priority_defaults


class QueryStrategyTests(unittest.TestCase):
    def test_new_config_defaults_to_reliability_without_enabling_transactions(self):
        config = validate_config({})
        self.assertEqual((config["query_priority"], config["request_mode"], config["interval"], config["query_timeout"]),
                         ("reliability", "conservative", 6, 40))
        self.assertTrue(config["keep_alive"] and config["smart_rate"])
        self.assertFalse(config["auto_submit"] or config["auto_alternate"])

    def test_old_tuning_is_preserved_and_migration_is_idempotent(self):
        for smart_rate, interval in ((False, 8.5), (True, 3.5)):
            with self.subTest(smart_rate=smart_rate):
                original = {"interval": interval, "query_timeout": 51, "smart_rate": smart_rate, "keep_alive": False}
                config = validate_config(original)
                self.assertEqual(config["request_mode"], "legacy")
                for key, value in original.items():
                    self.assertEqual(config[key], value)
                again = validate_config(config)
                self.assertEqual(again["request_mode"], "legacy")
                self.assertEqual(again["query_jobs"][0]["interval"], interval)

    def test_presets_survive_disk_and_bridge_and_control_real_limiter(self):
        for priority, base, timeout, lower, upper in (("speed", 3, 20, 3, 30), ("reliability", 6, 40, 5, 60)):
            with self.subTest(priority=priority), tempfile.TemporaryDirectory() as directory:
                config = validate_config({**default_config(), **priority_defaults(priority)})
                bridge = RailWatchBridge(directory, event_callback=lambda _: None)
                manager = ConfigManager(directory)
                self.assertTrue(manager.save(bridge._make_query_config(config)))
                restored = manager.load().to_dict()
                self.assertEqual((restored["query_priority"], restored["interval"], restored["query_timeout"]),
                                 (priority, base, timeout))
                monitor = TicketMonitor(Mock(), restored, log_callback=lambda _: None, server_time_sync=Mock())
                limiter = monitor.rate_limiter
                self.assertEqual((limiter.min_interval, limiter.max_interval), (lower, upper))
                for _ in range(100):
                    limiter.on_success()
                with patch("anti_detect.random.uniform", side_effect=lambda low, high: low):
                    self.assertEqual(limiter.get_interval(), lower)
                for _ in range(20):
                    limiter.on_timeout()
                with patch("anti_detect.random.uniform", side_effect=lambda low, high: high):
                    self.assertEqual(limiter.get_interval(), upper)

    def test_primary_job_uses_new_strategy_and_other_jobs_keep_their_own(self):
        fast = {**default_config(), **priority_defaults("speed")}
        slow = {**default_config(), **priority_defaults("reliability")}
        config = validate_config({**fast, "query_jobs": [slow, slow]})
        self.assertEqual(config["query_jobs"][0]["request_mode"], "fast")
        self.assertEqual(config["query_jobs"][1]["request_mode"], "conservative")

    def test_customized_values_survive_roundtrip_without_preset_reset(self):
        config = validate_config({**priority_defaults("speed"), "interval": 7.5, "query_timeout": 53,
                                 "keep_alive": False, "smart_rate": False})
        restored = validate_config(QueryConfig.from_dict(config).to_dict())
        self.assertEqual((restored["interval"], restored["query_timeout"], restored["request_mode"]), (7.5, 53, "fast"))
        self.assertFalse(restored["smart_rate"] or restored["keep_alive"])

    def test_unknown_modes_are_rejected(self):
        for patch_config in ({"request_mode": "turbo"}, {"query_priority": "turbo"}):
            with self.subTest(patch_config=patch_config), self.assertRaises(ValueError):
                validate_config(patch_config)


if __name__ == "__main__":
    unittest.main()
