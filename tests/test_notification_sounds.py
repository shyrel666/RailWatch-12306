"""Notification tone migration, validation and persisted partial-update semantics."""
import json
from pathlib import Path
import tempfile
import unittest

from railwatch_bridge import RailWatchBridge
from railwatch_config_contract import merge_notification_settings, validate_notification_patch


class NotificationSoundTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bridge = RailWatchBridge(data_dir=self.directory.name)
        self.addCleanup(self.bridge.notification_service.close)

    def test_old_preferences_keep_the_original_beep_and_loop_switch(self):
        settings = merge_notification_settings({"sound_loop": False})
        self.assertEqual(settings["sound_tone"], "beep")
        self.assertEqual(settings["sound_custom_file"], "")
        self.assertFalse(settings["sound_loop"])
        self.assertEqual(merge_notification_settings({"sound_tone": "unknown"})["sound_tone"], "beep")

    def test_presets_survive_restart_and_unrelated_partial_updates(self):
        for tone in ("beep", "chime", "double", "alarm"):
            with self.subTest(tone=tone):
                self.bridge.save_preferences(notification_settings={"sound_tone": tone})
                self.bridge.save_preferences(notification_settings={"sound_loop": False})
                restored = RailWatchBridge(data_dir=self.directory.name)
                self.addCleanup(restored.notification_service.close)
                settings = restored.load_preferences()["notification_settings"]
                self.assertEqual(settings["sound_tone"], tone)
                self.assertFalse(settings["sound_loop"])

    def test_custom_sound_requires_an_import_and_preserves_metadata_on_reload(self):
        with self.assertRaisesRegex(ValueError, "先导入"):
            self.bridge.save_preferences(notification_settings={"sound_tone": "custom"})
        file = "a" * 64 + ".wav"
        patch = {"sound_tone": "custom", "sound_custom_file": file, "sound_custom_name": "我的提示音.wav"}
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.bridge.save_preferences(notification_settings=patch)
        directory = Path(self.directory.name, "notification-sounds")
        directory.mkdir()
        (directory / file).write_bytes(b"fixture")
        self.bridge.save_preferences(notification_settings=patch)
        restored = RailWatchBridge(data_dir=self.directory.name)
        self.addCleanup(restored.notification_service.close)
        settings = restored.load_preferences()["notification_settings"]
        self.assertTrue(all(settings[key] == value for key, value in patch.items()))
        (directory / file).unlink()
        # A missing clip must never prevent disabling the loop or other channels.
        saved = restored.save_preferences(notification_settings={"sound_loop": False})
        self.assertFalse(saved["notification_settings"]["sound_loop"])

    def test_saving_an_imported_clip_removes_superseded_imports_only(self):
        directory = Path(self.directory.name, "notification-sounds")
        directory.mkdir()
        old, new = "a" * 64 + ".wav", "b" * 64 + ".mp3"
        (directory / old).write_bytes(b"old")
        (directory / "notes.txt").write_bytes(b"not an import")
        self.bridge.save_preferences(notification_settings={
            "sound_tone": "custom", "sound_custom_file": old, "sound_custom_name": "旧.wav"})
        (directory / new).write_bytes(b"new")
        self.bridge.save_preferences(notification_settings={
            "sound_tone": "custom", "sound_custom_file": new, "sound_custom_name": "新.mp3"})
        self.assertEqual(sorted(path.name for path in directory.iterdir()), sorted([new, "notes.txt"]))
        # A preset keeps the saved clip, so switching back to custom still works.
        self.bridge.save_preferences(notification_settings={"sound_tone": "beep"})
        self.assertTrue((directory / new).exists())

    def test_bad_audio_fields_fail_without_changing_the_previous_preferences(self):
        self.bridge.save_preferences(notification_settings={"sound_tone": "chime"})
        file = Path(self.directory.name, "notification_settings.json")
        before = json.loads(file.read_text(encoding="utf-8"))
        for patch in ({"sound_tone": "invalid"}, {"sound_tone": []}, {"sound_custom_file": "../private.wav"},
                      {"sound_custom_name": "bad\nname.wav"}, {"sound_custom_file": None}):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    self.bridge.save_preferences(notification_settings=patch)
                self.assertEqual(json.loads(file.read_text(encoding="utf-8")), before)
        self.assertEqual(validate_notification_patch({"sound_tone": "double"}), {"sound_tone": "double"})


if __name__ == "__main__":
    unittest.main()
