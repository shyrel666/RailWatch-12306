"""Official waitlist option contracts, durable intent changes and display evidence."""
from dataclasses import asdict, replace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from selenium.common.exceptions import ElementClickInterceptedException

from railwatch_alternate_options import (NewTrainWindow, added_fulfillment_matches, canonical_deadline,
    new_train_summary_matches, normalize_windows, record_review)
from railwatch_alternate_plan import AlternateChoice
from railwatch_config_contract import automation_config_issue, validate_config as normalize_config
from railwatch_new_trains import set_new_trains
from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_bridge import RailWatchBridge


class AlternateOptionTests(unittest.TestCase):
    def setUp(self):
        self.intent = OrderIntent("alternate", "G101", "2026-10-10", "北京", "上海", "二等座", ("张三",),
                                  "开车前1小时", new_train_windows=(NewTrainWindow("2026-10-10", 8, 22),))

    def test_deadline_migration_is_equivalent_and_preserves_unusable_legacy_values(self):
        for value, expected in (("开车前60分钟", "开车前1小时"), ("开车前48小时", "开车前2天"),
                                ("2026-10-10 18:00", "2026-10-10 18:00"), ("18:00", "18:00")):
            self.assertEqual(canonical_deadline(value), expected)
            config = normalize_config({"alternate_deadline": value})
            self.assertEqual(config["alternate_deadline"], expected)
        config = normalize_config({"auto_alternate": True, "train_code": "G101", "seat_keyword": "二等座",
                                   "passengers": "张三", "alternate_deadline": "18:00"})
        self.assertIn("仅支持官网提供的选项", automation_config_issue(config))

    def test_added_train_windows_validate_dates_integer_hours_duplicates_and_limit(self):
        cases = [[{"date": "2026-02-30", "start_hour": 8, "end_hour": 10}],
                 [{"date": "2026-10-10", "start_hour": True, "end_hour": 10}],
                 [{"date": "2026-10-10", "start_hour": 8.5, "end_hour": 10}],
                 [{"date": "2026-10-10", "start_hour": 10, "end_hour": 10}],
                 [asdict(self.intent.new_train_windows[0])] * 2,
                 [{"date": f"2026-10-{i}", "start_hour": 0, "end_hour": 24} for i in range(10, 14)]]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_windows(value)

    def test_summary_requires_exact_route_seats_and_complete_saved_dates(self):
        valid = "乘车区间：北京 - 上海 席别类型：二等座 10月10日：8点-22点 编辑"
        self.assertTrue(new_train_summary_matches(valid, self.intent))
        for text in (valid.replace("北京", "北京南"), valid.replace("二等座", "一等座"),
                     valid.replace("22点", "24点"), valid + " 10月11日：格式变化", valid + " 10月10日：8点-22点"):
            self.assertFalse(new_train_summary_matches(text, self.intent))

    def test_added_train_fulfillment_never_uses_guessed_city_or_unbound_identity(self):
        record = {"kind": "alternate", "order_id": "E1", "state": "兑现成功", "new_train_verified": True,
                  "new_train_fulfilled": True, "passengers": ["张三"], "choices": [{"train": "G999",
                  "date": "2026-10-10", "from": "北京南", "to": "上海虹桥", "seat": "二等座", "departure": "09:30", "fulfilled": True}]}
        self.assertTrue(added_fulfillment_matches(record, self.intent, "E1"))
        for patch_value in ({"order_id": "E2"}, {"new_train_verified": False}, {"new_train_fulfilled": False},
                            {"passengers": ["李四"]}, {"state": "待兑现"}):
            self.assertFalse(added_fulfillment_matches({**record, **patch_value}, self.intent, "E1"))
        self.assertFalse(added_fulfillment_matches(record, self.intent, ""))

    def test_review_never_invents_rate_or_money_from_missing_or_malformed_fields(self):
        for rate in ("--", "101%", "-2%", "40", "40% extra"):
            self.assertEqual(record_review({"success_rate": rate})["success_rate_status"], "unavailable")
        self.assertEqual(record_review({"success_rate": "0%", "prepay_amount": "661.00"})["success_rate"], 0)
        self.assertNotIn("prepay_amount", record_review({"prepay_amount": "661元"}))

    def test_persistence_restores_conditions_and_stales_failed_review(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            journal.begin("run", self.intent, {})
            journal.mark("run", "alternate_form", self.intent.intent_id,
                         {"success_rate": 40, "success_rate_status": "available", "success_rate_observed_at": 100})
            journal.record(self.intent, OrderResult("unknown", "offline"))
            pending = OrderJournal(journal.filename).pending()
            self.assertEqual(OrderIntent.from_dict(pending["intent"]), self.intent)
            self.assertEqual(pending["result"]["review"]["success_rate_status"], "stale")
            with self.assertRaises(ValueError):
                journal.record(replace(self.intent, new_train_windows=()), OrderResult("unknown"))

    def test_deadline_reselection_retains_identity_and_rejects_after_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            journal.begin("run", self.intent, {})
            journal.record(self.intent, OrderResult("verification", review={"deadline_options": ["开车前20分钟"],
                "deadline_reselection": True, "success_rate": 40, "form_signature": "old"}))
            with self.assertRaises(ValueError):
                journal.revise_alternate_deadline(self.intent.intent_id, "开车前3天")
            journal.revise_alternate_deadline(self.intent.intent_id, "开车前20分钟")
            saved = OrderIntent.from_dict(journal.pending()["intent"])
            self.assertEqual(saved, replace(self.intent, deadline="开车前20分钟"))
            self.assertIsNone(journal.pending()["result"]["review"]["success_rate"])
            journal.mark("run", "alternate_submit", saved.intent_id)
            with self.assertRaises(ValueError):
                journal.revise_alternate_deadline(saved.intent_id, "开车前20分钟")

    def test_rate_refresh_updates_history_without_repeating_state_events(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            journal.begin("run", self.intent, {})
            initial = OrderResult("pending_payment", order_id="E1", evidence={"matched": True},
                                  review={"success_rate": 40, "success_rate_observed_at": 100})
            journal.record(self.intent, initial)
            count = len(journal.history_detail(self.intent.intent_id)["events"])
            journal.refresh_review(self.intent, replace(initial, review={"success_rate": 42, "success_rate_observed_at": 200}))
            self.assertEqual(journal.history_detail(self.intent.intent_id)["summary"]["review"]["success_rate"], 42)
            self.assertEqual(len(journal.history_detail(self.intent.intent_id)["events"]), count)
            journal.refresh_review(self.intent, replace(initial, order_id="E2"))
            self.assertEqual(journal.pending()["result"]["review"]["success_rate"], 42)

    def test_windows_apply_only_to_the_orders_own_dates(self):
        config = {"date": "2026-10-10", "from_station_cn": "北京", "to_station_cn": "上海", "passengers": "张三",
                  "alternate_deadline": "开车前1小时", "alternate_accept_new_trains": True,
                  "alternate_new_train_windows": [{"date": "2026-10-09", "start_hour": 0, "end_hour": 24},
                                                  {"date": "2026-10-10", "start_hour": 8, "end_hour": 22}]}
        # A single-choice order on 10-10 can only carry the 10-10 window.
        single = OrderIntent.from_config(config, "G101", "二等座", "alternate")
        self.assertEqual(single.new_train_windows, (NewTrainWindow("2026-10-10", 8, 22),))
        multiple_config = {**config, "alternate_mode": "multiple", "train_code": "G101,G102", "seat_keyword": "二等座",
                           "_alternate_dates": ["2026-10-10", "2026-10-09"]}
        multiple = OrderIntent.from_config(multiple_config, "G101", "二等座", "alternate")
        self.assertEqual(len(multiple.new_train_windows), 2)
        primary = AlternateChoice.from_intent(multiple)
        same_day = replace(multiple, choices=(primary, replace(primary, train_code="G102"))).for_choice_dates()
        self.assertEqual(same_day.new_train_windows, single.new_train_windows)
        spanning = replace(multiple, choices=(primary, replace(primary, date="2026-10-09"))).for_choice_dates()
        self.assertEqual(spanning.new_train_windows, multiple.new_train_windows)
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            journal.begin("run", multiple, multiple_config)
            # Binding may narrow windows to the chosen dates, never drop or add others.
            with self.assertRaises(ValueError):
                journal.bind_alternatives(replace(same_day, new_train_windows=()))
            journal.bind_alternatives(same_day)
            self.assertEqual(OrderIntent.from_dict(journal.pending()["intent"]), same_day)

    def test_a_disabled_unselected_new_train_date_does_not_block_the_selected_one(self):
        state = {"saved": False, "closed": False}
        save, close = Mock(), Mock()
        save.click.side_effect = lambda: state.update(saved=True)
        close.click.side_effect = lambda: state.update(closed=True)
        control = lambda value: {"value": value, "button": Mock(), "options": []}
        editor = {"rules": "乘车区间：北京-上海 席别：二等座", "save": save, "close": close, "rows": [
            {"date": "20261009", "checked": False, "enabled": False, "toggle": Mock(), "controls": [control("0点"), control("24点")]},
            {"date": "20261010", "checked": True, "enabled": True, "toggle": Mock(), "controls": [control("8点"), control("22点")]}]}
        page = Mock()
        page.stop.return_value = False
        page.poll.side_effect = lambda predicate, timeout=0: predicate()
        page.snapshot.return_value = {"addedTrain": True}
        page.alternate_options.side_effect = lambda: {"new_train_summary":
            "乘车区间：北京-上海 席别：二等座 10月10日：8点-22点" if state["saved"] else ""}
        page.driver.execute_script.side_effect = lambda *_: None if state["closed"] else editor
        set_new_trains(page, self.intent)
        save.click.assert_called_once()
        close.click.assert_called_once()
        editor["rows"][0]["toggle"].click.assert_not_called()

    def test_cached_options_can_be_read_while_monitoring_without_browser_access(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            try:
                snapshot = {"deadline_options": ["开车前1小时"], "from_station": "北京"}
                bridge.order_journal.mark("run", "alternate_options", detail=snapshot)
                bridge._browser_busy = True
                bridge.driver = Mock()
                self.assertEqual(bridge.read_alternate_options()["snapshot"], snapshot)
                bridge.driver.execute_script.assert_not_called()
                with self.assertRaises(RuntimeError):
                    bridge.read_alternate_options(True)
            finally:
                bridge.notification_service.close()


class AlternateConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.intent = OrderIntent("alternate", "G101", "2026-10-10", "北京", "上海", "二等座", ("张三",), "开车前1小时")
        self.marks = []
        self.page = OrderPage(Mock(), wait=lambda _: None, mark=lambda stage, detail=None: self.marks.append(stage))
        # The submitted waitlist form with a dialog listed, before any order card exists.
        self.page.snapshot = Mock(return_value={"dialogs": ["提示"], "formReady": True})
        self.dialog = OrderResult("verification", "存在未识别的订单提示")

    def wait(self, results, buttons):
        self.page._result_with_alternate_details = Mock(side_effect=results)
        self.page.alternate_confirmation = Mock(side_effect=buttons)
        return self.page.wait_result(self.intent, confirm_alternate=True)

    def test_a_click_refused_before_dispatch_is_released_and_retried(self):
        refused, accepted = Mock(), Mock()
        refused.click.side_effect = ElementClickInterceptedException("covered by a loading mask")
        result = self.wait([self.dialog, self.dialog, OrderResult("pending_payment", order_id="E1")], [refused, accepted])
        self.assertEqual(result.status, "pending_payment")
        accepted.click.assert_called_once()
        self.assertEqual(self.marks, ["alternate_confirm_attempt", "alternate_confirm_rejected", "alternate_confirm_attempt"])

    def test_a_listed_dialog_that_is_not_yet_clickable_gets_a_short_grace(self):
        button = Mock()
        result = self.wait([self.dialog] * 3 + [OrderResult("pending_payment", order_id="E1")], [None, None, button])
        self.assertEqual(result.status, "pending_payment")
        button.click.assert_called_once()
        self.assertEqual(self.marks, ["alternate_confirm_attempt"])

    def test_the_grace_is_bounded_and_a_real_verification_returns_at_once(self):
        self.page.ALTERNATE_CONFIRMATION_GRACE = 0.05
        self.page.wait = time.sleep
        self.page._result_with_alternate_details = Mock(return_value=self.dialog)
        self.page.alternate_confirmation = Mock(return_value=None)
        self.assertEqual(self.page.wait_result(self.intent, confirm_alternate=True), self.dialog)
        self.assertGreater(self.page.alternate_confirmation.call_count, 1)
        for snap in ({"dialogs": ["请完成滑块验证"], "formReady": True, "verification": True},
                     # An order card means details are being read; retrying would click them again.
                     {"dialogs": ["提示"], "formReady": True, "orders": [{"order_id": "E1"}]}):
            with self.subTest(snap=snap):
                self.page.snapshot.return_value = snap
                self.page.alternate_confirmation.reset_mock()
                self.assertEqual(self.page.wait_result(self.intent, confirm_alternate=True), self.dialog)
                self.page.alternate_confirmation.assert_called_once()
        self.assertFalse(self.marks)


if __name__ == "__main__":
    unittest.main()
