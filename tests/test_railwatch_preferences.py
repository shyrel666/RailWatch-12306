import json
import os
import tempfile
import unittest

from railwatch_preferences import UI_PREFERENCES_FILE, load_theme_preference, save_theme_preference


class RailWatchPreferencesTests(unittest.TestCase):
    def test_all_modes_preserve_unrelated_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, UI_PREFERENCES_FILE)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"notification_settings": {"sound_loop": False}}, handle)
            for mode in ("system", "light", "dark"):
                save_theme_preference(temp_dir, mode)
                self.assertEqual(load_theme_preference(temp_dir), mode)
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["notification_settings"], {"sound_loop": False})

    def test_corrupt_preferences_fall_back_to_system(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with open(os.path.join(temp_dir, UI_PREFERENCES_FILE), "w", encoding="utf-8") as handle:
                handle.write("{invalid")
            self.assertEqual(load_theme_preference(temp_dir), "system")

    def test_theme_preference_round_trip_without_ui_framework_dependency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_theme_preference(temp_dir, "dark")

            pref_path = os.path.join(temp_dir, UI_PREFERENCES_FILE)
            self.assertTrue(os.path.exists(pref_path))

            with open(pref_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["theme"], "dark")

            self.assertEqual(load_theme_preference(temp_dir), "dark")

    def test_invalid_or_missing_theme_preference_falls_back_to_system(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(load_theme_preference(temp_dir), "system")

            pref_path = os.path.join(temp_dir, UI_PREFERENCES_FILE)
            with open(pref_path, "w", encoding="utf-8") as handle:
                json.dump({"theme": "solarized"}, handle)

            self.assertEqual(load_theme_preference(temp_dir), "system")


if __name__ == "__main__":
    unittest.main()
