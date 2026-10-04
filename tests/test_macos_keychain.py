"""macOS notification secrets: one keychain item, read only off the startup path."""
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from railwatch_bridge import RailWatchBridge
from railwatch_preferences import (
    KEYCHAIN_ACCOUNT,
    KEYCHAIN_SERVICE,
    MacSecretStore,
    keychain_access_denied,
    protect_local_secret,
    unprotect_local_secret,
)
from railwatch_rehearsal_checks import check_alerts


class NotFound(Exception):
    """Same class name as keyring's macOS api.NotFound."""


class KeyringLocked(Exception):
    """Same class name as keyring.errors.KeyringLocked."""


class FakeBackend:
    def __init__(self):
        self.items = {}
        self.calls = []

    def get_password(self, service, account):
        self.calls.append(("get", service, account))
        return self.items.get((service, account))

    def set_password(self, service, account, value):
        self.calls.append(("set", service, account))
        self.items[(service, account)] = value

    def delete_password(self, service, account):
        self.calls.append(("delete", service, account))
        if (service, account) not in self.items:
            try:
                raise NotFound("item not found")
            except NotFound as cause:
                raise RuntimeError("Can't delete password in keychain") from cause
        del self.items[(service, account)]


class FakeStore:
    """MacSecretStore stand-in whose reads can be held to imitate an open prompt."""

    def __init__(self, values=None, read_error=None):
        self.values = values
        self.read_error = read_error
        self.release = threading.Event()
        self.release.set()
        self.calls = []

    def read_all(self):
        self.calls.append("read_all")
        self.release.wait(5)
        if self.read_error:
            raise self.read_error
        return None if self.values is None else dict(self.values)

    def write_all(self, secrets):
        self.calls.append("write_all")
        self.values = {key: value for key, value in secrets.items() if value} or None

    def delete(self):
        self.calls.append("delete")
        self.values = None


class MacSecretStoreTests(unittest.TestCase):
    def test_all_secrets_share_one_keychain_item(self):
        backend = FakeBackend()
        store = MacSecretStore(backend=backend)
        self.assertIsNone(store.read_all())
        store.write_all({"email_password": "mail", "server_chan_key": "send", "wecom_webhook_url": ""})
        self.assertEqual(list(backend.items), [(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)])
        self.assertEqual(store.read_all(), {"email_password": "mail", "server_chan_key": "send"})

    def test_writing_no_secrets_deletes_the_item_and_missing_items_are_not_errors(self):
        backend = FakeBackend()
        store = MacSecretStore(backend=backend)
        store.write_all({"email_password": "mail"})
        store.write_all({"email_password": ""})
        self.assertEqual(backend.items, {})
        store.delete()  # Already absent.

    def test_other_delete_failures_propagate(self):
        backend = FakeBackend()
        backend.delete_password = lambda *_: (_ for _ in ()).throw(KeyringLocked("denied"))
        with self.assertRaises(KeyringLocked):
            MacSecretStore(backend=backend).delete()

    def test_malformed_item_is_rejected(self):
        backend = FakeBackend()
        backend.items[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] = "not json"
        with self.assertRaisesRegex(ValueError, "格式无效"):
            MacSecretStore(backend=backend).read_all()

    def test_denied_access_is_recognised_through_wrapped_errors(self):
        try:
            try:
                raise KeyringLocked("user denied")
            except KeyringLocked as cause:
                raise RuntimeError("wrapped") from cause
        except RuntimeError as exc:
            self.assertTrue(keychain_access_denied(exc))
        self.assertFalse(keychain_access_denied(RuntimeError("other")))


@patch("railwatch_preferences.uses_system_keychain", return_value=True)
class KeychainMarkerTests(unittest.TestCase):
    def test_protect_writes_only_a_slot_marker(self, _):
        self.assertEqual(protect_local_secret("mail", "email_password"), "keychain:email_password")
        self.assertEqual(protect_local_secret("", "email_password"), "")
        with self.assertRaises(RuntimeError):
            protect_local_secret("mail")

    def test_windows_blobs_and_wrong_markers_are_rejected(self, _):
        with self.assertRaisesRegex(ValueError, "来自 Windows"):
            unprotect_local_secret("dpapi:YWJj", "email_password")
        with self.assertRaisesRegex(ValueError, "标记无效"):
            unprotect_local_secret("keychain:server_chan_key", "email_password")
        with self.assertRaisesRegex(ValueError, "后台读取"):
            unprotect_local_secret("keychain:email_password", "email_password")

    def test_other_platforms_cannot_read_keychain_markers(self, mocked):
        mocked.return_value = False
        with self.assertRaisesRegex(ValueError, "macOS 钥匙串"):
            unprotect_local_secret("keychain:email_password", "email_password")


@patch("railwatch_preferences.uses_system_keychain", return_value=True)
class KeychainBridgeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        # clear_local_data only accepts the real, canonical app data directory name.
        self.data_dir = os.path.join(os.path.realpath(directory.name), "railwatch-12306")
        os.makedirs(self.data_dir)
        self.path = os.path.join(self.data_dir, "notification_settings.json")

    def write_settings(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def read_settings(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def bridge(self, store):
        finished = threading.Event()
        events = []

        def callback(event):
            events.append(event)
            if event["event"] == "notificationCredentials":
                finished.set()

        bridge = RailWatchBridge(data_dir=self.data_dir, event_callback=callback, secret_store=store)
        return bridge, finished, events

    def test_saved_secrets_live_in_the_keychain_and_the_file_keeps_markers(self, _):
        store = FakeStore()
        bridge, _, _ = self.bridge(store)
        bridge.save_preferences("dark", {"email_enabled": True, "email_password": "mail-secret", "server_chan_key": "send"})
        persisted = self.read_settings()
        self.assertEqual(persisted["email_password"], "keychain:email_password")
        self.assertEqual(persisted["server_chan_key"], "keychain:server_chan_key")
        self.assertEqual(persisted["wecom_webhook_url"], "")
        self.assertNotIn("mail-secret", json.dumps(persisted))
        self.assertEqual(store.values, {"email_password": "mail-secret", "server_chan_key": "send"})
        writes = store.calls.count("write_all")
        bridge.save_preferences(notification_settings={"sound_loop": False})
        self.assertEqual(store.calls.count("write_all"), writes)  # Unchanged secrets skip the keychain.

    def test_construction_never_touches_the_keychain(self, _):
        self.write_settings({"email_enabled": True, "email_password": "keychain:email_password"})
        store = FakeStore({"email_password": "mail"})
        with patch.object(RailWatchBridge, "_start_keychain_preload"):
            bridge = RailWatchBridge(data_dir=self.data_dir, secret_store=store)
        self.assertEqual(store.calls, [])
        self.assertTrue(bridge.notification_credentials_pending)
        self.assertEqual(bridge.notification_service.settings["email_password"], "")
        self.assertTrue(bridge.load_preferences()["notification_settings"]["email_password_configured"])

    def test_background_read_waits_for_authorization_without_blocking_commands(self, _):
        self.write_settings({"email_enabled": True, "email_password": "keychain:email_password", "email_user": "me"})
        store = FakeStore({"email_password": "mail"})
        store.release.clear()  # The authorization prompt is still open.
        bridge, finished, events = self.bridge(store)
        self.assertTrue(bridge.notification_credentials_pending)
        self.assertEqual(check_alerts(bridge.notification_service.settings, {}, True)["status"], "warn")
        self.assertEqual(bridge.save_preferences("light")["theme"], "light")
        with self.assertRaisesRegex(RuntimeError, "钥匙串授权尚未完成"):
            bridge.save_preferences(notification_settings={"email_password": "new"})
        store.release.set()
        self.assertTrue(finished.wait(5))
        self.assertFalse(bridge.notification_credentials_pending)
        self.assertEqual(bridge.notification_service.settings["email_password"], "mail")
        self.assertTrue(bridge.notification_service.settings["email_enabled"])
        self.assertEqual([event["payload"]["status"] for event in events if event["event"] == "notificationCredentials"], ["ready"])
        writes = store.calls.count("write_all")
        bridge.save_preferences(notification_settings={"desktop_urgent": False})
        self.assertEqual(store.calls.count("write_all"), writes)

    def test_denied_or_missing_credentials_disable_external_channels(self, _):
        for name, store, status in (
            ("denied", FakeStore(read_error=KeyringLocked("user denied")), "denied"),
            ("missing", FakeStore(None), "missing"),
        ):
            with self.subTest(name):
                self.write_settings({"email_enabled": True, "server_chan_enabled": True,
                                     "email_password": "keychain:email_password", "email_user": "me"})
                bridge, finished, events = self.bridge(store)
                self.assertTrue(finished.wait(5))
                settings = bridge.notification_service.settings
                self.assertFalse(settings["email_enabled"] or settings["server_chan_enabled"])
                self.assertEqual(settings["email_password"], "")
                self.assertEqual(settings["email_user"], "me")
                self.assertEqual(events[-1]["payload"]["status"], status)
                self.assertTrue(any(entry["level"] == "WARN" and "通知设置无法读取" in entry["message"]
                                    for entry in bridge.log_entries))
                self.assertFalse(bridge.load_preferences()["notification_settings"]["email_password_configured"])
                self.assertEqual(self.read_settings()["email_password"], "keychain:email_password")

    def test_legacy_plaintext_is_migrated_in_the_background(self, _):
        self.write_settings({"server_chan_enabled": True, "server_chan_key": "plain-key"})
        store = FakeStore()
        bridge, finished, _ = self.bridge(store)
        self.assertEqual(bridge.notification_service.settings["server_chan_key"], "plain-key")
        self.assertTrue(finished.wait(5))
        self.assertNotIn("read_all", store.calls)  # Nothing stored yet, so no read prompt.
        self.assertEqual(store.values, {"server_chan_key": "plain-key"})
        self.assertEqual(self.read_settings()["server_chan_key"], "keychain:server_chan_key")
        self.assertTrue(bridge.notification_service.settings["server_chan_enabled"])

    def test_windows_blob_on_macos_is_rejected_at_startup_without_keychain_access(self, _):
        self.write_settings({"email_enabled": True, "email_password": "dpapi:YWJj"})
        store = FakeStore()
        bridge, _, _ = self.bridge(store)
        self.assertFalse(bridge.notification_service.settings["email_enabled"])
        self.assertFalse(bridge.notification_credentials_pending)
        self.assertEqual(store.calls, [])
        self.assertTrue(any("通知设置无法读取" in entry["message"] for entry in bridge.log_entries))

    def test_clearing_data_skips_keychain_deletion_while_authorization_is_open(self, _):
        self.write_settings({"email_password": "keychain:email_password"})
        store = FakeStore({"email_password": "mail"})
        store.release.clear()
        bridge, _, events = self.bridge(store)
        with patch("railwatch_bridge.release_orphan_browsers"):
            result = bridge.clear_local_data(confirmed=True)
        self.assertNotIn("delete", store.calls)
        self.assertIn("钥匙串授权尚未完成", result["warning"])
        self.assertFalse(result["cleanup_pending"])
        store.release.set()
        bridge_thread = [thread for thread in threading.enumerate() if thread.name == "railwatch-keychain"]
        for thread in bridge_thread:
            thread.join(5)
        self.assertFalse([event for event in events if event["event"] == "notificationCredentials"])
        self.assertEqual(bridge.notification_service.settings["email_password"], "")
        with patch("railwatch_bridge.release_orphan_browsers"):
            result = bridge.clear_local_data(confirmed=True)
        self.assertIn("delete", store.calls)
        self.assertEqual(result["warning"], "")

    def test_keychain_write_failure_keeps_the_previous_file_and_service(self, _):
        store = FakeStore()
        bridge, _, _ = self.bridge(store)
        bridge.save_preferences(notification_settings={"email_password": "old"})
        before = self.read_settings()
        store.write_all = lambda _secrets: (_ for _ in ()).throw(KeyringLocked("denied"))
        with self.assertRaisesRegex(RuntimeError, "钥匙串写入失败"):
            bridge.save_preferences(notification_settings={"email_password": "new"})
        self.assertEqual(self.read_settings(), before)
        self.assertEqual(bridge.notification_service.settings["email_password"], "old")


if __name__ == "__main__":
    unittest.main()
