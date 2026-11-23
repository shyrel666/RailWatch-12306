import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_cleanup import reset_directory
from railwatch_config_contract import TRIP_FIELD_KEYS
from railwatch_preferences import atomic_write_json
from railwatch_runtime import RailWatchRuntime
from railwatch_state import APP_SLUG
from railwatch_trip_choices import MAX_FAVORITES, MAX_ROUTES, load_trip_choices, remember_route, save_train_favorites
from railwatch_trip_presets import (
    FILE_NAME,
    MAX_PRESETS,
    delete_trip_preset,
    export_sanitized_bundle,
    import_sanitized_bundle,
    load_trip_presets,
    save_trip_preset,
)


def exported_preset(name, config, preset_id="external-1"):
    return {"id": preset_id, "name": name, "config": config}


class TripPresetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data_dir = str(Path(directory.name, APP_SLUG).resolve())
        self.path = Path(self.data_dir, FILE_NAME)

    def test_save_load_update_and_delete_preserve_only_trip_fields(self):
        self.assertEqual(load_trip_presets(self.data_dir), {"items": []})
        saved = save_trip_preset(self.data_dir, " 南站行程 ", {
            "date": "2001-03-15", "passengers": "本机乘车人", "seat_keyword": "二等座",
            "custom_dates": ["2001-03-15", "2001-03-19"], "notification_settings": {"email_password": "ignored"},
        })
        preset_id = saved["saved_id"]
        self.assertRegex(preset_id, r"^[A-Za-z0-9_-]{1,64}$")
        item, = saved["items"]
        self.assertEqual(item["name"], "南站行程")
        self.assertEqual(set(item["config"]), set(TRIP_FIELD_KEYS))
        self.assertEqual(item["config"]["date"], "2001-03-15")
        self.assertEqual(item["config"]["passengers"], "本机乘车人")
        self.assertEqual(item["config"]["custom_dates"], ["2001-03-15", "2001-03-19"])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"schema_version": 1, "items": [item]})
        updated = save_trip_preset(self.data_dir, "新名字", {"date": "2090-01-01", "auto_submit": True}, preset_id)
        self.assertEqual(updated["saved_id"], preset_id)
        self.assertEqual(updated["items"][0]["config"]["date"], "2090-01-01")
        self.assertTrue(updated["items"][0]["config"]["auto_submit"])
        self.assertEqual(load_trip_presets(self.data_dir), {"items": updated["items"]})
        self.assertEqual(delete_trip_preset(self.data_dir, preset_id), {"items": []})
        self.assertEqual(delete_trip_preset(self.data_dir, preset_id), {"items": []})

    def test_invalid_names_ids_config_and_capacity_do_not_overwrite(self):
        name = "长" * 40
        first = save_trip_preset(self.data_dir, name, {"date": ""})
        saved_id = first["saved_id"]
        for n in range(1, MAX_PRESETS):
            save_trip_preset(self.data_dir, f"方案 {n}", {})
        before = self.path.read_bytes()
        for invalid_name in (None, 42, "", "　", "长" * 41, "换\n行", "名称\x7f", "\x85行程", "尾部\t"):
            with self.subTest(name=invalid_name), self.assertRaises(ValueError):
                save_trip_preset(self.data_dir, invalid_name, {}, saved_id)
        for invalid_id in (1, "", "../preset", "x\n", "中文", "a" * 65):
            with self.subTest(id=invalid_id):
                with self.assertRaises(ValueError):
                    save_trip_preset(self.data_dir, name, {}, invalid_id)
                with self.assertRaises(ValueError):
                    delete_trip_preset(self.data_dir, invalid_id)
        for invalid_config in ([], {"custom_dates": [1]}, {"interval": float("nan")}):
            with self.subTest(config=invalid_config), self.assertRaises(ValueError):
                save_trip_preset(self.data_dir, name, invalid_config, saved_id)
        with self.assertRaisesRegex(ValueError, "不存在"):
            save_trip_preset(self.data_dir, name, {}, "missing-1")
        with self.assertRaisesRegex(ValueError, "同名"):
            save_trip_preset(self.data_dir, "方案 1", {}, saved_id)
        with self.assertRaisesRegex(ValueError, "最多保存 20"):
            save_trip_preset(self.data_dir, "另一个方案", {})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(save_trip_preset(self.data_dir, name, {"date": "2090-03-15"}, saved_id)["items"]), MAX_PRESETS)

    def test_legacy_maintenance_field_is_ignored_when_loading_and_saving(self):
        item = exported_preset("旧方案", {"date": "2002-04-21", "maintenance_sleep": "true"})
        atomic_write_json(self.path, {"schema_version": 1, "items": [item]})
        loaded, = load_trip_presets(self.data_dir)["items"]
        self.assertEqual(loaded["config"]["date"], "2002-04-21")
        self.assertNotIn("maintenance_sleep", loaded["config"])
        saved = save_trip_preset(self.data_dir, "旧方案", item["config"], item["id"])
        self.assertEqual(saved["items"], [loaded])
        self.assertNotIn("maintenance_sleep", self.path.read_text(encoding="utf-8"))

    def test_corrupt_file_is_read_safely_and_unrelated_files_are_preserved(self):
        self.path.parent.mkdir()
        settings = self.path.with_name("notification_settings.json")
        settings.write_text('{"opaque": "local"}', encoding="utf-8")
        for content in ("{invalid", '[]', '{"schema_version": true, "items": []}', '{"schema_version":1,"items":null}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                self.assertEqual(load_trip_presets(self.data_dir), {"items": []})
                self.assertEqual(self.path.read_text(encoding="utf-8"), content)
        atomic_write_json(self.path, {"schema_version": 1, "items": [
            None, exported_preset("名称非法\x00", {}), exported_preset("配置非法", {"seat_keyword": False}),
            exported_preset("有效", {"date": "2002-04-21"}),
        ]})
        self.assertEqual([item["name"] for item in load_trip_presets(self.data_dir)["items"]], ["有效"])
        self.path.write_text("broken", encoding="utf-8")
        save_trip_preset(self.data_dir, "恢复后", {})
        self.assertEqual(settings.read_text(encoding="utf-8"), '{"opaque": "local"}')

    def test_concurrent_saves_keep_both_items_and_distinct_ids(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            saved = list(pool.map(lambda name: save_trip_preset(self.data_dir, name, {}), ("行程一", "行程二")))
        self.assertEqual(len({result["saved_id"] for result in saved}), 2)
        self.assertEqual({item["name"] for item in load_trip_presets(self.data_dir)["items"]}, {"行程一", "行程二"})

    def test_reset_directory_clears_root_preset_file(self):
        save_trip_preset(self.data_dir, "本机方案", {"passengers": "本机乘车人"})
        self.assertTrue(self.path.is_file())
        reset_directory(self.data_dir, lambda: None)
        self.assertFalse(self.path.exists())
        self.assertEqual(load_trip_presets(self.data_dir), {"items": []})


class TripBundleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data_dir = directory.name
        self.preset_path = Path(self.data_dir, FILE_NAME)
        self.choices_path = Path(self.data_dir, "trip_choices.json")

    def test_export_filters_private_keys_even_if_they_were_present_on_disk(self):
        item = exported_preset("行程一", {
            "passengers": "隐藏姓名", "passenger_selections": [
                {"name": "隐藏姓名", "ticket_type": "adult", "identity_hint": "证件尾号"},
            ], "seat_keyword": "二等座", "date": "2002-04-21", "email_password": "邮件密钥", "cookies": "浏览器 Cookie",
            "notification_settings": {"server_chan_key": "推送密钥"}, "query_jobs": [{"passengers": "另一个姓名"}],
            "order_history": ["隐藏订单"], "maintenance_sleep": True,
        })
        atomic_write_json(self.preset_path, {"schema_version": 1, "items": [item]})
        atomic_write_json(self.choices_path, {"schema_version": 1,
                          "favorites": [{"from_station": "北京", "to_station": "上海", "trains": ["G1"], "token": "路线密钥"}],
                          "recent_routes": [{"from_station": "上海", "to_station": "北京", "passengers": "路线姓名"}]})
        for name, content in (("notification_settings.json", "通知密钥"), ("orders.sqlite3", "订单记录"),
                              ("cookies.json", "会话记录"), ("user_config.json", "当前乘车人")):
            Path(self.data_dir, name).write_text(content, encoding="utf-8")

        bundle = export_sanitized_bundle(self.data_dir)
        self.assertEqual(set(bundle), {"schema_version", "exported_at", "presets", "favorites", "recent_routes"})
        self.assertEqual(bundle["schema_version"], 1)
        self.assertIsInstance(bundle["exported_at"], float)
        self.assertEqual(set(bundle["presets"][0]["config"]), set(TRIP_FIELD_KEYS) - {"passengers", "passenger_selections"})
        self.assertEqual(bundle["favorites"], [{"from_station": "北京", "to_station": "上海", "trains": ["G1"]}])
        self.assertEqual(bundle["recent_routes"], [{"from_station": "上海", "to_station": "北京"}])
        serialized = json.dumps(bundle, ensure_ascii=False)
        self.assertNotIn("maintenance_sleep", serialized)
        for secret in ("隐藏姓名", "证件尾号", "邮件密钥", "浏览器 Cookie", "推送密钥", "另一个姓名", "隐藏订单",
                       "路线密钥", "路线姓名", "通知密钥", "订单记录", "会话记录", "当前乘车人", "passenger_selections"):
            self.assertNotIn(secret, serialized)

    def test_import_merges_by_name_preserves_local_ids_and_disables_automation(self):
        old = save_trip_preset(self.data_dir, "覆盖", {"passengers": "旧姓名", "auto_submit": True})["saved_id"]
        keep = save_trip_preset(self.data_dir, "保留", {"passengers": "本机姓名", "auto_alternate": True})["saved_id"]
        local_settings = Path(self.data_dir, "notification_settings.json")
        local_settings.write_bytes(b'{"secret":"only-local"}')
        local_preferences = Path(self.data_dir, "ui_preferences.json")
        local_preferences.write_bytes(b'{"maintenance_sleep":true}')
        remember_route(self.data_dir, "深圳", "广州")
        save_train_favorites(self.data_dir, "北京", "上海", ["G1"])
        save_train_favorites(self.data_dir, "深圳", "广州", ["G2"])
        bundle = {"schema_version": 1, "presets": [
            exported_preset("覆盖", {"auto_submit": True, "auto_alternate": True, "passengers": ["忽略"],
                                     "passenger_selections": {"name": "忽略"}, "date": "2099-02-01",
                                     "target_time": "08:00:00", "token": "忽略", "maintenance_sleep": "ignored"}, keep),
            exported_preset("新增", {"auto_submit": True, "auto_alternate": True, "date": "1999-04-01",
                                     "target_time": "09:00:00"}, old),
        ], "favorites": [{"from_station": "北京", "to_station": "上海", "trains": ["g1", "D3"]},
                         {"from_station": "成都", "to_station": "昆明", "trains": ["D8"]}],
            "recent_routes": [{"from_station": "深圳", "to_station": "广州"}, {"from_station": "成都", "to_station": "昆明"}],
            "notification_settings": {"secret": "foreign"}, "maintenance_sleep": False}

        result = import_sanitized_bundle(self.data_dir, bundle)
        items = {item["name"]: item for item in result["items"]}
        self.assertEqual(items["覆盖"]["id"], old)
        self.assertEqual(items["保留"]["id"], keep)
        self.assertNotIn(items["新增"]["id"], (old, keep))
        self.assertEqual(items["保留"]["config"]["passengers"], "本机姓名")
        self.assertTrue(items["保留"]["config"]["auto_alternate"])
        for name, date in (("覆盖", "2099-02-01"), ("新增", "1999-04-01")):
            config = items[name]["config"]
            self.assertEqual(config["date"], date)
            self.assertEqual(config["passengers"], "")
            self.assertEqual(config["passenger_selections"], [])
            self.assertIs(config["auto_submit"], False)
            self.assertIs(config["auto_alternate"], False)
            self.assertNotIn("maintenance_sleep", config)
        self.assertEqual(result["favorites"], [
            {"from_station": "深圳", "to_station": "广州", "trains": ["G2"]},
            {"from_station": "北京", "to_station": "上海", "trains": ["G1", "D3"]},
            {"from_station": "成都", "to_station": "昆明", "trains": ["D8"]},
        ])
        self.assertEqual([item["from_station"] for item in result["recent_routes"]], ["深圳", "成都"])
        self.assertEqual(local_settings.read_bytes(), b'{"secret":"only-local"}')
        self.assertEqual(local_preferences.read_bytes(), b'{"maintenance_sleep":true}')
        self.assertNotIn("maintenance_sleep", self.preset_path.read_text(encoding="utf-8"))
        self.assertEqual(load_trip_presets(self.data_dir), {"items": result["items"]})
        self.assertEqual(load_trip_choices(self.data_dir), {key: result[key] for key in ("favorites", "recent_routes")})
        self.assertEqual(import_sanitized_bundle(self.data_dir, bundle), result)

    def test_import_checks_preset_capacity_before_writing_either_file(self):
        for n in range(MAX_PRESETS):
            save_trip_preset(self.data_dir, f"方案 {n}", {})
        before = self.preset_path.read_bytes()
        matching = exported_preset("方案 1", {"train_code": "G102"})
        bundle = {"schema_version": 1, "presets": [matching, exported_preset("超出上限", {}, "external-2")],
                  "recent_routes": [{"from_station": "广州", "to_station": "深圳"}]}
        with self.assertRaisesRegex(ValueError, "超过 20"):
            import_sanitized_bundle(self.data_dir, bundle)
        self.assertEqual(self.preset_path.read_bytes(), before)
        self.assertFalse(self.choices_path.exists())
        result = import_sanitized_bundle(self.data_dir, {**bundle, "presets": [matching]})
        self.assertEqual(len(result["items"]), MAX_PRESETS)
        self.assertEqual(result["items"][1]["config"]["train_code"], "G102")

    def test_route_and_train_caps_keep_unrelated_local_favorites(self):
        for n in range(MAX_ROUTES):
            remember_route(self.data_dir, f"出发{n}", "终点")
            save_train_favorites(self.data_dir, f"出发{n}", "终点", [f"G{i}" for i in range(1, MAX_FAVORITES + 1)])
        before = load_trip_choices(self.data_dir)
        result = import_sanitized_bundle(self.data_dir, {"schema_version": 1,
            "favorites": [{"from_station": "出发1", "to_station": "终点", "trains": ["G99"]},
                          {"from_station": "外部", "to_station": "终点", "trains": ["G99"]}],
            "recent_routes": [{"from_station": "外部", "to_station": "终点"}],
        })
        self.assertEqual(result, {"items": [], **before})

    def test_invalid_bundle_or_entry_is_rejected_before_writing(self):
        for bundle in (None, [], {}, {"schema_version": True}, {"schema_version": 2}, {"schema_version": 1, "presets": {}},
                       {"schema_version": 1, "presets": [exported_preset("方案", {}, "../bad")]},
                       {"schema_version": 1, "presets": [exported_preset("坏\x00名称", {})]},
                       {"schema_version": 1, "presets": [exported_preset("方案", {"date": False})]},
                       {"schema_version": 1, "presets": [exported_preset("重复", {}), exported_preset("重复", {})]},
                       {"schema_version": 1, "presets": [exported_preset("方案", {})], "favorites": None},
                       {"schema_version": 1, "presets": [exported_preset("方案", {})],
                        "favorites": [{"from_station": "北京", "to_station": "上海", "trains": ["bad-code"]}]}):
            with self.subTest(bundle=bundle), self.assertRaises(ValueError):
                import_sanitized_bundle(self.data_dir, bundle)
            self.assertFalse(self.preset_path.exists())
            self.assertFalse(self.choices_path.exists())

    def test_presets_write_failure_restores_original_routes(self):
        bundle = {"schema_version": 1, "presets": [exported_preset("新增", {})],
                  "recent_routes": [{"from_station": "北京", "to_station": "上海"}]}
        for original in (None, b'{"schema_version":1,"recent_routes":[],"future_key":true}'):
            with self.subTest(original=original):
                if original is not None:
                    self.choices_path.write_bytes(original)
                with patch("railwatch_trip_presets._write_presets", side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        import_sanitized_bundle(self.data_dir, bundle)
                self.assertFalse(self.preset_path.exists())
                if original is None:
                    self.assertFalse(self.choices_path.exists())
                else:
                    self.assertEqual(self.choices_path.read_bytes(), original)
                self.assertEqual(list(Path(self.data_dir).glob(".trip-import-*")), [])

    def test_runtime_commands_manage_presets_without_saving_draft_or_starting_monitor(self):
        bridge = RailWatchBridge(data_dir=self.data_dir)
        bridge.start_monitor = Mock()
        runtime = RailWatchRuntime(bridge=bridge)
        self.addCleanup(runtime.shutdown)
        self.assertEqual(runtime._dispatch("loadTripPresets", {}), {"items": []})
        saved = runtime._dispatch("saveTripPreset", {"name": "外地行程", "config": {"passengers": "只留本机", "auto_submit": True}})
        bundle = runtime._dispatch("exportTripBundle", {})
        self.assertNotIn("只留本机", json.dumps(bundle, ensure_ascii=False))
        result = runtime._dispatch("importTripBundle", {"bundle": bundle})
        self.assertFalse(result["items"][0]["config"]["auto_submit"])
        self.assertEqual(runtime._dispatch("deleteTripPreset", {"preset_id": saved["saved_id"]}), {"items": []})
        bridge.start_monitor.assert_not_called()
        self.assertFalse(bridge.is_monitoring)
        self.assertEqual(bridge.load_trip_state()["draft"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
