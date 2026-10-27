"""Work done while no task runs: idle login probes and sale-start reminders."""
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_policies import IDLE_POLICIES, validate_idle_policies
from railwatch_preferences import load_ui_preferences, save_ui_preferences
from railwatch_sale_reminders import FILE_NAME, SaleReminders

NOW = 1_800_000_000.0
LEAD = IDLE_POLICIES["sale_reminder_lead_minutes"] * 60


class SaleReminderStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SaleReminders(self.temp.name)

    def test_one_reminder_per_route_and_date_and_a_limit(self):
        self.store.add("上海虹桥", "北京南", "2026-12-01", NOW + 3600, NOW, 2)
        items = self.store.add(" 上海虹桥 ", "北京南", "2026-12-01", NOW + 7200, NOW, 2)
        self.assertEqual([(item["from_station"], item["sale_at"]) for item in items], [("上海虹桥", NOW + 7200)])
        self.store.add("上海虹桥", "北京南", "2026-12-02", NOW + 9000, NOW, 2)
        with self.assertRaisesRegex(ValueError, "最多设置 2 个"):
            self.store.add("上海虹桥", "北京南", "2026-12-03", NOW + 9999, NOW, 2)

    def test_invalid_or_already_open_dates_are_rejected(self):
        for args, message in ((("上海", "上海", "2026-12-01", NOW + 60), "不能相同"), (("上海", "北京", "2026-13-01", NOW + 60), "日期"),
                              (("", "北京", "2026-12-01", NOW + 60), "站名"), (("上海", "北京", "2026-12-01", NOW), "已经开售")):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, message):
                self.store.add(*args, NOW, 20)

    def test_due_covers_the_lead_window_only_and_never_a_started_sale(self):
        soon = self.store.add("上海", "北京", "2026-12-01", NOW + LEAD - 1, NOW, 20)[0]
        self.store.add("上海", "北京", "2026-12-02", NOW + LEAD + 60, NOW, 20)
        self.assertEqual([item["id"] for item in self.store.due(NOW, LEAD)], [soon["id"]])
        self.store.update(soon["id"], NOW, notified_at=NOW)
        self.assertEqual(self.store.due(NOW, LEAD), [])
        # After the sale starts the reminder drops out; it is not sent late.
        self.assertEqual(self.store.items(NOW + LEAD + 61), [])

    def test_remove_and_unreadable_files(self):
        item = self.store.add("上海", "北京", "2026-12-01", NOW + 3600, NOW, 20)[0]
        self.assertEqual(self.store.remove(item["id"], NOW), [])
        with open(os.path.join(self.temp.name, FILE_NAME), "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "items": [{"id": "x", "from_station": "上海"}, "junk"]}, handle)
        self.assertEqual(self.store.items(NOW), [])


class IdleBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events = []
        self.bridge = RailWatchBridge(data_dir=self.temp.name, event_callback=self.events.append)
        self.bridge.notification_service.enqueue = Mock(return_value={})
        # The login probe is opt-in; these tests cover a user who turned it on.
        save_ui_preferences(self.temp.name, {"idle_keep_alive": True})

    def notices(self):
        return [event["payload"] for event in self.events if event["event"] == "notify"]

    def test_due_reminder_is_sent_once_with_desktop_and_external_notices(self):
        self.bridge._official_sale_at = Mock(return_value=NOW + 1200)
        with patch("railwatch_bridge.time.time", return_value=NOW):
            self.bridge.add_sale_reminder("上海虹桥", "北京南", "2026-12-01")
            self.bridge._remind_sales()
            self.bridge._remind_sales()
        notices = self.notices()
        self.assertEqual(len(notices), 1)
        self.assertEqual((notices[0]["title"], notices[0]["priority"]), ("起售提醒", "notice"))
        self.assertIn("上海虹桥→北京南 2026-12-01 的车票将在", notices[0]["message"])
        self.assertIn("约 20 分钟后", notices[0]["message"])
        self.assertIn("尚未确认登录", notices[0]["message"])
        self.assertEqual(self.bridge.notification_service.enqueue.call_args.kwargs["event_type"], "sale_reminder")
        self.assertIsNotNone(self.bridge.list_sale_reminders()["items"][0]["notified_at"])

    def test_a_later_official_time_postpones_the_reminder(self):
        self.bridge._official_sale_at = Mock(return_value=NOW + 1200)
        with patch("railwatch_bridge.time.time", return_value=NOW):
            self.bridge.add_sale_reminder("上海虹桥", "北京南", "2026-12-01")
            self.bridge._official_sale_at.return_value = NOW + 1200 + 3600
            self.bridge._remind_sales()
            self.assertEqual(self.notices(), [])
            self.assertEqual(self.bridge.list_sale_reminders()["items"][0]["sale_at"], NOW + 4800)

    def test_unknown_official_time_refuses_a_reminder(self):
        self.bridge._official_sale_at = Mock(return_value=None)
        with self.assertRaisesRegex(ValueError, "未能确定该日期的官方起售时间"):
            self.bridge.add_sale_reminder("上海虹桥", "北京南", "2026-12-01")

    def ready_browser(self, result="expired", ready=True):
        self.bridge.driver = object()
        self.bridge._verify_login_session = Mock(return_value=result)
        self.bridge.state = self.bridge.state.with_login_verified(ready, "")

    def test_a_confirmed_login_that_lapses_is_reported_once(self):
        self.ready_browser("expired")
        self.bridge._idle_keep_alive()
        self.assertFalse(self.bridge.state.login_ready)
        self.assertEqual([(notice["title"], notice["priority"]) for notice in self.notices()], [("12306 登录已失效", "notice")])
        self.assertEqual(self.bridge.notification_service.enqueue.call_args.kwargs["event_type"], "login_expired")
        self.bridge._idle_login_checked_at = float("-inf")
        self.bridge._idle_keep_alive()
        self.assertEqual(len(self.notices()), 1)

    def test_a_login_never_confirmed_is_not_reported_and_ok_marks_it_ready(self):
        self.ready_browser("expired", ready=False)
        self.bridge._idle_keep_alive()
        self.assertEqual(self.notices(), [])
        self.bridge._idle_login_checked_at = float("-inf")
        self.bridge._verify_login_session.return_value = "ok"
        self.bridge._idle_keep_alive()
        self.assertTrue(self.bridge.state.login_ready)
        self.assertEqual(self.notices(), [])

    def test_probe_stays_off_until_turned_on(self):
        with tempfile.TemporaryDirectory() as fresh:
            bridge = RailWatchBridge(data_dir=fresh, event_callback=self.events.append)
            bridge.notification_service.enqueue = Mock(return_value={})
            bridge.driver = object()
            bridge._verify_login_session = Mock(return_value="ok")
            bridge._idle_keep_alive()
            bridge._verify_login_session.assert_not_called()
            save_ui_preferences(fresh, {"idle_keep_alive": True})
            bridge._idle_keep_alive()
            bridge._verify_login_session.assert_called_once()

    def test_probe_waits_for_its_interval(self):
        self.ready_browser("ok")
        self.bridge._idle_keep_alive()
        self.bridge._idle_keep_alive()
        self.assertEqual(self.bridge._verify_login_session.call_count, 1)

    def test_probe_skips_a_busy_or_reserved_browser(self):
        cases = {
            "monitoring": lambda: setattr(self.bridge, "_task", Mock(active=True)),
            "browser command": lambda: setattr(self.bridge, "_browser_busy", True),
            "rehearsal": lambda: setattr(self.bridge, "_rehearsal_cancel", threading.Event()),
            "pending order": lambda: setattr(self.bridge.order_journal, "pending", Mock(return_value={"intent": {}})),
            "turned off": lambda: save_ui_preferences(self.temp.name, {"idle_keep_alive": False}),
            "no browser": lambda: setattr(self.bridge, "driver", None),
        }
        for name, block in cases.items():
            with self.subTest(name), patch.object(self.bridge, "order_journal", Mock(pending=Mock(return_value=None))):
                self.ready_browser("expired")
                block()
                self.bridge._idle_keep_alive()
                self.bridge._verify_login_session.assert_not_called()
                self.bridge._task, self.bridge._browser_busy, self.bridge._rehearsal_cancel = None, False, None
                save_ui_preferences(self.temp.name, {"idle_keep_alive": True})

    def test_probe_never_waits_for_a_browser_held_elsewhere(self):
        self.ready_browser("expired")
        held, release = threading.Event(), threading.Event()

        def hold():
            with self.bridge._driver_lock:
                held.set()
                release.wait(5)
        thread = threading.Thread(target=hold)
        thread.start()
        held.wait(5)
        try:
            self.bridge._idle_keep_alive()
        finally:
            release.set()
            thread.join()
        self.bridge._verify_login_session.assert_not_called()

    def test_tick_reports_a_failing_step_once(self):
        self.bridge._remind_sales = Mock(side_effect=OSError("磁盘已满"))
        self.bridge._idle_tick()
        self.bridge._idle_tick()
        self.assertEqual(len([entry for entry in self.bridge.log_entries if "后台检查失败：磁盘已满" in entry["message"]]), 1)


class IdlePolicyTests(unittest.TestCase):
    def test_preference_defaults_off_and_validates(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(load_ui_preferences(temp)["idle_keep_alive"])
            self.assertTrue(save_ui_preferences(temp, {"idle_keep_alive": True})["idle_keep_alive"])
            self.assertFalse(save_ui_preferences(temp, {"idle_keep_alive": False})["idle_keep_alive"])
            with self.assertRaises(ValueError):
                save_ui_preferences(temp, {"idle_keep_alive": "no"})

    def test_policy_ranges(self):
        self.assertEqual(validate_idle_policies(dict(IDLE_POLICIES)), IDLE_POLICIES)
        for key, value in (("login_keep_alive_seconds", 60), ("sale_reminder_lead_minutes", 2.5), ("max_sale_reminders", 0)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                validate_idle_policies({**IDLE_POLICIES, key: value})


if __name__ == "__main__":
    unittest.main()
