import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from railwatch_preferences import (
    UI_PREFERENCES_FILE,
    atomic_write_json,
    load_theme_preference,
    protect_local_secret,
    save_theme_preference,
    unprotect_local_secret,
)


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

    def test_failed_atomic_write_preserves_the_previous_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_theme_preference(temp_dir, "dark")
            with patch("railwatch_preferences.json.dump", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    save_theme_preference(temp_dir, "light")
            self.assertEqual(load_theme_preference(temp_dir), "dark")

    def test_replace_failure_does_not_close_a_reused_descriptor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_theme_preference(temp_dir, "dark")
            path = os.path.join(temp_dir, UI_PREFERENCES_FILE)
            descriptors = []

            def fail_replace(*_args):
                worker = threading.Thread(target=lambda: descriptors.append(os.open(path, os.O_RDONLY)))
                worker.start()
                worker.join()
                self.assertEqual(descriptors[0], fdopen.call_args.args[0])
                raise PermissionError("sharing violation")

            try:
                with patch("railwatch_preferences.os.fdopen", wraps=os.fdopen) as fdopen, \
                     patch("railwatch_preferences.os.replace", side_effect=fail_replace):
                    with self.assertRaisesRegex(PermissionError, "sharing violation"):
                        save_theme_preference(temp_dir, "light")
                self.assertIn(b"dark", os.read(descriptors[0], 1024))
                self.assertEqual(load_theme_preference(temp_dir), "dark")
                self.assertEqual(os.listdir(temp_dir), [UI_PREFERENCES_FILE])
            finally:
                for descriptor in descriptors:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

    def test_fdopen_failure_closes_unclaimed_descriptor_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("railwatch_preferences.os.fdopen", side_effect=OSError("cannot open stream")) as fdopen:
                with self.assertRaisesRegex(OSError, "cannot open stream"):
                    atomic_write_json(os.path.join(temp_dir, UI_PREFERENCES_FILE), {})
            with self.assertRaises(OSError):
                os.fstat(fdopen.call_args.args[0])
            self.assertEqual(os.listdir(temp_dir), [])

    def test_fsync_failure_preserves_the_previous_file_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            save_theme_preference(temp_dir, "dark")
            with patch("railwatch_preferences.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    save_theme_preference(temp_dir, "light")
            self.assertEqual(load_theme_preference(temp_dir), "dark")
            self.assertEqual(os.listdir(temp_dir), [UI_PREFERENCES_FILE])

    @unittest.skipUnless(os.name == "nt", "DPAPI is available on Windows")
    def test_windows_dpapi_corrupt_blob_reports_a_recoverable_error(self):
        with self.assertRaisesRegex(ValueError, "当前 Windows 账户解密"):
            unprotect_local_secret("dpapi:YWJj")

    @unittest.skipUnless(os.name == "nt", "DPAPI is available on Windows")
    def test_windows_dpapi_account_mismatch_reports_a_recoverable_error(self):
        import pywintypes

        protected = protect_local_secret("test-secret")
        with patch("win32crypt.CryptUnprotectData", side_effect=pywintypes.error(13, "CryptUnprotectData", "invalid data")):
            with self.assertRaisesRegex(ValueError, "当前 Windows 账户解密"):
                unprotect_local_secret(protected)

    @unittest.skipUnless(os.name == "nt", "DPAPI is available on Windows")
    def test_windows_dpapi_round_trip_does_not_store_plaintext(self):
        protected = protect_local_secret("test-secret")
        self.assertTrue(protected.startswith("dpapi:"))
        self.assertNotIn("test-secret", protected)
        self.assertEqual(unprotect_local_secret(protected), "test-secret")


if __name__ == "__main__":
    unittest.main()
