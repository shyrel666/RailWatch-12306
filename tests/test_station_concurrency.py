"""Station cache concurrency and runtime responsiveness without network access."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from gui_12306_0 import StationCodeResolver
from railwatch_bridge import RailWatchBridge
from railwatch_runtime import RailWatchRuntime


SOURCE = "var station_names ='@bjb|北京北|VAP|beijingbei|bjb|0@shhq|上海虹桥|AOH|shanghaihongqiao|shhq|0';"


class StationConcurrencyTests(unittest.TestCase):
    def test_concurrent_cold_loads_share_one_download(self):
        entered, duplicate, release = threading.Event(), threading.Event(), threading.Event()
        followers = threading.Barrier(4)

        def download(*args, **kwargs):
            if entered.is_set():
                duplicate.set()
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test download was not released")
            return io.BytesIO(SOURCE.encode("utf-8"))

        with tempfile.TemporaryDirectory() as directory, \
                patch("gui_12306_0.urllib.request.urlopen", side_effect=download) as fetch, \
                ThreadPoolExecutor(4) as pool:
            resolver = StationCodeResolver(directory)
            first = pool.submit(resolver.load)
            try:
                self.assertTrue(entered.wait(2))
                def load_after_barrier():
                    followers.wait(2)
                    return resolver.load()
                pending = [pool.submit(load_after_barrier) for _ in range(3)]
                followers.wait(2)
                self.assertFalse(duplicate.wait(.2), "concurrent callers downloaded the same station data")
            finally:
                release.set()
            names = first.result(timeout=2)
            self.assertEqual(names, {"北京北": "VAP", "上海虹桥": "AOH"})
            for future in pending:
                self.assertIs(future.result(timeout=2), names)
            fetch.assert_called_once()
            self.assertEqual(resolver.search("bjb")["items"][0]["code"], "VAP")

    def test_failed_cold_load_can_be_retried_from_another_thread(self):
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(1) as pool:
            resolver = StationCodeResolver(directory)
            with patch("gui_12306_0.urllib.request.urlopen", side_effect=OSError("offline")), \
                    patch("gui_12306_0.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    resolver.load()
            with patch("gui_12306_0.urllib.request.urlopen", return_value=io.BytesIO(SOURCE.encode("utf-8"))) as fetch:
                self.assertEqual(pool.submit(resolver.get_code, "北京北").result(timeout=2), "VAP")
                fetch.assert_called_once()

    def test_queries_keep_loaded_codes_while_a_refresh_downloads(self):
        entered, release = threading.Event(), threading.Event()

        def slow_download(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test download was not released")
            return io.BytesIO(SOURCE.encode("utf-8"))

        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(2) as pool:
            resolver = StationCodeResolver(directory)
            with patch("gui_12306_0.urllib.request.urlopen", return_value=io.BytesIO(SOURCE.encode("utf-8"))):
                resolver.load()
            with patch("gui_12306_0.urllib.request.urlopen", side_effect=slow_download):
                refreshing = pool.submit(resolver.refresh)
                try:
                    self.assertTrue(entered.wait(2))
                    # A running monitor refills its query form from the codes it already has.
                    self.assertEqual(pool.submit(resolver.get_code, "上海虹桥").result(timeout=1), "AOH")
                finally:
                    release.set()
                self.assertEqual(refreshing.result(timeout=2), {"count": 2})

    def test_failed_refresh_preserves_code_and_search_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            resolver = StationCodeResolver(directory)
            with patch("gui_12306_0.urllib.request.urlopen", return_value=io.BytesIO(SOURCE.encode("utf-8"))):
                initial = resolver.search("bjb")
            with patch("gui_12306_0.urllib.request.urlopen", side_effect=OSError("offline")), \
                    patch("gui_12306_0.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    resolver.refresh()
                self.assertEqual(resolver.search("bjb"), initial)
                self.assertEqual(resolver.get_code("北京北"), "VAP")
                self.assertEqual(StationCodeResolver(directory).search("bjb"), initial)

    def test_slow_station_commands_leave_preferences_responsive(self):
        for command, count in (("searchStations", 4), ("refreshStations", 1)):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                entered, release = threading.Event(), threading.Event()
                responses = []
                bridge = RailWatchBridge(directory)
                runtime = RailWatchRuntime(bridge=bridge, writer=responses.append, max_workers=count)

                def download(*args, **kwargs):
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError("test download was not released")
                    return io.BytesIO(SOURCE.encode("utf-8"))

                def send(name, request_id):
                    return runtime.handle_line(json.dumps({"id": request_id, "command": name,
                                                           "payload": {"query": "北京"}}))

                with patch("gui_12306_0.urllib.request.urlopen", side_effect=download) as fetch:
                    try:
                        pending = [send(command, f"station-{index}") for index in range(count)]
                        self.assertTrue(entered.wait(2))
                        send("loadPreferences", "preferences").result(timeout=2)
                        self.assertTrue(next(row for row in responses if row["id"] == "preferences")["ok"])
                        self.assertTrue(all(not future.done() for future in pending))
                    finally:
                        release.set()
                        runtime.shutdown()
                        bridge.notification_service.close()
                    fetch.assert_called_once()
                station_responses = [row for row in responses if row["id"].startswith("station-")]
                self.assertEqual(len(station_responses), count)
                for row in station_responses:
                    self.assertTrue(row["ok"], row)
                    if command == "searchStations":
                        self.assertEqual(row["result"]["items"][0]["name"], "北京北")
                    else:
                        self.assertEqual(row["result"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
