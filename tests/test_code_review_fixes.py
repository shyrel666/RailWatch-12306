"""Regressions for the 2026-10 code review: lost browsers, station names and search caching."""
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from gui_12306_0 import StationCodeResolver, TicketMonitor
from railwatch_bridge import RailWatchBridge


class InvalidSessionIdException(Exception):
    pass


CONFIG = {"date": "2026-09-10", "from_station_cn": "北京", "to_station_cn": "上海",
          "interval": 3, "smart_rate": False}


class LostBrowserTests(unittest.TestCase):
    def monitor(self):
        actions = []
        monitor = TicketMonitor(Mock(), dict(CONFIG), log_callback=lambda _: None,
                                server_time_sync=Mock(), human_action_callback=actions.append)
        monitor._prepared = True
        monitor._sleep = Mock()
        return monitor, actions

    def test_closed_browser_stops_monitoring_instead_of_retrying(self):
        monitor, actions = self.monitor()
        monitor._run_single_loop = Mock(side_effect=InvalidSessionIdException("invalid session id"))
        monitor.run()
        monitor._run_single_loop.assert_called_once()
        monitor._sleep.assert_not_called()
        self.assertEqual(len(actions), 1)
        self.assertIn("浏览器已关闭", actions[0]["message"])

    def test_ordinary_failures_still_back_off_and_retry(self):
        monitor, actions = self.monitor()
        monitor._run_single_loop = Mock(side_effect=[RuntimeError("timeout"), True])
        monitor.run()
        self.assertEqual(monitor._run_single_loop.call_count, 2)
        monitor._sleep.assert_called_once()
        self.assertEqual(actions, [])


class StationNameTests(unittest.TestCase):
    def resolver(self, directory, names):
        with open(os.path.join(directory, "station_codes_cache.json"), "w", encoding="utf-8") as handle:
            json.dump(names, handle, ensure_ascii=False)
        return StationCodeResolver(directory)

    def test_trailing_station_suffix_resolves_exact_name(self):
        with tempfile.TemporaryDirectory() as directory:
            resolver = self.resolver(directory, {"北京": "BJP", "北京南": "VNP", "上海": "SHH", "上海虹桥": "AOH"})
            self.assertEqual(resolver.get_code("北京南站"), "VNP")
            self.assertEqual(resolver.get_code("上海虹桥站"), "AOH")
            self.assertEqual(resolver.get_code("北京站"), "BJP")
            with self.assertRaisesRegex(ValueError, "不明确"):
                resolver.get_code("京")

    def test_search_reads_disk_caches_once_per_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = []
            resolver = self.resolver(directory, {"北京": "BJP", "北京南": "VNP"})
            resolver.log = logs.append
            with patch("builtins.open", wraps=open) as opened:
                for query in ("北", "北京", "北京南"):
                    resolver.search(query)
            self.assertEqual(opened.call_count, 2)
            self.assertEqual(len(logs), 1)
            self.assertEqual([item["name"] for item in resolver.search("北京")["items"]], ["北京", "北京南"])


class BridgeStationResolverTests(unittest.TestCase):
    def test_bridge_reuses_one_resolver_and_resets_it_with_local_data(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory, event_callback=lambda _: None)
            self.addCleanup(bridge.notification_service.close)
            with open(os.path.join(directory, "station_codes_cache.json"), "w", encoding="utf-8") as handle:
                json.dump({"北京": "BJP"}, handle, ensure_ascii=False)
            bridge.search_stations("北")
            first = bridge._station_resolver
            bridge.search_stations("北京")
            self.assertIs(bridge._station_resolver, first)
            cache_logs = [entry for entry in bridge.log_entries if "站点编码缓存已加载" in entry["message"]]
            self.assertEqual(len(cache_logs), 1)

    def test_query_analyzers_share_the_bridge_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory, event_callback=lambda _: None)
            self.addCleanup(bridge.notification_service.close)
            with open(os.path.join(directory, "station_codes_cache.json"), "w", encoding="utf-8") as handle:
                json.dump({"北京": "BJP"}, handle, ensure_ascii=False)
            bridge.search_stations("北")
            first = bridge._page_analyzer(object(), lambda *_: None)
            second = bridge._page_analyzer(object(), lambda *_: None)
            self.assertIs(first.resolver, bridge._station_resolver)
            self.assertIs(second.resolver, bridge._station_resolver)
            self.assertEqual(second.resolver.get_code("北京"), "BJP")
            cache_logs = [entry for entry in bridge.log_entries if "站点编码缓存已加载" in entry["message"]]
            self.assertEqual(len(cache_logs), 1)


if __name__ == "__main__":
    unittest.main()
