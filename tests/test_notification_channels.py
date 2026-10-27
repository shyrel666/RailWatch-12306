"""Shared notification channel table, phone push channels and their settings rules."""
import copy
import json
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

import railwatch_notify
from railwatch_bridge import VERIFICATION_PUSH_HINT, RailWatchBridge, order_push_summary
from railwatch_orders import OrderIntent, OrderResult
from railwatch_config_contract import (NOTIFICATION_CHANNELS, NOTIFICATION_REQUIRED_FIELDS, NOTIFICATION_SECRET_FIELDS,
                                       merge_notification_settings, validate_notification_patch)
from railwatch_notify import NotificationService
from railwatch_policies import NOTIFICATION_CHANNEL_TABLE, validate_notification_channels

EVENTS = ("hit", "verification", "payment", "alternate_active", "alternate_fulfilled", "purchase_success",
          "login_expired", "sale_reminder")
LEGACY = ("server_chan", "email", "wecom_webhook")


class NotificationChannelTableTests(unittest.TestCase):
    def test_legacy_settings_keep_their_keys_values_and_order(self):
        legacy = {
            "desktop_urgent": True, "sound_loop": True, "sound_tone": "beep", "sound_custom_file": "",
            "sound_custom_name": "", "window_attention": True,
            "server_chan_enabled": False, "server_chan_key": "",
            "email_enabled": False, "email_smtp_host": "", "email_smtp_port": 465, "email_user": "",
            "email_password": "", "email_to": "",
            "wecom_webhook_enabled": False, "wecom_webhook_url": "",
        }
        defaults = merge_notification_settings()
        self.assertEqual([(key, defaults[key]) for key in defaults if key in legacy], list(legacy.items()))
        self.assertEqual({key: defaults[key] for key in defaults if key.startswith(("bark_", "ntfy_"))}, {
            "bark_enabled": False, "bark_key": "", "bark_server": "https://api.day.app", "bark_critical": False,
            "bark_call": False, "ntfy_enabled": False, "ntfy_topic_url": "", "ntfy_token": "",
        })
        self.assertEqual(defaults["event_channels"], {event: list(NOTIFICATION_CHANNELS) for event in EVENTS})

    def test_derived_channel_lists(self):
        self.assertEqual(NOTIFICATION_CHANNELS, (*LEGACY, "bark", "ntfy"))
        self.assertEqual(NOTIFICATION_SECRET_FIELDS, ("server_chan_key", "email_password", "wecom_webhook_url",
                                                      "bark_key", "ntfy_topic_url", "ntfy_token"))
        self.assertEqual(NOTIFICATION_REQUIRED_FIELDS, {
            "server_chan": ("server_chan_key",),
            "email": ("email_smtp_host", "email_user", "email_password", "email_to"),
            "wecom_webhook": ("wecom_webhook_url",),
            "bark": ("bark_key",),
            "ntfy": ("ntfy_topic_url",),
        })

    def test_enabled_flags_and_switches_are_coerced(self):
        merged = merge_notification_settings({"server_chan_enabled": "yes", "wecom_webhook_enabled": 0, "bark_call": "on"})
        self.assertIs(merged["server_chan_enabled"], True)
        self.assertIs(merged["wecom_webhook_enabled"], False)
        self.assertIs(merged["bark_call"], True)

    def test_patch_validation_rules(self):
        for field in ("server_chan_key", "email_smtp_host", "email_user", "email_to", "bark_key", "ntfy_token"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "非法换行"):
                validate_notification_patch({field: "a\nb"})
        for field in ("email_password", "wecom_webhook_url"):
            self.assertEqual(validate_notification_patch({field: "a\nb"}), {field: "a\nb"})
        for field in NOTIFICATION_SECRET_FIELDS:
            self.assertEqual(validate_notification_patch({field: None}), {field: None})
        with self.assertRaisesRegex(ValueError, "通知字段无效"):
            validate_notification_patch({"email_smtp_host": None})
        with self.assertRaisesRegex(ValueError, "^SMTP 端口必须在 1 至 65535 之间。$"):
            validate_notification_patch({"email_smtp_port": 0})
        for field in ("email_enabled", "bark_critical"):
            with self.assertRaisesRegex(ValueError, "通知开关必须为布尔值"):
                validate_notification_patch({field: "true"})
        with self.assertRaisesRegex(ValueError, "未知通知设置字段"):
            validate_notification_patch({"dingtalk_webhook": "x"})
        with self.assertRaisesRegex(ValueError, "未知通知设置字段"):
            validate_notification_patch({"event_channels_seeded": []})

    def test_addresses_must_be_https(self):
        for value in ("http://api.day.app", "https://", "ftp://ntfy.sh/t", "https://ntfy.sh/a b", "api.day.app"):
            for field in ("bark_server", "ntfy_topic_url"):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "https://"):
                    validate_notification_patch({field: value})
        self.assertEqual(validate_notification_patch({"bark_server": ""}), {"bark_server": ""})
        self.assertEqual(validate_notification_patch({"ntfy_topic_url": "https://ntfy.example/sub/topic"}),
                         {"ntfy_topic_url": "https://ntfy.example/sub/topic"})

    def test_ntfy_address_must_name_a_topic_the_sender_can_use(self):
        # Saved only when the sender would post it; otherwise every push would fail silently.
        for value in ("https://ntfy.sh", "https://ntfy.sh/", "https://ntfy.sh/rail?auth=tk", "https://ntfy.sh/rail.json",
                      "https://ntfy.sh/" + "a" * 65):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "主题名仅含"):
                validate_notification_patch({"ntfy_topic_url": value})
        for value in ("https://ntfy.sh/rail", "https://ntfy.sh/rail/", "https://ntfy.example/sub/rail_topic-1"):
            with self.subTest(value=value):
                self.assertEqual(validate_notification_patch({"ntfy_topic_url": value}), {"ntfy_topic_url": value})
        self.assertEqual(validate_notification_patch({"ntfy_topic_url": None}), {"ntfy_topic_url": None})

    def test_every_channel_has_a_sender(self):
        for channel in NOTIFICATION_CHANNELS:
            self.assertTrue(callable(getattr(NotificationService, f"_send_{channel}", None)), channel)

    def test_malformed_tables_are_rejected(self):
        def broken(edit):
            table = copy.deepcopy(NOTIFICATION_CHANNEL_TABLE)
            edit(table["channels"])
            return table

        cases = {
            "false flag": lambda c: c["email"]["fields"]["email_user"].update(secret=False),
            "unprefixed field": lambda c: c["email"]["fields"].update(smtp_host={"label": "x"}),
            "reserved suffix": lambda c: c["email"]["fields"].update(email_x_enabled={"label": "x"}),
            # "email_x_to" carries both the "email_" and the "email_x_" prefix.
            "duplicate field": lambda c: (c["email"]["fields"].update(email_x_to={"label": "x"}),
                                          c.update(email_x={"label": "x", "fields": {"email_x_to": {"label": "x"}}})),
            "unknown type": lambda c: c["email"]["fields"]["email_user"].update(type="number"),
            "secret port": lambda c: c["email"]["fields"]["email_smtp_port"].update(secret=True),
            "port default type": lambda c: c["email"]["fields"]["email_smtp_port"].update(default="465"),
            "switch without default": lambda c: c["bark"]["fields"]["bark_call"].pop("default"),
            "required switch": lambda c: c["bark"]["fields"]["bark_call"].update(required=True),
            "multiline url": lambda c: c["bark"]["fields"]["bark_server"].update(allow_newline=True),
            "missing label": lambda c: c["server_chan"].update(label=""),
            "bad channel id": lambda c: c.update({"Pushy": {"label": "x", "fields": {"Pushy_key": {"label": "x"}}}}),
        }
        for name, edit in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                validate_notification_channels(broken(edit))
        self.assertIs(validate_notification_channels(NOTIFICATION_CHANNEL_TABLE), NOTIFICATION_CHANNEL_TABLE)


class EventSeedingTests(unittest.TestCase):
    def test_saved_settings_without_a_record_gain_new_channels_on_every_event(self):
        saved = {"event_channels": {"hit": ["email"], "payment": []}}
        merged = merge_notification_settings(saved)
        self.assertEqual(merged["event_channels"]["hit"], ["email", "bark", "ntfy"])
        self.assertEqual(merged["event_channels"]["payment"], ["bark", "ntfy"])
        self.assertEqual(merged["event_channels_seeded"], list(NOTIFICATION_CHANNELS))
        self.assertEqual(saved, {"event_channels": {"hit": ["email"], "payment": []}})

    def test_unchecking_after_seeding_sticks(self):
        merged = merge_notification_settings({"event_channels": {"hit": ["email"]}})
        merged["event_channels"]["hit"] = ["email"]
        self.assertEqual(merge_notification_settings(merged)["event_channels"]["hit"], ["email"])

    def test_only_unrecorded_channels_are_seeded(self):
        merged = merge_notification_settings({"event_channels": {"hit": []}, "event_channels_seeded": [*LEGACY, "bark"]})
        self.assertEqual(merged["event_channels"]["hit"], ["ntfy"])


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class PhoneSenderTests(unittest.TestCase):
    def send(self, channel, settings, reply, urgent):
        logs, requests = [], []
        service = NotificationService(settings, logs.append)
        self.addCleanup(service.close)

        def fake_open(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(reply)

        with patch.object(railwatch_notify._PUSH_OPENER, "open", fake_open):
            ok = getattr(service, f"_send_{channel}")("RailWatch 有票", "G1 二等座", service.settings, urgent)
        return ok, requests, logs

    def test_bark_levels_follow_urgency_and_options(self):
        base = {"bark_enabled": True, "bark_key": "device-key"}
        cases = [
            (base, False, {"level": "active"}),
            (base, True, {"level": "timeSensitive"}),
            ({**base, "bark_critical": True, "bark_call": True}, True, {"level": "critical", "call": "1"}),
            ({**base, "bark_critical": True, "bark_call": True}, False, {"level": "active"}),
        ]
        for settings, urgent, expected in cases:
            with self.subTest(settings=settings, urgent=urgent):
                ok, [(request, timeout)], logs = self.send("bark", settings, {"code": 200}, urgent)
                self.assertTrue(ok)
                self.assertEqual(request.full_url, "https://api.day.app/push")
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(request.get_header("Content-type"), "application/json")
                self.assertEqual(timeout, 8)
                self.assertEqual(json.loads(request.data), {"device_key": "device-key", "title": "RailWatch 有票",
                                                            "body": "G1 二等座", "group": "RailWatch", **expected})
                self.assertNotIn("device-key", " ".join(logs))

    def test_bark_uses_a_self_hosted_https_server_and_refuses_plain_http(self):
        settings = {"bark_enabled": True, "bark_key": "k", "bark_server": "https://bark.example/base/"}
        ok, [(request, _)], _ = self.send("bark", settings, {"code": 200}, True)
        self.assertTrue(ok)
        self.assertEqual(request.full_url, "https://bark.example/base/push")
        ok, requests, _ = self.send("bark", {**settings, "bark_server": "http://bark.example"}, {"code": 200}, True)
        self.assertFalse(ok)
        self.assertEqual(requests, [])

    def test_bark_rejected_reply_fails_without_logging_the_key(self):
        ok, _, logs = self.send("bark", {"bark_key": "device-key"}, {"code": 400, "message": "device-key invalid"}, True)
        self.assertFalse(ok)
        self.assertEqual(logs, ["Bark 通知失败，请检查渠道配置。"])

    def test_ntfy_posts_json_to_the_server_root_with_priority_and_token(self):
        settings = {"ntfy_topic_url": "https://ntfy.example/sub/rail_topic", "ntfy_token": "tk_secret"}
        for urgent, priority in ((True, 5), (False, 3)):
            with self.subTest(urgent=urgent):
                ok, [(request, _)], logs = self.send("ntfy", settings, {"id": "abc"}, urgent)
                self.assertTrue(ok)
                self.assertEqual(request.full_url, "https://ntfy.example/sub/")
                self.assertEqual(request.get_header("Authorization"), "Bearer tk_secret")
                self.assertEqual(json.loads(request.data), {"topic": "rail_topic", "title": "RailWatch 有票",
                                                            "message": "G1 二等座", "priority": priority})
                self.assertNotIn("tk_secret", " ".join(logs))
                self.assertNotIn("rail_topic", " ".join(logs))

    def test_ntfy_without_token_sends_no_authorization_and_needs_a_topic(self):
        ok, [(request, _)], _ = self.send("ntfy", {"ntfy_topic_url": "https://ntfy.sh/rail"}, {"id": "x"}, True)
        self.assertTrue(ok)
        self.assertIsNone(request.get_header("Authorization"))
        for url in ("https://ntfy.sh/", "https://ntfy.sh/bad topic", "http://ntfy.sh/rail", "https://ntfy.sh/rail?auth=tk"):
            with self.subTest(url=url):
                ok, requests, logs = self.send("ntfy", {"ntfy_topic_url": url}, {"id": "x"}, True)
                self.assertFalse(ok)
                self.assertEqual(requests, [])
                # The reason is logged, never the address itself.
                self.assertEqual(logs, ["ntfy 主题地址格式无效，请检查渠道配置。"])

    def test_urgency_follows_the_event_type(self):
        service = NotificationService({"bark_enabled": True, "bark_key": "k"})
        self.addCleanup(service.close)
        service._send_bark = Mock(return_value=True)
        for event, urgent in (("hit", True), ("payment", True), ("verification", True), ("purchase_success", False)):
            service.enqueue("t", "m", event_type=event, event_key=event)
            service._executors["bark"].submit(lambda: None).result(timeout=2)
            self.assertIs(service._send_bark.call_args.args[3], urgent, event)


class RedirectTests(unittest.TestCase):
    def test_push_requests_never_follow_a_redirect(self):
        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                hits.append(self.path)
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(307)
                self.send_header("Location", "/elsewhere")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            railwatch_notify._post_json(f"http://127.0.0.1:{server.server_port}/push", {"a": 1})
        self.assertEqual(caught.exception.code, 307)
        self.assertEqual(hits, ["/push"])


class PushContentTests(unittest.TestCase):
    def test_order_summary_names_the_trip_without_passengers(self):
        intent = SimpleNamespace(kind="regular", train_code="G1", date="2026-10-20", seat="二等座",
                                 from_station="北京南", to_station="上海虹桥", combinations=(), passengers=("张三",))
        self.assertEqual(order_push_summary(intent), "G1 2026-10-20 二等座 北京南→上海虹桥")
        alternate = SimpleNamespace(**{**vars(intent), "kind": "alternate", "combinations": (1, 2, 3)})
        self.assertEqual(order_push_summary(alternate), "G1 2026-10-20 二等座 北京南→上海虹桥 等 3 个候补组合")

    def bridge(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        bridge = RailWatchBridge(directory.name)
        self.addCleanup(bridge.notification_service.close)
        bridge._notify_async, bridge.emit = Mock(), Mock()
        return bridge

    def test_payment_push_carries_order_essentials_and_app_guidance(self):
        bridge = self.bridge()
        regular = OrderIntent("regular", "G1", "2026-10-20", "北京南", "上海虹桥", "二等座", ("张三",))
        bridge._handle_order(regular, OrderResult("pending_payment", order_id="E1"))
        (title, message), kwargs = bridge._notify_async.call_args
        self.assertEqual((title, kwargs["event_type"]), ("预订待支付", "payment"))
        self.assertTrue(message.startswith("G1 2026-10-20 二等座 北京南→上海虹桥。"))
        self.assertIn("12306 App 的未完成订单", message)
        self.assertNotIn("张三", message)
        alternate = OrderIntent("alternate", "G1", "2026-10-20", "北京南", "上海虹桥", "二等座", ("张三",))
        bridge._handle_order(alternate, OrderResult("pending_payment", order_id="E2"))
        self.assertIn("12306 App 的候补订单", bridge._notify_async.call_args.args[1])

    def test_verification_push_points_back_to_the_computer_but_the_desktop_event_does_not(self):
        bridge = self.bridge()
        bridge._handle_human_action({"title": "需要人工操作", "message": "请完成滑块核验"})
        self.assertEqual(bridge._notify_async.call_args.args, ("需要人工操作", f"请完成滑块核验\n{VERIFICATION_PUSH_HINT}"))
        human = [call.args[1] for call in bridge.emit.call_args_list if call.args[0] == "humanAction"][0]
        self.assertEqual(human["message"], "请完成滑块核验")


if __name__ == "__main__":
    unittest.main()
