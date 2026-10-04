"""v0.4.2 foundation: patch semantics, concurrent saves and legacy recovery."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from unittest.mock import patch

from railwatch_bridge import RailWatchBridge
from railwatch_config_contract import CONFIG_VERSION, validate_config, validate_trip_draft
from railwatch_dates import eligible_travel_dates
from railwatch_orders import OrderIntent, OrderResult
from railwatch_preferences import (
    TRIP_DRAFT_FILE,
    UI_PREFERENCES_FILE,
    load_trip_draft,
    load_ui_preferences,
    save_theme_preference,
    save_ui_preferences,
)
from railwatch_runtime import RailWatchRuntime


class PreferencePatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bridge = RailWatchBridge(data_dir=self.directory.name)
        self.responses = []
        self.runtime = RailWatchRuntime(bridge=self.bridge, writer=self.responses.append)
        self.addCleanup(self.runtime.shutdown)

    def request(self, payload):
        self.runtime.handle_line(json.dumps({"id": "test", "command": "savePreferences", "payload": payload})).result(timeout=5)
        response = self.responses[-1]
        self.assertTrue(response["ok"], response)
        return response["result"]

    def test_notification_only_ipc_patch_preserves_theme_and_tray(self):
        self.request({"theme": "dark", "close_to_tray": True})
        result = self.request({"notification_settings": {"sound_loop": False}})
        self.assertEqual(result["theme"], "dark")
        self.assertTrue(result["close_to_tray"])
        self.assertFalse(result["notification_settings"]["sound_loop"])
        restored = RailWatchBridge(data_dir=self.directory.name).load_preferences()
        self.assertEqual(result, restored)

    def test_theme_only_patch_preserves_tray_notifications_and_unknown_disk_fields(self):
        path = Path(self.directory.name, UI_PREFERENCES_FILE)
        path.write_text(json.dumps({"future_ui": {"density": "compact"}}), encoding="utf-8")
        self.request({"close_to_tray": True, "notification_settings": {"sound_loop": False, "window_attention": False}})
        result = self.request({"theme": "dark"})
        self.assertTrue(result["close_to_tray"])
        self.assertFalse(result["notification_settings"]["sound_loop"])
        self.assertFalse(result["notification_settings"]["window_attention"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["future_ui"], {"density": "compact"})
        self.assertNotIn("future_ui", result)

    def test_empty_patch_does_not_rewrite_preferences(self):
        self.request({"theme": "dark"})
        with patch("railwatch_bridge.atomic_write_json") as notifications, patch("railwatch_preferences.atomic_write_json") as ui:
            result = self.request({})
        self.assertEqual(result["theme"], "dark")
        notifications.assert_not_called()
        ui.assert_not_called()

    def test_legacy_ui_file_defaults_do_not_expose_embedded_secrets(self):
        Path(self.directory.name, UI_PREFERENCES_FILE).write_text(
            json.dumps({"theme": "dark", "notification_settings": {"email_password": "old-secret"}}), encoding="utf-8")
        result = self.bridge.load_preferences()
        self.assertEqual(result["theme"], "dark")
        self.assertFalse(result["close_to_tray"])
        self.assertTrue(result["notification_settings"]["window_attention"])
        self.assertNotIn("old-secret", json.dumps(result))

    def test_secret_omission_empty_and_null_have_distinct_semantics(self):
        # Exercise public protocol semantics without a Windows-only dependency.
        with patch("railwatch_bridge.protect_local_secret", side_effect=lambda value, slot="": "protected" if value else ""):
            result = self.request({"notification_settings": {"email_password": "private-password"}})
            self.assertEqual(result["notification_settings"]["email_password"], "")
            self.assertTrue(result["notification_settings"]["email_password_configured"])
            self.request({"notification_settings": {"email_password": "", "email_password_configured": False}})
            self.assertEqual(self.bridge.notification_service.settings["email_password"], "private-password")
            self.request({"notification_settings": {"desktop_urgent": False}})
            self.assertEqual(self.bridge.notification_service.settings["email_password"], "private-password")
            result = self.request({"notification_settings": {"email_password": None}})
            self.assertFalse(result["notification_settings"]["email_password_configured"])
            self.assertEqual(self.bridge.notification_service.settings["email_password"], "")
            self.assertNotIn("private-password", Path(self.directory.name, "notification_settings.json").read_text(encoding="utf-8"))

    def test_invalid_patch_does_not_partially_change_ui(self):
        self.request({"theme": "dark"})
        for payload in ({"theme": "unknown"}, {"close_to_tray": "false"}, {"theme": "light", "notification_settings": []}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.runtime._dispatch("savePreferences", payload)
        self.assertEqual(self.bridge.load_preferences()["theme"], "dark")

    def test_secret_failure_does_not_change_any_requested_preference(self):
        self.request({"theme": "dark", "close_to_tray": True})
        before = self.bridge.load_preferences()
        with patch("railwatch_bridge.protect_local_secret", side_effect=RuntimeError("encryption failed")):
            with self.assertRaisesRegex(RuntimeError, "encryption failed"):
                self.bridge.save_preferences("light", {"email_password": "secret"}, close_to_tray=False)
        self.assertEqual(self.bridge.load_preferences(), before)

    def test_notification_replace_failure_keeps_file_and_service_in_sync(self):
        self.request({"notification_settings": {"sound_loop": False}})
        path = Path(self.directory.name, "notification_settings.json")
        before = path.read_bytes()
        with patch("railwatch_preferences.os.replace", side_effect=PermissionError("sharing violation")):
            with self.assertRaises(PermissionError):
                self.bridge.save_preferences(notification_settings={"sound_loop": True})
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.bridge.notification_service.settings["sound_loop"])

    def test_cross_file_failure_reports_error_but_keeps_committed_notification_state(self):
        self.request({"theme": "dark"})
        with patch("railwatch_preferences.atomic_write_json", side_effect=OSError("UI disk full")):
            with self.assertRaisesRegex(OSError, "UI disk full"):
                self.bridge.save_preferences("light", {"sound_loop": False})
        # Separate files commit independently; callers reload after a failure.
        restored = RailWatchBridge(data_dir=self.directory.name).load_preferences()
        self.assertEqual(restored["theme"], "dark")
        self.assertFalse(restored["notification_settings"]["sound_loop"])
        self.assertEqual(restored, self.bridge.load_preferences())

    def test_concurrent_notification_patches_merge_after_previous_commit(self):
        entered = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        real_save = self.bridge._save_notification_settings

        def delayed_save(settings):
            if not settings["sound_loop"] and settings["desktop_urgent"]:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test release timed out")
            real_save(settings)

        def second_patch():
            second_started.set()
            return self.bridge.save_preferences(notification_settings={"desktop_urgent": False})

        with patch.object(self.bridge, "_save_notification_settings", side_effect=delayed_save), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.bridge.save_preferences, notification_settings={"sound_loop": False})
            try:
                self.assertTrue(entered.wait(3))
                second = pool.submit(second_patch)
                self.assertTrue(second_started.wait(3))
                with self.assertRaises(TimeoutError):
                    second.result(timeout=0.1)
            finally:
                release.set()
            first.result(timeout=3)
            second.result(timeout=3)
        result = self.bridge.load_preferences()["notification_settings"]
        self.assertFalse(result["sound_loop"])
        self.assertFalse(result["desktop_urgent"])
        self.assertEqual(result, RailWatchBridge(data_dir=self.directory.name).load_preferences()["notification_settings"])

    def test_theme_and_tray_read_modify_write_share_one_lock(self):
        path = Path(self.directory.name, UI_PREFERENCES_FILE)
        path.write_text('{"future_ui": true}', encoding="utf-8")
        entered, release = threading.Event(), threading.Event()
        from railwatch_preferences import atomic_write_json

        def delayed_write(filename, payload):
            if payload.get("theme") == "dark" and "close_to_tray" not in payload:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test release timed out")
            atomic_write_json(filename, payload)

        with patch("railwatch_preferences.atomic_write_json", side_effect=delayed_write), ThreadPoolExecutor(max_workers=2) as pool:
            theme = pool.submit(save_theme_preference, self.directory.name, "dark")
            try:
                self.assertTrue(entered.wait(3))
                tray = pool.submit(save_ui_preferences, self.directory.name, {"close_to_tray": True})
                with self.assertRaises(TimeoutError):
                    tray.result(timeout=0.1)
            finally:
                release.set()
            theme.result(timeout=3)
            tray.result(timeout=3)
        self.assertEqual(load_ui_preferences(self.directory.name), {"theme": "dark", "close_to_tray": True, "auto_rehearsal": False})
        self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["future_ui"])


class DraftAndLegacyCompatibilityTests(unittest.TestCase):
    @staticmethod
    def draft(**overrides):
        return {"schema_version": 1, "revision": 7, "saved_at": 1780000000.5,
                "config": {"from_station_cn": "", "date": "2000-01-01", "auto_submit": False}, **overrides}

    def test_legacy_config_keeps_expired_date_and_supplies_safe_missing_fields(self):
        config = validate_config({"from_station_cn": "北京", "to_station_cn": "上海", "date": "2000-01-01"})
        self.assertEqual(config["config_version"], CONFIG_VERSION)
        self.assertEqual(config["date"], "2000-01-01")
        self.assertEqual(config["sale_at"], "")
        self.assertFalse(config["auto_submit"])
        self.assertFalse(config["auto_alternate"])
        self.assertFalse(config["timer_enabled"])
        valid, skipped = eligible_travel_dates(config["date"], config["date_range"], today=dt.date(2026, 9, 22))
        self.assertEqual(valid, [])
        self.assertTrue(all(item["reason"] == "已过期" for item in skipped))

    def test_incomplete_draft_keeps_original_fields_without_execution_validation(self):
        payload = self.draft(future_field={"value": "preserved"})
        parsed = validate_trip_draft(payload)
        self.assertEqual(parsed, payload)
        parsed["config"]["from_station_cn"] = "changed"
        self.assertEqual(payload["config"]["from_station_cn"], "")
        self.assertEqual(validate_trip_draft(self.draft(config={"date": ""}))["config"], {"date": ""})

    def test_draft_rejects_invalid_versions_revisions_and_field_types(self):
        invalid = [None, [], {}, self.draft(schema_version=True), self.draft(schema_version=2),
                   self.draft(revision=-1), self.draft(revision=True), self.draft(revision=2 ** 53),
                   self.draft(saved_at=float("nan")), self.draft(saved_at=float("inf")), self.draft(saved_at=True),
                   self.draft(saved_at=10 ** 400), self.draft(config={"interval": 10 ** 400}),
                   self.draft(config=[]), self.draft(config={"auto_submit": "false"}),
                   self.draft(config={"interval": float("nan")}), self.draft(config={"config_version": 999})]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_trip_draft(payload)

    def test_draft_missing_valid_corrupt_and_future_files_are_read_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_trip_draft(directory), {"status": "missing", "draft": None, "warning": None})
            path = Path(directory, TRIP_DRAFT_FILE)
            path.write_text(json.dumps(self.draft()), encoding="utf-8")
            self.assertEqual(load_trip_draft(directory)["draft"], self.draft())
            for content in ('{"broken":', json.dumps(self.draft(schema_version=99)), json.dumps(self.draft(saved_at=10 ** 400))):
                path.write_text(content, encoding="utf-8")
                result = load_trip_draft(directory)
                self.assertEqual(result["status"], "invalid")
                self.assertIsNone(result["draft"])
                self.assertTrue(result["warning"])
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_corrupt_draft_does_not_change_saved_config_or_pending_order(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(data_dir=directory)
            config = bridge.save_config({"from_station_cn": "北京", "to_station_cn": "上海", "date": "2000-01-01"})
            intent = OrderIntent("regular", "G101", config["date"], "北京", "上海", "二等座", ("测试乘客",))
            bridge.order_journal.begin("legacy-run", intent, config)
            bridge.order_journal.record(intent, OrderResult("pending_payment", order_id="TEST123", evidence={"matched": True}))
            Path(directory, TRIP_DRAFT_FILE).write_text("broken draft", encoding="utf-8")
            self.assertEqual(load_trip_draft(directory)["status"], "invalid")
            restored = RailWatchBridge(data_dir=directory)
            self.assertEqual(restored.load_config()["date"], "2000-01-01")
            self.assertEqual(restored.state.order["order_id"], "TEST123")
            self.assertTrue(restored.state.order["recovery_required"])
            self.assertFalse(restored.is_monitoring)
            with self.assertRaisesRegex(RuntimeError, "存在待支付或待核对订单"):
                restored.start_monitor(config)


if __name__ == "__main__":
    unittest.main()
