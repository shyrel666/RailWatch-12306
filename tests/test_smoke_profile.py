"""The smoke tests' temporary profiles, including the Chinese-named one."""
import os
import unittest
from pathlib import Path

from scripts.smoke_profile import NON_ASCII_PROFILE, install_under_profile, temporary_profile


class SmokeProfileTests(unittest.TestCase):
    def test_plain_profile_is_a_canonical_folder_removed_afterwards(self):
        with temporary_profile("railwatch-profile-test-") as home:
            self.assertTrue(os.path.isdir(home))
            self.assertEqual(home, os.path.realpath(home))
        self.assertFalse(os.path.exists(home))

    def test_non_ascii_profile_is_named_like_a_chinese_account_with_a_space(self):
        self.assertFalse(NON_ASCII_PROFILE.isascii())
        self.assertIn(" ", NON_ASCII_PROFILE)
        with temporary_profile("railwatch-profile-test-", non_ascii=True) as home:
            self.assertEqual(os.path.basename(home), NON_ASCII_PROFILE)
            self.assertTrue(os.path.isdir(home))
            parent = os.path.dirname(home)
        self.assertFalse(os.path.exists(parent))

    def test_install_copies_the_app_folder_into_the_profile_and_returns_its_executable(self):
        with temporary_profile("railwatch-profile-test-") as source, \
                temporary_profile("railwatch-profile-test-", non_ascii=True) as home:
            bundle = Path(source) / "RailWatch 12306"
            (bundle / "resources").mkdir(parents=True)
            (bundle / "RailWatch 12306.exe").write_bytes(b"app")
            (bundle / "resources" / "app.asar").write_bytes(b"asar")
            installed = install_under_profile(bundle / "RailWatch 12306.exe", bundle, home)
            self.assertEqual(installed, Path(home) / "Programs" / "RailWatch 12306" / "RailWatch 12306.exe")
            self.assertEqual(installed.read_bytes(), b"app")
            self.assertEqual((installed.parent / "resources" / "app.asar").read_bytes(), b"asar")
            self.assertTrue((bundle / "RailWatch 12306.exe").exists(), "the original app must stay in place")


if __name__ == "__main__":
    unittest.main()
