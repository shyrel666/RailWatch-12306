import json
import os
import tempfile
import unittest
from unittest.mock import patch

from railwatch_trip_choices import load_trip_choices, remember_route, save_train_favorites
from railwatch_config_contract import validate_config
from railwatch_seats import validate_automation_seats, public_seat_capabilities


class TripChoicesTests(unittest.TestCase):
    def test_route_favorites_are_scoped_and_recent_route_has_no_trip_details(self):
        with tempfile.TemporaryDirectory() as data_dir:
            remember_route(data_dir, "北京南", "上海虹桥")
            save_train_favorites(data_dir, "北京南", "上海虹桥", ["G101", "G101", "D21"])
            remember_route(data_dir, "上海虹桥", "北京南")
            result = load_trip_choices(data_dir)
            self.assertEqual(result["recent_routes"][0], {"from_station": "上海虹桥", "to_station": "北京南"})
            self.assertEqual(result["favorites"], [{"from_station": "北京南", "to_station": "上海虹桥",
                                                    "trains": ["G101", "D21"]}])
            self.assertNotIn("date", json.dumps(result))
            self.assertNotIn("auto_submit", json.dumps(result))
            self.assertEqual(load_trip_choices(data_dir), result)

    def test_rejects_invalid_route_and_trains_without_changing_file(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_train_favorites(data_dir, "北京", "上海", ["G1"])
            path = os.path.join(data_dir, "trip_choices.json")
            with open(path, "rb") as handle:
                before = handle.read()
            for trains in (["G1", "bad-code"], ["G1"] * 21, "G1"):
                with self.assertRaises(ValueError):
                    save_train_favorites(data_dir, "北京", "上海", trains)
            with self.assertRaises(ValueError):
                remember_route(data_dir, "北京", "北京")
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), before)

    def test_same_station_is_not_a_valid_executable_route(self):
        with self.assertRaisesRegex(ValueError, "不能相同"):
            validate_config({"from_station_cn": "北京", "to_station_cn": "北京"})

    def test_seat_transaction_support_is_explicit(self):
        seats = public_seat_capabilities()
        self.assertIn("硬卧", [item["name"] for item in seats if item["regular"]])
        self.assertEqual(validate_automation_seats("硬座，软卧", regular=True, alternate=False), ["硬座", "软卧"])
        with self.assertRaisesRegex(ValueError, "尚未通过"):
            validate_automation_seats("高级软卧", regular=True, alternate=False)
        with self.assertRaisesRegex(ValueError, "尚未通过"):
            validate_automation_seats("硬座", regular=False, alternate=True)

    def test_structured_passenger_selection_keeps_legacy_name_field(self):
        selected = validate_config({"passengers": "张三", "passenger_selections": [
            {"name": "张三", "ticket_type": "adult", "identity_hint": "11***22", "unknown": "discard"}]})
        self.assertEqual(selected["passengers"], "张三")
        self.assertEqual(selected["passenger_selections"], [
            {"name": "张三", "ticket_type": "adult", "identity_hint": "11***22"}])

    def test_station_search_uses_legacy_cache_offline(self):
        from gui_12306_0 import StationCodeResolver

        with tempfile.TemporaryDirectory() as data_dir:
            with open(os.path.join(data_dir, "station_codes_cache.json"), "w", encoding="utf-8") as handle:
                json.dump({"北京": "BJP", "北京南": "VNP", "上海虹桥": "AOH"}, handle)
            with patch("gui_12306_0.urllib.request.urlopen", side_effect=AssertionError("network used")):
                result = StationCodeResolver(data_dir).search("北京")
            self.assertEqual([item["name"] for item in result["items"]], ["北京", "北京南"])

    def test_station_search_supports_source_pinyin_and_initials(self):
        from gui_12306_0 import StationCodeResolver

        source = "var station_names ='@bjb|北京北|VAP|beijingbei|bjb|0@shhq|上海虹桥|AOH|shanghaihongqiao|shhq|0';"
        with tempfile.TemporaryDirectory() as data_dir:
            response = type("Response", (), {"read": lambda self: source.encode("utf-8"), "__enter__": lambda self: self, "__exit__": lambda *args: None})()
            with patch("gui_12306_0.urllib.request.urlopen", return_value=response):
                resolver = StationCodeResolver(data_dir)
                self.assertEqual(resolver.search("shhq")["items"][0]["name"], "上海虹桥")
            self.assertEqual(StationCodeResolver(data_dir).search("beijingbei")["items"][0]["name"], "北京北")

    def test_passenger_read_is_idle_only_and_returns_masked_candidates(self):
        from railwatch_bridge import RailWatchBridge

        with tempfile.TemporaryDirectory() as data_dir:
            bridge = RailWatchBridge(data_dir=data_dir)
            self.assertIn("未打开", bridge.read_passengers()["warning"])
            driver = type("Driver", (), {"window_handles": ["one"], "execute_script": lambda self, script: [
                {"name": "张三", "ticket_type": "adult", "identity_hint": "11***22"},
                {"name": "张三", "ticket_type": "student", "identity_hint": "33***44"},
                {"name": "李四", "ticket_type": "unknown", "identity_hint": "123456789012345678"},
            ]})()
            bridge.driver = driver
            items = bridge.read_passengers()["items"]
            self.assertTrue(items[0]["ambiguous"])
            self.assertEqual(items[2]["identity_hint"], "")
            bridge._browser_busy = True
            with self.assertRaisesRegex(RuntimeError, "浏览器正在操作"):
                bridge.read_passengers()

    def test_passenger_read_supports_personal_centre_list_without_paging(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_order_page import READ_PASSENGER_BOOK_JS

        scripts = []
        def execute(self, script):
            scripts.append(script)
            return {"recognized": True, "page": 1, "total_pages": 2, "has_next": True, "complete": False, "pagination_valid": True,
                    "items": [{"name": "张三", "ticket_type": "adult", "type_source": "profile_metadata", "identity_hint": "11***22"},
                              {"name": "王五", "ticket_type": "unknown", "type_source": "unavailable", "identity_hint": "33***44"}]}
        with tempfile.TemporaryDirectory() as data_dir:
            bridge = RailWatchBridge(data_dir=data_dir)
            bridge.driver = type("Driver", (), {"window_handles": ["one"], "current_url": "https://kyfw.12306.cn/otn/view/passengers.html?x=1",
                                                 "execute_script": execute})()
            result = bridge.read_passengers()
        self.assertEqual(scripts, [READ_PASSENGER_BOOK_JS])
        self.assertEqual([(item["name"], item["ticket_type"], item["ambiguous"]) for item in result["items"]],
                         [("张三", "adult", False), ("王五", "unknown", False)])
        self.assertIn("仅读取了当前页", result["warning"])


if __name__ == "__main__":
    unittest.main()
