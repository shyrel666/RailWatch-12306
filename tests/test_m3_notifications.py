"""M3 notification routing, bounded delivery, and redaction."""
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_notify import NotificationService


class NotificationTests(unittest.TestCase):
    def test_channel_filters_and_deduplication(self):
        service = NotificationService({
            "server_chan_enabled": True, "server_chan_key": "test-key",
            "event_channels": {"hit": ["server_chan"], "payment": []},
        })
        sent = threading.Event()
        service._send_server_chan = Mock(side_effect=lambda *_: sent.set() or True)
        first = service.enqueue("票", "测试", event_type="hit", event_key="run:hit")
        second = service.enqueue("票", "测试", event_type="hit", event_key="run:hit")
        filtered = service.enqueue("支付", "测试", event_type="payment", event_key="run:payment")
        self.assertEqual(first["server_chan"]["status"], "queued")
        self.assertEqual(second["server_chan"]["status"], "duplicate")
        self.assertEqual(filtered["server_chan"]["status"], "disabled")
        self.assertTrue(sent.wait(2))
        self.assertEqual(service._send_server_chan.call_count, 1)

    def test_slow_channel_does_not_block_another_channel(self):
        service = NotificationService({"server_chan_enabled": True, "server_chan_key": "key",
                                       "wecom_webhook_enabled": True, "wecom_webhook_url": "https://qyapi.weixin.qq.com/test"})
        slow = threading.Event()
        fast = threading.Event()
        service._send_server_chan = Mock(side_effect=lambda *_: slow.wait(2) or True)
        service._send_wecom = Mock(side_effect=lambda *_: fast.set() or True)
        thread = threading.Thread(target=service.test_notification)
        thread.start()
        try:
            self.assertTrue(fast.wait(1), "企业微信渠道应独立于慢速 Server酱")
        finally:
            slow.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_test_payload_is_fixed_and_return_has_channel_status(self):
        service = NotificationService({"email_enabled": True, "email_smtp_host": "mail.example",
                                       "email_user": "from@example.com", "email_password": "secret", "email_to": "to@example.com"})
        service._send_email = Mock(return_value=True)
        result = service.test_notification()
        title, message, _settings = service._send_email.call_args.args
        self.assertEqual(title, "RailWatch 测试通知")
        self.assertNotIn("乘客姓名", message)
        self.assertEqual(result["email"]["status"], "success")
        self.assertIsInstance(result["email"]["sent_at"], float)
        self.assertEqual(result["server_chan"]["status"], "disabled")

    def test_failed_server_reply_does_not_log_secret(self):
        logs = []
        service = NotificationService({"server_chan_enabled": True, "server_chan_key": "secret-key"}, logs.append)
        response = Mock()
        response.read.return_value = json.dumps({"code": 1, "error": "secret-key"}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("railwatch_notify.urllib.request.urlopen", return_value=response):
            self.assertFalse(service._send_server_chan("test", "test", service.settings))
        self.assertNotIn("secret-key", " ".join(logs))

    def test_bridge_patch_keeps_theme_and_event_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(data_dir=directory)
            bridge.save_preferences(theme="dark")
            saved = bridge.save_preferences(notification_settings={"event_channels": {"hit": ["email"]}, "sound_loop": False})
            self.assertEqual(saved["theme"], "dark")
            self.assertEqual(saved["notification_settings"]["event_channels"]["hit"], ["email"])
            self.assertTrue(saved["notification_settings"]["event_channels"]["payment"])
            self.assertFalse(saved["notification_settings"]["sound_loop"])
            restored = RailWatchBridge(data_dir=directory).load_preferences()
            self.assertEqual(restored["notification_settings"]["event_channels"]["hit"], ["email"])
            with self.assertRaises(ValueError):
                bridge.save_preferences(notification_settings={"event_channels": {"hit": [["bad"]]}})


if __name__ == "__main__":
    unittest.main()
