"""Unit tests for official 12306 pre-fill parsing, safety guards, and runtime handoff."""
import datetime as dt
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

import railwatch_prefill as prefill
from gui_12306_0 import TicketMonitor
from railwatch_bridge import RailWatchBridge
from railwatch_order_page import ConfirmationOutcome, OrderPage
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_prefill import (
    ArmedPrefillPlan,
    BEIJING_TZ,
    PrefillAdapter,
    PrefillCandidate,
    PrefillExecutionOutcome,
    PrefillFallback,
    month_day_matches,
    parse_countdown_seconds,
    parse_sale_label_timestamp,
    passengers_span_matches,
    prefill_eligible_reason,
    regular_target_seats,
)
from railwatch_rehearsal_checks import check_clock
from railwatch_run_review import build_run_review, run_conclusion
from railwatch_task import MonitorTask, TaskCancelled


SALE_1600 = dt.datetime(2026, 11, 7, 16, 0, 0, tzinfo=BEIJING_TZ).timestamp()
NOW_1550 = dt.datetime(2026, 11, 7, 15, 50, 0, tzinfo=BEIJING_TZ).timestamp()

BASE_CONFIG = {
    "from_station_cn": "北京南",
    "to_station_cn": "天津",
    "date": "2026-11-21",
    "date_range": "单日",
    "train_code": "G8821,G8863",
    "seat_keyword": "二等座,一等座,商务座",
    "passengers": "张三",
    "timer_enabled": True,
    "auto_submit": True,
    "auto_alternate": True,
    "alternate_deadline": "开车前1小时",
    "sale_at": "2026-11-07T16:00:00+08:00",
    "interval": 3,
    "smart_rate": True,
    "request_mode": "fast",
}


class PrefillParserAndGuardTests(unittest.TestCase):
    def test_parse_sale_label_timestamp_handles_minutes_newlines_and_year_rollover(self):
        self.assertEqual(
            parse_sale_label_timestamp("11月7日16点\n  起售", reference_timestamp=NOW_1550),
            SALE_1600,
        )
        self.assertEqual(
            parse_sale_label_timestamp("11月7日12点45分起售", reference_timestamp=NOW_1550),
            dt.datetime(2026, 11, 7, 12, 45, 0, tzinfo=BEIJING_TZ).timestamp(),
        )
        self.assertEqual(
            parse_sale_label_timestamp("16点起售", reference_timestamp=NOW_1550),
            SALE_1600,
        )
        dec_ref = dt.datetime(2026, 12, 31, 20, 0, 0, tzinfo=BEIJING_TZ).timestamp()
        jan_sale = dt.datetime(2027, 1, 2, 8, 30, 0, tzinfo=BEIJING_TZ).timestamp()
        self.assertEqual(
            parse_sale_label_timestamp("1月2日8点30分起售", reference_timestamp=dec_ref),
            jan_sale,
        )
        self.assertIsNone(parse_sale_label_timestamp("预订", reference_timestamp=NOW_1550))
        self.assertIsNone(parse_sale_label_timestamp("11月7日25点起售", reference_timestamp=NOW_1550))

    def test_parse_countdown_seconds(self):
        self.assertEqual(parse_countdown_seconds("18小时29分钟49秒"), 18 * 3600 + 29 * 60 + 49)
        self.assertEqual(parse_countdown_seconds(["0", "10", "05"]), 605)
        self.assertEqual(parse_countdown_seconds(["50", "04"]), 3004)
        self.assertEqual(parse_countdown_seconds(["09"]), 9)
        self.assertIsNone(parse_countdown_seconds(["60", "00"]))
        self.assertEqual(parse_countdown_seconds("12分0秒"), 720)
        self.assertEqual(parse_countdown_seconds("45秒"), 45)
        self.assertIsNone(parse_countdown_seconds("10分75秒"))
        self.assertIsNone(parse_countdown_seconds(""))

    def test_passengers_span_and_month_day_matching(self):
        self.assertTrue(passengers_span_matches("张三", ("张三",)))
        self.assertTrue(passengers_span_matches("张三、李四", ("李四", "张三")))
        self.assertTrue(passengers_span_matches("张三 李四", ("张三", "李四")))
        self.assertTrue(passengers_span_matches("张三\u3000李四", ("张三", "李四")))
        self.assertFalse(passengers_span_matches("张三丰", ("张三",)))
        self.assertFalse(passengers_span_matches("张三、李四", ("张三",)))
        self.assertTrue(month_day_matches("（11月21日  星期五）", "2026-11-21"))
        self.assertFalse(month_day_matches("（11月22日  星期六）", "2026-11-21"))

    def test_eligibility_and_regular_seat_filtering(self):
        self.assertEqual(regular_target_seats(BASE_CONFIG), ["二等座", "一等座"])
        self.assertIsNone(prefill_eligible_reason(BASE_CONFIG, SALE_1600, now=NOW_1550))
        self.assertIn("已关闭", prefill_eligible_reason({**BASE_CONFIG, "prefill_enabled": False}, SALE_1600, now=NOW_1550))
        self.assertIn("不足", prefill_eligible_reason(BASE_CONFIG, SALE_1600, now=SALE_1600 - 30))
        self.assertIsNotNone(prefill_eligible_reason({**BASE_CONFIG, "auto_submit": False}, SALE_1600, now=NOW_1550))
        self.assertIsNotNone(prefill_eligible_reason({**BASE_CONFIG, "seat_keyword": "商务座"}, SALE_1600, now=NOW_1550))
        self.assertIsNotNone(prefill_eligible_reason({**BASE_CONFIG, "train_code": ""}, SALE_1600, now=NOW_1550))

    def test_non_utc8_browser_and_rehearsal_clock_warning(self):
        driver = Mock()
        driver.execute_script.return_value = 360  # UTC-6 (getTimezoneOffset is UTC - local in minutes)
        adapter = PrefillAdapter(driver, now=lambda: NOW_1550)
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.check_browser_clock()
        self.assertEqual(ctx.exception.stage, "timezone_mismatch")

        warn_verdict = check_clock(0.2, 0.2, timezone_offset_minutes=-360, prefill_intended=True)
        self.assertEqual(warn_verdict["status"], "warn")
        self.assertTrue(any("UTC+8" in d for d in warn_verdict["details"]))
        pass_verdict = check_clock(0.2, 0.2, timezone_offset_minutes=480, prefill_intended=True)
        self.assertEqual(pass_verdict["status"], "pass")

    def test_account_conflict_protection_blocks_overwrite_without_deleting(self):
        adapter = PrefillAdapter(Mock(), now=lambda: NOW_1550)
        conflicting_editor = {
            "header_dates": ["乘车日期：2026年11月21日 星期五", "乘车日期：2026年11月22日 星期六"],
            "rows": [{"train_code": "G101", "from_station": "上海虹桥", "to_station": "杭州东", "seats": ["二等座"]}],
            "checked_names": ["李四"],
        }
        with self.assertRaises(PrefillFallback) as ctx:
            adapter._verify_no_editor_conflict(conflicting_editor, ("张三",))
        self.assertEqual(ctx.exception.stage, "account_conflict")

    def test_account_conflict_protection_covers_the_same_trip_and_allows_own_or_empty_selection(self):
        # The detail inspection can time out and report no saved pre-fill; the
        # editor is then the only place another passenger's entry is visible.
        adapter = PrefillAdapter(Mock(), now=lambda: NOW_1550)
        same_trip = {
            "header_dates": ["乘车日期：2026年11月21日 星期五"],
            "rows": [{"train_code": "G8821", "from_station": "大兴机场", "to_station": "天津西", "seats": ["二等座"]}],
        }
        with self.assertRaises(PrefillFallback) as ctx:
            adapter._verify_no_editor_conflict({**same_trip, "checked_names": ["李四"]}, ("张三",))
        self.assertEqual(ctx.exception.stage, "account_conflict")
        with self.assertRaises(PrefillFallback):
            adapter._verify_no_editor_conflict({**same_trip, "checked_names": ["张三", "李四"]}, ("张三",))
        adapter._verify_no_editor_conflict({**same_trip, "checked_names": ["张三"]}, ("张三",))
        adapter._verify_no_editor_conflict({**same_trip, "checked_names": []}, ("张三",))

    def test_countdown_mismatch_rejects_arming(self):
        adapter = PrefillAdapter(Mock(), now=lambda: SALE_1600 - 600)
        adapter._check_countdown_tolerance(603, SALE_1600, stage="detail_countdown")
        with self.assertRaises(PrefillFallback) as ctx:
            adapter._check_countdown_tolerance(18 * 3600 + 30 * 60, SALE_1600, stage="detail_countdown")
        self.assertEqual(ctx.exception.stage, "countdown_mismatch")


class PrefillExecutionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = OrderJournal(Path(self.temp.name) / "orders.sqlite3")
        self.addCleanup(lambda: self.journal.release_resume(*self.journal._resume_owner[:2])
                        if self.journal._resume_owner else None)
        self.plan = ArmedPrefillPlan(
            date="2026-11-21",
            passengers=("张三",),
            candidates=(
                PrefillCandidate("G8821", "2026-11-21", "大兴机场", "天津西", "二等座", "11月7日16点起售"),
                PrefillCandidate("G8863", "2026-11-21", "北京大兴", "天津西", "二等座", "11月7日16点起售"),
            ),
            target_timestamp=SALE_1600,
        )

    def make_adapter(self):
        driver = Mock()
        adapter = PrefillAdapter(driver, wait=lambda _: None, now=lambda: SALE_1600)
        adapter._detail_snapshot = Mock(
            return_value={
                "passengers_text": "张三",
                "dialogs": [],
                "tabs": [
                    {"index": 0, "active": True, "from_station": "大兴机场", "to_station": "天津西", "info": "（11月21日）"},
                    {"index": 1, "active": False, "from_station": "北京大兴", "to_station": "天津西", "info": "（11月21日）"},
                ]
            }
        )
        def select_tab(candidate):
            for tab in adapter._detail_snapshot.return_value["tabs"]:
                tab["active"] = tab["from_station"] == candidate.from_station
            return True
        adapter._ensure_candidate_tab = Mock(side_effect=select_tab)
        return adapter

    @staticmethod
    def settled_results(results):
        remaining = iter(results)

        def resolve(intent, page, **kwargs):
            result = next(remaining)
            if result.no_order:
                kind = "not_on_sale" if result.evidence.get("not_on_sale") else "sold_out"
                page.mark("prefill_official_rejected", {"kind": kind})
            return result
        return resolve

    def test_unlock_timeout_writes_no_journal_order_and_falls_back(self):
        adapter = self.make_adapter()
        adapter._wait_buy_button = Mock(return_value=None)
        outcome = adapter.execute_armed(self.plan, self.journal, "run-1", BASE_CONFIG)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertIsNone(self.journal.pending())
        events = [e["stage"] for e in self.journal.run_events("run-1")]
        self.assertIn("prefill_fallback", events)
        self.assertNotIn("submitting", events)

    def test_countdown_clearly_behind_falls_back_at_once_without_waiting_or_claiming(self):
        adapter = self.make_adapter()
        adapter._detail_snapshot.return_value.update(
            unonsale_visible=True, countdown_text="10秒",
            cards=[{"train_code": "G8821", "sale_label": "11月7日16点起售"}])
        adapter._wait_buy_button = Mock(return_value=Mock())
        outcome = adapter.execute_armed(self.plan, self.journal, "behind", BASE_CONFIG)
        self.assertEqual(outcome.action, "fallback_to_query")
        adapter._wait_buy_button.assert_not_called()
        self.assertIsNone(self.journal.pending())
        events = self.journal.run_events("behind")
        self.assertEqual([e["stage"] for e in events], ["prefill_fallback"])
        self.assertEqual(events[0]["detail"]["stage"], "countdown_behind")

    def test_imminent_or_ambiguous_countdown_still_waits_for_the_button(self):
        # Empty is what the live page shows in the last moments before unlocking.
        own = [{"train_code": "G8821", "sale_label": "11月7日16点起售"}]
        later = own + [{"train_code": "G8899", "sale_label": "11月7日18点起售"}]
        for index, (label, changes) in enumerate((
                ("empty", {"unonsale_visible": True, "countdown_text": "", "cards": own}),
                ("within threshold", {"unonsale_visible": True, "countdown_text": "2秒", "cards": own}),
                ("already on sale", {"unonsale_visible": False, "countdown_text": "", "cards": own}),
                ("a later sale shares the tab", {"unonsale_visible": True, "countdown_text": "1小时59分58秒", "cards": later}),
                ("unreadable sale label", {"unonsale_visible": True, "countdown_text": "10秒",
                                           "cards": [{"train_code": "G8821", "sale_label": "稍后起售"}]}))):
            with self.subTest(label):
                adapter = self.make_adapter()
                adapter._detail_snapshot.return_value.update(changes)
                adapter._wait_buy_button = Mock(return_value=None)
                outcome = adapter.execute_armed(self.plan, self.journal, f"wait-{index}", BASE_CONFIG)
                adapter._wait_buy_button.assert_called_once()
                self.assertEqual(adapter._wait_buy_button.call_args.args[1],
                                 prefill.ORDER_POLICIES["prefill_unlock_timeout_ms"] / 1000)
                self.assertEqual(outcome.action, "fallback_to_query")
                self.assertEqual(self.journal.run_events(f"wait-{index}")[-1]["detail"]["stage"], "unlock_timeout")

    def test_countdown_of_another_trip_tab_never_aborts_the_candidate(self):
        adapter = self.make_adapter()
        detail = adapter._detail_snapshot.return_value
        detail.update(unonsale_visible=True, countdown_text="10分钟",
                      cards=[{"train_code": "G8863", "sale_label": "11月7日16点起售"}])
        for tab in detail["tabs"]:
            tab["active"] = tab["from_station"] == "北京大兴"
        # The snapshot under judgement was read before the tab switch.
        adapter._ensure_candidate_tab = Mock(return_value=True)
        adapter._wait_buy_button = Mock(return_value=None)
        adapter.execute_armed(self.plan, self.journal, "other-tab", BASE_CONFIG)
        adapter._wait_buy_button.assert_called_once()

    def test_presale_retries_follow_the_policy_delays_and_share_one_task_budget(self):
        not_on_sale = OrderResult("not_submitted", "官方提示未到起售时间", no_order=True, evidence={"not_on_sale": True})
        for delays, clicks, waits in (([350, 1000], 3, [0.35, 1.0]), ([350], 2, [0.35]), ([], 1, [])):
            with self.subTest(delays=delays), patch.dict("railwatch_prefill.ORDER_POLICIES",
                                                         {"prefill_presale_retry_delays_ms": delays}):
                adapter = self.make_adapter()
                adapter.wait = Mock()
                button = Mock()
                adapter._wait_buy_button = Mock(return_value=button)
                adapter._resolve_after_buy_click = Mock(side_effect=self.settled_results([not_on_sale] * clicks))
                run_id = f"presale-{len(delays)}"
                outcome = adapter.execute_armed(self.plan, self.journal, run_id, BASE_CONFIG)
                self.assertEqual(outcome.action, "fallback_to_query")
                self.assertEqual(button.click.call_count, clicks)
                self.assertEqual([call.args[0] for call in adapter.wait.call_args_list], waits)
                self.assertIsNone(self.journal.pending())
                self.assertEqual(self.journal.run_events(run_id)[-1]["detail"]["stage"], "not_on_sale")
                # Only the first wait may use the full unlock budget; every retry rechecks quickly.
                budgets = [call.args[1] for call in adapter._wait_buy_button.call_args_list]
                self.assertEqual(budgets[1:], [0.5] * (clicks - 1))

    def test_presale_retry_budget_is_not_renewed_for_the_next_candidate(self):
        not_on_sale = OrderResult("not_submitted", no_order=True, evidence={"not_on_sale": True})
        adapter = self.make_adapter()
        button = Mock()
        adapter._wait_buy_button = Mock(return_value=button)
        adapter._resolve_after_buy_click = Mock(side_effect=self.settled_results(
            [not_on_sale, not_on_sale, OrderResult("sold_out", no_order=True), not_on_sale]))
        outcome = adapter.execute_armed(self.plan, self.journal, "budget", BASE_CONFIG)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertEqual(button.click.call_count, 4)
        self.assertEqual(outcome.sold_out_candidates, self.plan.candidates[:1])
        self.assertEqual(self.journal.run_events("budget")[-1]["detail"],
                         {"stage": "not_on_sale", "train": "G8863", "seat": "二等座"})

    def test_entry_click_marker_carries_the_unlock_wait_for_the_review(self):
        adapter = self.make_adapter()
        adapter._resolve_after_buy_click = Mock(return_value=OrderResult("unknown"))
        clock = [10.0]

        def unlocked_after_wait(plan, cand, budget):
            clock[0] += 0.75
            return Mock(), ""

        adapter._prepare_candidate_button = Mock(side_effect=unlocked_after_wait)
        with patch("railwatch_prefill.time.monotonic", side_effect=lambda: clock[0]):
            outcome = adapter.execute_armed(self.plan, self.journal, "unlock-wait", BASE_CONFIG)
        marker = next(e for e in self.journal.run_events("unlock-wait") if e["stage"] == "prefill_submit")
        self.assertEqual(marker["detail"], {"train": "G8821", "seat": "二等座", "unlock_wait_ms": 750.0})
        self.journal.dismiss(outcome.last_intent.intent_id)

    def test_fallback_logs_reason_train_and_seat_without_passenger_names(self):
        cases = [
            ("passengers_changed", "官方预填乘车人信息缺失或已变化，已回退常规余票查询。"),
            ("unlock_timeout", "预填购票按钮未在限定时间内显示，已回退常规余票查询。"),
            ("unrecognized_stage", "官方预填暂不可用，已回退常规余票查询。"),
        ]
        for stage, message in cases:
            with self.subTest(stage=stage):
                adapter = self.make_adapter()
                adapter.log = Mock()
                button = Mock()
                adapter._wait_buy_button = Mock(return_value=None if stage == "unlock_timeout" else button)
                if stage == "passengers_changed":
                    adapter._detail_snapshot.return_value["passengers_text"] = "李四"
                elif stage == "unrecognized_stage":
                    adapter._prepare_candidate_button = Mock(return_value=(None, stage))
                outcome = adapter.execute_armed(self.plan, self.journal, stage, BASE_CONFIG)
                self.assertEqual(outcome.action, "fallback_to_query")
                self.assertIsNone(self.journal.pending())
                button.click.assert_not_called()
                adapter.log.assert_called_once_with(f"G8821 二等座：{message}")
                self.assertNotIn("张三", str(adapter.log.call_args_list))
                self.assertNotIn("李四", str(adapter.log.call_args_list))

    def test_previous_candidate_dialog_clears_on_second_poll_and_click_continues(self):
        adapter = self.make_adapter()
        detail = adapter._detail_snapshot.return_value
        blocked = {**detail, "dialogs": ["票已售完"]}
        adapter._detail_snapshot.side_effect = [blocked, blocked, detail]
        button = Mock()
        adapter._wait_buy_button = Mock(return_value=button)
        adapter._resolve_after_buy_click = Mock(return_value=OrderResult("unknown"))
        elapsed = [0.0]
        def wait(seconds):
            elapsed[0] += seconds
        adapter.wait = Mock(side_effect=wait)
        with patch("railwatch_prefill.time.monotonic", side_effect=lambda: elapsed[0]):
            outcome = adapter.execute_armed(self.plan, self.journal, "dialog-cleared", BASE_CONFIG)
        self.assertEqual(outcome.action, "handled")
        self.assertEqual(adapter._detail_snapshot.call_count, 3)
        self.assertGreater(elapsed[0], 0)
        self.assertLess(elapsed[0], adapter.DIALOG_CLEAR_SECONDS)
        adapter.wait.assert_called_once()
        button.click.assert_called_once()
        adapter._resolve_after_buy_click.assert_called_once()
        stages = [event["stage"] for event in self.journal.run_events("dialog-cleared")]
        self.assertIn("prefill_submit", stages)
        self.assertNotIn("prefill_fallback", stages)

    def test_presale_prompt_retries_once_without_leaving_lock(self):
        adapter = self.make_adapter()
        button = Mock()
        adapter._wait_buy_button = Mock(return_value=button)
        adapter._resolve_after_buy_click = Mock(
            side_effect=self.settled_results([
                OrderResult("not_submitted", "官方提示未到起售时间", no_order=True, evidence={"not_on_sale": True}),
                OrderResult("pending_payment", order_id="E888888", evidence={"matched": True}),
            ])
        )
        outcome = adapter.execute_armed(self.plan, self.journal, "run-2", BASE_CONFIG)
        self.assertEqual(outcome.action, "handled")
        self.assertEqual(outcome.last_result.status, "pending_payment")
        self.assertEqual(button.click.call_count, 2)
        self.assertEqual(self.journal.pending()["result"]["order_id"], "E888888")

    def test_first_candidate_sold_out_cascades_to_second_candidate(self):
        adapter = self.make_adapter()
        btn1, btn2 = Mock(), Mock()
        adapter._wait_buy_button = Mock(side_effect=[btn1, btn2])
        adapter._resolve_after_buy_click = Mock(
            side_effect=self.settled_results([
                OrderResult("sold_out", "官方提示余票不足", no_order=True),
                OrderResult("pending_payment", order_id="E999999", evidence={"matched": True}),
            ])
        )
        seen = []
        outcome = adapter.execute_armed(
            self.plan, self.journal, "run-3", BASE_CONFIG, on_order=lambda i, r: seen.append((i.train_code, r.status))
        )
        self.assertEqual(outcome.action, "handled")
        self.assertEqual([c.train_code for c in outcome.sold_out_candidates], ["G8821"])
        self.assertEqual(outcome.last_intent.train_code, "G8863")
        self.assertEqual(outcome.last_result.order_id, "E999999")
        self.assertEqual(
            seen,
            [
                ("G8821", "submitting"),
                ("G8821", "sold_out"),
                ("G8863", "submitting"),
                ("G8863", "pending_payment"),
            ],
        )

    def test_unknown_outcome_locks_journal_and_never_clicks_second_candidate(self):
        adapter = self.make_adapter()
        btn1, btn2 = Mock(), Mock()
        adapter._wait_buy_button = Mock(side_effect=[btn1, btn2])
        adapter._resolve_after_buy_click = Mock(return_value=OrderResult("unknown", "官方处理超时"))
        outcome = adapter.execute_armed(self.plan, self.journal, "run-4", BASE_CONFIG)
        self.assertEqual(outcome.action, "handled")
        self.assertEqual(outcome.last_result.status, "unknown")
        btn1.click.assert_called_once()
        btn2.click.assert_not_called()
        self.assertIsNotNone(self.journal.pending())

    def test_run_review_recognizes_prefill_submit_markers(self):
        events = [
            {"sequence": 1, "run_id": "r", "stage": "inventory_found", "at": 100.0, "monotonic": 10.0, "detail": {}},
            {"sequence": 2, "run_id": "r", "stage": "prefill_submit", "at": 100.05, "monotonic": 10.05, "detail": {}},
        ]
        self.assertEqual(run_conclusion(events), "结果待核对")
        review = build_run_review(events)
        readback = next(s for s in review["segments"] if s["id"] == "readback")
        self.assertEqual(readback["duration_ms"], 50.0)

    def test_preclick_recheck_rejects_changed_or_missing_passengers_trip_or_dialog(self):
        cases = [
            ({"passengers_text": "李四"}, "passengers_changed"),
            ({"passengers_text": ""}, "passengers_changed"),
            ({"info": "11月22日"}, "trip_changed"),
            ({"to_station": "南京南"}, "trip_changed"),
            ({"active": False}, "trip_changed"),
            ({"duplicate_active": True}, "trip_changed"),
            ({"dialogs": ["请先处理提示"]}, "dialog_open"),
        ]
        for changes, stage in cases:
            with self.subTest(changes=changes):
                adapter = self.make_adapter()
                button = Mock()
                def ready(*args):
                    detail = adapter._detail_snapshot.return_value
                    if set(changes) & {"info", "to_station", "active"}:
                        detail["tabs"][0].update(changes)
                    elif changes.get("duplicate_active"):
                        detail["tabs"].append(dict(detail["tabs"][0]))
                    else:
                        detail.update(changes)
                    return button
                adapter._wait_buy_button = Mock(side_effect=ready)
                adapter._resolve_after_buy_click = Mock(return_value=OrderResult("unknown"))
                outcome = adapter.execute_armed(self.plan, self.journal, "changed", BASE_CONFIG)
                self.assertEqual(outcome.action, "fallback_to_query")
                self.assertIsNone(self.journal.pending())
                button.click.assert_not_called()
                event = self.journal.run_events("changed")[-1]
                self.assertEqual(event["stage"], "prefill_fallback")
                self.assertEqual(event["detail"], {"stage": stage, "train": "G8821", "seat": "二等座"})
                self.assertNotIn("张三", json.dumps(event["detail"], ensure_ascii=False))
                self.assertNotIn("李四", json.dumps(event["detail"], ensure_ascii=False))

    def test_detail_read_errors_soft_fallback_before_intent(self):
        adapter = self.make_adapter()
        adapter._detail_snapshot.side_effect = WebDriverException("敏感页面文本")
        outcome = adapter.execute_armed(self.plan, self.journal, "read-error", BASE_CONFIG)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertIsNone(self.journal.pending())
        self.assertEqual(self.journal.run_events("read-error")[-1]["detail"]["stage"], "detail_unavailable")

    def test_partial_sold_out_never_reports_all_on_early_exit(self):
        for failure in ("unlock_timeout", "detail_unavailable", "not_on_sale", "click_rejected"):
            with self.subTest(failure=failure):
                adapter = self.make_adapter()
                first, second = Mock(), Mock()
                adapter._wait_buy_button = Mock(side_effect=[first, None] if failure == "unlock_timeout" else None,
                                                return_value=second)
                if failure != "unlock_timeout":
                    adapter._wait_buy_button.side_effect = [first] + [second] * 4
                if failure == "detail_unavailable":
                    adapter._ensure_candidate_tab.side_effect = [True, False]
                if failure == "click_rejected":
                    second.click.side_effect = ElementNotInteractableException()
                results = [OrderResult("sold_out", no_order=True)]
                if failure == "not_on_sale":
                    attempts = 1 + len(prefill.ORDER_POLICIES["prefill_presale_retry_delays_ms"])
                    results += [OrderResult("not_submitted", no_order=True, evidence={"not_on_sale": True})] * attempts
                adapter._resolve_after_buy_click = Mock(side_effect=self.settled_results(results))
                outcome = adapter.execute_armed(self.plan, self.journal, failure, BASE_CONFIG)
                self.assertEqual(outcome.action, "fallback_to_query")
                self.assertEqual(outcome.sold_out_candidates, self.plan.candidates[:1])
                self.assertIsNotNone(outcome.last_intent)
                self.assertIsNotNone(outcome.last_result)
                self.assertIsNone(self.journal.pending())
                self.assertEqual(self.journal.run_events(failure)[-1]["detail"]["stage"], failure)

    def test_all_confirmed_sold_out_reports_sold_out_all(self):
        adapter = self.make_adapter()
        adapter._wait_buy_button = Mock(return_value=Mock())
        adapter._resolve_after_buy_click = Mock(side_effect=self.settled_results([OrderResult("sold_out", no_order=True)] * 2))
        outcome = adapter.execute_armed(self.plan, self.journal, "all", BASE_CONFIG)
        self.assertEqual(outcome.action, "sold_out_all")
        self.assertEqual(outcome.sold_out_candidates, self.plan.candidates)
        self.assertIsNone(self.journal.pending())

    def test_rejected_click_reacquires_same_intent_before_single_resolution(self):
        for exc_type in (StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException):
            with self.subTest(exc_type=exc_type):
                adapter = self.make_adapter()
                adapter.log = Mock()
                first, second = Mock(), Mock()
                first.click.side_effect = exc_type("张三")
                adapter._wait_buy_button = Mock(side_effect=[first, second])
                adapter._resolve_after_buy_click = Mock(return_value=OrderResult("unknown"))
                run_id = "retry-" + exc_type.__name__
                outcome = adapter.execute_armed(self.plan, self.journal, run_id, BASE_CONFIG)
                first.click.assert_called_once()
                second.click.assert_called_once()
                adapter._resolve_after_buy_click.assert_called_once()
                events = [e for e in self.journal.run_events(run_id) if e["stage"].startswith("prefill_")]
                self.assertEqual([e["stage"] for e in events], ["prefill_submit", "prefill_click_rejected", "prefill_submit"])
                self.assertEqual({e["intent_id"] for e in events}, {outcome.last_intent.intent_id})
                self.assertEqual(events[1]["detail"], {"kind": exc_type.__name__})
                self.assertNotIn("张三", str(adapter.log.call_args_list))
                self.assertEqual(adapter._wait_buy_button.call_args.args[1], 0.3)
                self.journal.dismiss(outcome.last_intent.intent_id)

    def test_three_rejected_clicks_release_intent_and_fallback(self):
        adapter = self.make_adapter()
        button = Mock()
        button.click.side_effect = StaleElementReferenceException()
        adapter._wait_buy_button = Mock(return_value=button)
        adapter._resolve_after_buy_click = Mock()
        outcome = adapter.execute_armed(self.plan, self.journal, "rejected", BASE_CONFIG)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertEqual(outcome.last_result.status, "not_submitted")
        self.assertTrue(outcome.last_result.no_order)
        self.assertTrue(outcome.last_result.evidence["click_rejected"])
        self.assertIsNone(self.journal.pending())
        button.click.assert_has_calls([unittest.mock.call()] * 3)
        self.assertEqual(button.click.call_count, 3)
        adapter._resolve_after_buy_click.assert_not_called()

    def test_ambiguous_click_errors_keep_pending_and_never_retry(self):
        for exc_type in (TimeoutException, WebDriverException):
            with self.subTest(exc_type=exc_type):
                adapter = self.make_adapter()
                button = Mock()
                button.click.side_effect = exc_type("敏感页面文本")
                adapter._wait_buy_button = Mock(return_value=button)
                adapter._resolve_after_buy_click = Mock()
                with patch.object(OrderPage, "result", return_value=OrderResult("unknown")) as result:
                    outcome = adapter.execute_armed(self.plan, self.journal, "ambiguous", BASE_CONFIG)
                self.assertEqual(outcome.action, "handled")
                self.assertEqual(outcome.last_result.status, "unknown")
                self.assertIsNotNone(self.journal.pending())
                self.assertFalse(self.journal.claim_resume("resume", outcome.last_intent.intent_id))
                button.click.assert_called_once()
                result.assert_called_once_with(outcome.last_intent, submitted=True)
                adapter._resolve_after_buy_click.assert_not_called()
                self.journal.dismiss(outcome.last_intent.intent_id)

    def test_recheck_runs_after_presale_and_rejected_click_retries(self):
        for mode in ("presale", "click"):
            with self.subTest(mode=mode):
                adapter = self.make_adapter()
                button = Mock()
                def ready(*args):
                    if adapter._wait_buy_button.call_count > 1:
                        adapter._detail_snapshot.return_value["passengers_text"] = "李四"
                    return button
                adapter._wait_buy_button = Mock(side_effect=ready)
                if mode == "click":
                    button.click.side_effect = StaleElementReferenceException()
                adapter._resolve_after_buy_click = Mock(side_effect=self.settled_results([
                    OrderResult("not_submitted", no_order=True, evidence={"not_on_sale": True})]))
                outcome = adapter.execute_armed(self.plan, self.journal, mode, BASE_CONFIG)
                self.assertEqual(outcome.action, "fallback_to_query")
                self.assertIsNone(self.journal.pending())
                button.click.assert_called_once()
                stage = self.journal.run_events(mode)[-1]["detail"]["stage"]
                self.assertEqual(stage, "passengers_changed" if mode == "presale" else "click_rejected")

    def test_verification_prompt_keeps_first_candidate_and_dialog(self):
        adapter = self.make_adapter()
        first, second = Mock(), Mock()
        adapter._wait_buy_button = Mock(side_effect=[first, second])
        with patch.object(OrderPage, "snapshot", return_value={"dialogs": ["票已售完，请完成核验"], "verification": True}):
            outcome = adapter.execute_armed(self.plan, self.journal, "verification", BASE_CONFIG)
        self.assertEqual(outcome.last_result.status, "verification")
        self.assertFalse(outcome.last_result.no_order)
        self.assertEqual(outcome.sold_out_candidates, ())
        first.click.assert_called_once()
        second.click.assert_not_called()
        adapter.driver.execute_script.assert_not_called()
        self.assertIsNotNone(self.journal.pending())

    def test_failed_prefill_marker_never_clicks_button(self):
        adapter = self.make_adapter()
        button = Mock()
        adapter._wait_buy_button = Mock(return_value=button)
        original_mark = self.journal.mark
        def mark(run_id, stage, *args, **kwargs):
            if stage == "prefill_submit":
                raise RuntimeError("存储失败")
            return original_mark(run_id, stage, *args, **kwargs)
        with patch.object(self.journal, "mark", side_effect=mark), \
             patch.object(OrderPage, "result", return_value=OrderResult("unknown")):
            outcome = adapter.execute_armed(self.plan, self.journal, "marker", BASE_CONFIG)
        button.click.assert_not_called()
        self.assertEqual(outcome.last_result.status, "unknown")
        self.assertIsNotNone(self.journal.pending())

    def test_cancelled_relocation_after_rejection_releases_intent(self):
        adapter = self.make_adapter()
        button = Mock()
        button.click.side_effect = StaleElementReferenceException()
        adapter._wait_buy_button = Mock(side_effect=[button, TaskCancelled()])
        outcome = adapter.execute_armed(self.plan, self.journal, "cancelled-click", BASE_CONFIG)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertEqual(outcome.last_result.status, "not_submitted")
        self.assertIsNone(self.journal.pending())
        button.click.assert_called_once()


class PrefillPreparationRegressionTests(unittest.TestCase):
    def preparation(self, saved, rows, *, result=None, fixture=False):
        driver = Mock()
        driver.current_url = "file:///fixtures/prefill-order.html" if fixture else prefill.PREFILL_ORDER_URL
        driver.get.side_effect = lambda url: setattr(driver, "current_url", url)
        driver.execute_script.return_value = rows
        adapter = PrefillAdapter(driver, wait=lambda _: None, now=lambda: NOW_1550,
                                 allow_fixture=fixture, query_init_url="file:///fixtures/query.html" if fixture else prefill.QUERY_INIT_URL)
        adapter.check_browser_clock = Mock()
        detail = {"tabs": [{"index": 0}], "passengers_text": "张三"}
        adapter._detail_snapshot = Mock(return_value=detail)
        adapter._collect_saved_detail = Mock(return_value=("张三", saved))
        adapter._wait_detail_tabs = Mock(return_value=detail)
        adapter._wait_editor_ready = Mock(return_value={"ready": True})
        adapter._verify_editor_readback = Mock()
        adapter._verify_and_arm_detail = Mock(return_value=ArmedPrefillPlan("2026-11-21", ("张三",), tuple(saved), SALE_1600))
        adapter._wait_remaining_ready = Mock(return_value=None)
        page = Mock(spec=OrderPage)
        self.order_page = page
        query, entry, edit, confirm = Mock(), Mock(), Mock(), Mock()
        controls = {"#query_ticket": query, "#preFilled1href": entry, "#edit-button": edit,
                    prefill.PREFILL_EDITOR_CONFIRM_SELECTOR: confirm, "#saveBtn": Mock()}
        page.button.side_effect = lambda selectors: controls.get(selectors[0])
        executor = Mock()
        def execute(click, timeout):
            click()
            return result or {"status": "ok"}
        executor.execute.side_effect = execute
        for patcher in (patch("railwatch_prefill.OrderPage", return_value=page),
                        patch("railwatch_prefill.QueryExecutor", return_value=executor)):
            patcher.start()
            self.addCleanup(patcher.stop)
        return adapter, query, entry, edit, executor

    def test_saved_other_route_is_not_reused_and_entry_uses_one_query(self):
        saved = [PrefillCandidate("G1", "2026-11-21", "北京南", "南京南", "二等座")]
        adapter, query, entry, edit, executor = self.preparation(
            saved, [{"train": "G1", "from_station": "北京南", "to_station": "上海虹桥"}])
        config = {**BASE_CONFIG, "train_code": "G1", "seat_keyword": "二等座", "to_station_cn": "上海虹桥"}
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.prepare(config, SALE_1600)
        self.assertEqual(ctx.exception.stage, "remaining_load")
        query.click.assert_called_once()
        executor.execute.assert_called_once()
        entry.click.assert_called_once()
        edit.click.assert_not_called()
        adapter._verify_and_arm_detail.assert_not_called()

    def test_saved_seats_without_passengers_return_to_preparation(self):
        adapter, _, _, _, _ = self.preparation([], [])
        adapter._detail_snapshot.return_value = {"tabs": [{"index": 0}], "passengers_text": ""}
        self.assertEqual(adapter._inspect_existing(
            travel_date="2026-11-21", passengers=("张三",), target_timestamp=SALE_1600), [])
        adapter._collect_saved_detail.assert_not_called()

    def test_entry_landing_in_editor_follows_add_train_before_reading_remaining(self):
        adapter, _, entry, _, _ = self.preparation([], [])
        entry.click.side_effect = lambda: adapter.driver.get(prefill.PREFILL_LIST_URL)
        add_train = Mock()
        add_train.click.side_effect = lambda: adapter.driver.get(prefill.PREFILL_REMAINING_URL)
        original_lookup = self.order_page.button.side_effect
        self.order_page.button.side_effect = lambda selectors: (
            add_train if selectors == ("a.btn-addpassenger.list-add",) else original_lookup(selectors))
        def remaining(timeout):
            self.assertEqual(adapter.driver.current_url, prefill.PREFILL_REMAINING_URL)
            return {"items": []}
        adapter._wait_remaining_ready.side_effect = remaining
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.prepare(BASE_CONFIG, SALE_1600)
        self.assertEqual(ctx.exception.stage, "no_matching_candidates")
        add_train.click.assert_called_once()

    def test_saved_same_city_actual_route_is_reused_after_query(self):
        saved = [PrefillCandidate("G1", "2026-11-21", "大兴机场", "天津西", "二等座")]
        adapter, query, entry, edit, executor = self.preparation(
            saved, [{"train": "G1", "from_station": "大兴机场", "to_station": "天津西"}])
        edit.click.side_effect = lambda: self.assertEqual(query.click.call_count, 1)
        self.assertEqual(adapter.prepare({**BASE_CONFIG, "train_code": "G1", "seat_keyword": "二等座"}, SALE_1600),
                         adapter._verify_and_arm_detail.return_value)
        query.click.assert_called_once()
        executor.execute.assert_called_once()
        edit.click.assert_called_once()
        entry.click.assert_not_called()
        self.assertEqual(adapter.driver.get.call_args_list[-1].args[0], prefill.PREFILL_ORDER_URL)
        self.assertEqual(adapter._verify_and_arm_detail.call_args.args[1], saved)

    def test_missing_actual_route_does_not_reuse_saved_candidate(self):
        saved = [PrefillCandidate("G1", "2026-11-21", "大兴机场", "天津西", "二等座")]
        adapter, query, entry, edit, _ = self.preparation(
            saved, [{"train": "G1", "from_station": None, "to_station": "天津西"}])
        with self.assertRaises(PrefillFallback):
            adapter.prepare({**BASE_CONFIG, "train_code": "G1", "seat_keyword": "二等座"}, SALE_1600)
        edit.click.assert_not_called()
        entry.click.assert_called_once()
        query.click.assert_called_once()

    def test_empty_saved_candidates_skip_query_rows_and_continue_entry(self):
        for check_existing in (True, False):
            with self.subTest(check_existing=check_existing):
                adapter, query, entry, edit, _ = self.preparation([], [])
                adapter._try_reuse_existing = Mock(side_effect=AssertionError("不应复用空候选"))
                with patch.object(prefill.RowParser, "snapshot_rows", side_effect=RuntimeError("无法读取查询结果快照")) as rows:
                    with self.assertRaises(PrefillFallback) as ctx:
                        adapter.prepare(BASE_CONFIG, SALE_1600, check_existing=check_existing)
                self.assertEqual(ctx.exception.stage, "remaining_load")
                rows.assert_not_called()
                adapter._try_reuse_existing.assert_not_called()
                query.click.assert_called_once()
                entry.click.assert_called_once()
                edit.click.assert_not_called()

    def test_slow_preparation_stops_before_entry_to_keep_regular_query_on_time(self):
        clock = [NOW_1550]
        adapter, query, entry, _, executor = self.preparation([], [])
        adapter.now = lambda: clock[0]

        def slow_query(click, timeout):
            click()
            clock[0] = SALE_1600 - 20
            return {"status": "ok"}

        executor.execute.side_effect = slow_query
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.prepare(BASE_CONFIG, SALE_1600)
        self.assertEqual(ctx.exception.stage, "prepare_deadline")
        query.click.assert_called_once()
        entry.click.assert_not_called()
        # The budget belongs to preparation only: the timed purchase polls after the sale.
        self.assertIsNone(adapter._prepare_deadline)
        clock[0] = SALE_1600 + 1
        self.assertTrue(adapter._poll(lambda: True, 0.1))

    def test_fixture_detail_url_must_navigate_to_query_before_click(self):
        adapter, query, entry, _, _ = self.preparation([], [], fixture=True)
        query.click.side_effect = lambda: self.assertEqual(adapter.driver.current_url, adapter.query_init_url)
        with self.assertRaises(PrefillFallback):
            adapter.prepare(BASE_CONFIG, SALE_1600, check_existing=False)
        query.click.assert_called_once()
        entry.click.assert_called_once()

    def test_reuse_failure_after_leaving_query_is_a_fallback(self):
        saved = [PrefillCandidate("G1", "2026-11-21", "大兴机场", "天津西", "二等座")]
        adapter, query, entry, edit, _ = self.preparation(
            saved, [{"train": "G1", "from_station": "大兴机场", "to_station": "天津西"}])
        adapter._wait_editor_ready.return_value = None
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.prepare({**BASE_CONFIG, "train_code": "G1", "seat_keyword": "二等座"}, SALE_1600)
        self.assertEqual(ctx.exception.stage, "editor_load")
        query.click.assert_called_once()
        edit.click.assert_called_once()
        entry.click.assert_not_called()

    def test_prepare_cancelled_query_raises_task_cancelled(self):
        adapter, _, entry, _, _ = self.preparation([], [], result={"status": "cancelled"})
        with self.assertRaises(TaskCancelled):
            adapter.prepare(BASE_CONFIG, SALE_1600, check_existing=False)
        entry.click.assert_not_called()

    def test_new_candidates_are_not_filtered_by_query_route(self):
        adapter, query, entry, edit, _ = self.preparation([], [
            {"train": "G1", "from_station": "北京南", "to_station": "天津"}])
        adapter._wait_remaining_ready.return_value = {"items": [{
            "train_code": "G1", "from_station": "大兴机场", "to_station": "天津西", "sale_label": "11月7日16点起售",
            "seats": [{"seat": "二等座"}]}]}
        adapter._remaining_snapshot = Mock(return_value={"save_ready": True})
        adapter._editor_snapshot = Mock(return_value={"selected_rows": [{"name": "张三", "ticket_type": "成人票"}]})
        adapter._verify_no_editor_conflict = Mock()
        adapter._verify_and_arm_detail.return_value = Mock(spec=ArmedPrefillPlan, candidates=[Mock()])
        adapter.driver.execute_script.side_effect = lambda script, *args: (
            {"found": True, "active": True} if script == prefill.FIND_REMAINING_SEAT_BTN_JS else
            [{"train": "G1", "from_station": "北京南", "to_station": "天津"}])
        self.order_page.wait_people.return_value = True
        self.order_page.prepare_people.return_value = True
        adapter.prepare({**BASE_CONFIG, "train_code": "G1", "seat_keyword": "二等座"}, SALE_1600)
        candidate = adapter._verify_and_arm_detail.call_args.args[1][0]
        self.assertEqual((candidate.from_station, candidate.to_station), ("大兴机场", "天津西"))
        query.click.assert_called_once()
        entry.click.assert_called_once()
        edit.click.assert_not_called()

    def test_prepare_query_failure_preserves_result(self):
        result = {"status": "rate_limited", "retry_after_seconds": 300, "http_status": 429}
        adapter, _, entry, _, _ = self.preparation([], [], result=result)
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.prepare(BASE_CONFIG, SALE_1600, check_existing=False)
        self.assertEqual(ctx.exception.stage, "query_prepare")
        self.assertEqual(ctx.exception.query_result, result)
        entry.click.assert_not_called()

    def test_arming_always_checks_visible_countdown_for_mixed_sale_labels(self):
        cand = PrefillCandidate("G1", "2026-11-21", "北京南", "上海虹桥", "二等座")
        tab = {"index": 0, "active": True, "from_station": cand.from_station,
               "to_station": cand.to_station, "info": "11月21日"}
        cases = [
            (["11月7日16点起售", "11月7日18点起售"], True, "18小时", "countdown_mismatch"),
            (["无法解析起售文案"], True, "18小时", "countdown_mismatch"),
            (["11月7日16点起售"], False, "10分钟", "detail_countdown"),
            (["11月7日16点起售", "11月7日18点起售"], True, "10分钟", None),
        ]
        for labels, visible, countdown, stage in cases:
            with self.subTest(labels=labels, visible=visible, countdown=countdown):
                adapter = PrefillAdapter(Mock(), now=lambda: NOW_1550)
                snap = {"tabs": [tab], "passengers_text": "张三", "unonsale_visible": visible,
                        "countdown_text": countdown, "cards": [{"sale_label": label} for label in labels]}
                adapter._wait_detail_tabs = Mock(return_value=snap)
                adapter._detail_snapshot = Mock(return_value=snap)
                adapter._collect_saved_detail = Mock(return_value=("张三", [cand]))
                adapter._activate_detail_tab = Mock(return_value=snap)
                if stage:
                    with self.assertRaises(PrefillFallback) as ctx:
                        adapter._verify_and_arm_detail(cand.date, [cand], ("张三",), SALE_1600)
                    self.assertEqual(ctx.exception.stage, stage)
                else:
                    plan = adapter._verify_and_arm_detail(cand.date, [cand], ("张三",), SALE_1600)
                    self.assertEqual(plan.candidates, (cand,))

    def test_arming_rejects_visible_dialog_before_countdown_check(self):
        cand = PrefillCandidate("G1", "2026-11-21", "北京南", "上海虹桥", "二等座")
        tab = {"index": 0, "active": True, "from_station": cand.from_station,
               "to_station": cand.to_station, "info": "11月21日"}
        snap = {"tabs": [tab], "passengers_text": "张三", "dialogs": ["请核对乘车人信息"],
                "unonsale_visible": True, "countdown_text": "10分钟"}
        adapter = PrefillAdapter(Mock(), now=lambda: NOW_1550)
        adapter._wait_detail_tabs = Mock(return_value=snap)
        adapter._detail_snapshot = Mock(return_value=snap)
        adapter._collect_saved_detail = Mock(return_value=("张三", [cand]))
        adapter._activate_detail_tab = Mock(return_value=snap)
        adapter._check_countdown_tolerance = Mock()
        with self.assertRaises(PrefillFallback) as ctx:
            adapter._verify_and_arm_detail(cand.date, [cand], ("张三",), SALE_1600)
        self.assertEqual(ctx.exception.stage, "detail_dialog")
        adapter._check_countdown_tolerance.assert_not_called()


class PrefillJournalRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = OrderJournal(Path(self.temp.name) / "orders.sqlite3")
        self.addCleanup(lambda: self.journal.release_resume(*self.journal._resume_owner[:2])
                        if self.journal._resume_owner else None)
        self.intent = OrderIntent("regular", "G1", "2026-11-21", "北京南", "上海虹桥", "二等座", ("张三",))
        self.journal.begin("r", self.intent, BASE_CONFIG)

    def test_unsettled_prefill_click_blocks_resume_and_no_order_results(self):
        self.journal.mark("r", "prefill_submit", self.intent.intent_id)
        self.assertTrue(self.journal.submission_started(self.intent.intent_id))
        self.assertFalse(self.journal.claim_resume("resume", self.intent.intent_id))
        for status in ("sold_out", "not_submitted"):
            with self.subTest(status=status):
                result = self.journal.record(self.intent, OrderResult(status, no_order=True))
                self.assertEqual(result.status, "unknown")
                self.assertIsNotNone(self.journal.pending())

    def test_rejected_clicks_allow_explicit_no_order_results(self):
        for stage, status in ((stage, status) for stage in ("prefill_click_rejected", "prefill_official_rejected")
                              for status in ("sold_out", "not_submitted")):
            with self.subTest(stage=stage, status=status):
                self.journal.mark("r", "prefill_submit", self.intent.intent_id)
                self.assertTrue(self.journal.submission_started(self.intent.intent_id))
                self.journal.mark("r", stage, self.intent.intent_id)
                self.assertFalse(self.journal.submission_started(self.intent.intent_id))
                result = self.journal.record(self.intent, OrderResult(status, no_order=True))
                self.assertEqual(result.status, status)
                self.assertIsNone(self.journal.pending())
                self.intent = replace(self.intent, intent_id=self.intent.intent_id + "x")
                self.journal.begin("r", self.intent, BASE_CONFIG)

    def test_form_opened_hands_resume_ownership_to_regular_submit(self):
        self.journal.mark("r", "prefill_submit", self.intent.intent_id)
        self.assertTrue(self.journal.submission_started(self.intent.intent_id))
        self.journal.mark("r", "prefill_form_opened", self.intent.intent_id)
        self.assertFalse(self.journal.submission_started(self.intent.intent_id))
        self.assertTrue(self.journal.claim_resume("resume", self.intent.intent_id))
        self.journal.mark("resume", "regular_submit", self.intent.intent_id)
        self.journal.release_resume("resume", self.intent.intent_id)
        self.assertTrue(self.journal.submission_started(self.intent.intent_id))
        self.assertFalse(self.journal.claim_resume("resume", self.intent.intent_id))

    def test_prefill_mark_rejects_missing_pending_and_duplicate_attempts(self):
        for stage in ("prefill_click_rejected", "prefill_official_rejected", "prefill_form_opened"):
            with self.subTest(stage=stage), self.assertRaises(RuntimeError):
                self.journal.mark("r", stage, self.intent.intent_id)
        with self.assertRaises(RuntimeError):
            self.journal.mark("r", "prefill_submit", "missing")
        self.journal.mark("r", "prefill_submit", self.intent.intent_id)
        with self.assertRaises(RuntimeError):
            self.journal.mark("r", "prefill_submit", self.intent.intent_id)
        self.journal.mark("r", "prefill_click_rejected", self.intent.intent_id)
        self.journal.record(self.intent, OrderResult("not_submitted", no_order=True))
        with self.assertRaises(RuntimeError):
            self.journal.mark("r", "prefill_submit", self.intent.intent_id)

    def test_prefill_mark_rejects_other_owner_or_started_submission(self):
        self.assertTrue(self.journal.claim_resume("other", self.intent.intent_id))
        with self.assertRaises(RuntimeError):
            self.journal.mark("r", "prefill_submit", self.intent.intent_id)
        self.journal.release_resume("other", self.intent.intent_id)
        self.journal.mark("r", "regular_submit", self.intent.intent_id)
        with self.assertRaises(RuntimeError):
            self.journal.mark("r", "prefill_submit", self.intent.intent_id)

    def test_alternate_intent_cannot_mark_prefill_submit(self):
        self.journal.record(self.intent, OrderResult("not_submitted", no_order=True))
        alternate = replace(self.intent, kind="alternate", intent_id="alternate")
        self.journal.begin("r", alternate, BASE_CONFIG)
        with self.assertRaises(RuntimeError):
            self.journal.mark("r", "prefill_submit", alternate.intent_id)


class PrefillTransitionRegressionTests(unittest.TestCase):
    setUp = PrefillJournalRegressionTests.setUp
    def page(self, snap):
        self.journal.mark("r", "prefill_submit", self.intent.intent_id)
        driver = Mock()
        adapter = PrefillAdapter(driver, wait=lambda _: None)
        page = OrderPage(driver, mark=lambda stage, detail=None: self.journal.mark("r", stage, self.intent.intent_id, detail))
        page.snapshot = Mock(return_value=snap)
        page.button = Mock(return_value=Mock())
        page.regular = Mock(return_value=OrderResult("verification"))
        page._post_submit = Mock(return_value=OrderResult("unknown"))
        return adapter, page

    def test_verification_with_sold_out_text_never_dismisses_or_tries_next(self):
        snap = {"dialogs": ["票已售完，请完成核验"], "verification": True}
        adapter, page = self.page(snap)
        result = adapter._resolve_after_buy_click(self.intent, page)
        self.assertEqual(result.status, "verification")
        self.assertFalse(result.no_order)
        adapter.driver.execute_script.assert_not_called()
        page.button.assert_not_called()
        self.assertFalse(self.journal.claim_resume("resume", self.intent.intent_id))

    def test_human_states_precede_confirmation_and_form_and_keep_resume_locked(self):
        human_states = [
            {"verification": True},
            {"dialogs": ["请完成核验"]},
            {"url": "https://kyfw.12306.cn/otn/resources/login.html"},
            {"quietCar": True},
        ]
        for ready_field in ("confirmation", "formReady"):
            for index, human_state in enumerate(human_states):
                with self.subTest(ready_field=ready_field, human_state=human_state):
                    self.journal = OrderJournal(Path(self.temp.name) / f"human-{ready_field}-{index}.sqlite3")
                    self.journal.begin("r", self.intent, BASE_CONFIG)
                    adapter, page = self.page({ready_field: True, **human_state})
                    adapter.driver.execute_script.return_value = {
                        "text": "2026-11-21 G1次 北京南站 — 上海虹桥站 二等座 张三", "names": ["张三"]}
                    result = adapter._resolve_after_buy_click(self.intent, page)
                    self.assertEqual(result.status, "verification")
                    page.button.return_value.click.assert_not_called()
                    page.regular.assert_not_called()
                    stages = [event["stage"] for event in self.journal.run_events("r")]
                    self.assertNotIn("prefill_form_opened", stages)
                    self.assertNotIn("regular_submit", stages)
                    claimed = self.journal.claim_resume("resume", self.intent.intent_id)
                    if claimed:
                        self.journal.release_resume("resume", self.intent.intent_id)
                    self.assertFalse(claimed)

    def test_explicit_rejection_requires_one_unique_safe_dialog(self):
        cases = [
            ({"dialogs": ["票已售完"]}, "sold_out"),
            ({"dialogs": ["尚未起售"]}, "not_on_sale"),
            ({"dialogs": ["票已售完", "票已售完"]}, "sold_out"),
            ({"dialogs": ["票已售完", "请关闭窗口"]}, None),
            ({"dialogs": []}, None),
            ({"dialogs": ["票已售完，尚未起售"]}, None),
        ]
        cases += [({"dialogs": ["票已售完，请" + warning]}, None)
                  for warning in ("登录", "核验", "验证", "滑块", "频繁", "操作过快", "稍后再试", "订单", "提交", "支付", "排队")]
        cases += [({"dialogs": ["票已售完"], field: True}, None)
                  for field in ("orders", "processing", "confirmation", "formReady", "verification", "quietCar")]
        for snap, expected in cases:
            with self.subTest(snap=snap):
                self.assertEqual(prefill.explicit_rejection(snap), expected)

    def test_confirmation_precedes_form_and_confirms_matching_dialog_once(self):
        adapter, page = self.page({"confirmation": True, "formReady": True})
        adapter.driver.execute_script.return_value = {
            "text": "2026-11-21 G1次 北京南站 — 上海虹桥站 二等座 张三", "names": ["张三"]}
        confirm = page.button.return_value
        def click(button, intent):
            button.click()
            return ConfirmationOutcome.DISPATCHED
        page._click_regular_confirmation = Mock(side_effect=click)
        adapter._resolve_after_buy_click(self.intent, page)
        page.regular.assert_not_called()
        confirm.click.assert_called_once()
        page._post_submit.assert_called_once_with(self.intent, True)
        stages = [e["stage"] for e in self.journal.run_events("r")]
        self.assertEqual(stages.count("regular_submit"), 1)
        self.assertNotIn("prefill_form_opened", stages)

    def test_mismatched_or_unreadable_confirmation_never_submits(self):
        base = {"text": "2026-11-21 G1次 北京南站 — 上海虹桥站 二等座 张三", "names": ["张三"]}
        cases = [
            {**base, "names": ["李四"]}, {**base, "names": ["张三", "李四"]},
            {**base, "seats": ["一等座"]},
            {**base, "ticket_types": ["学生票"]},
            {**base, "text": base["text"].replace("G1次", "G101次")},
            {**base, "text": base["text"].replace("2026-11-21", "2026-11-22")},
            {**base, "text": base["text"].replace("北京南站 — 上海虹桥站", "上海虹桥站 — 北京南站")},
            {**base, "text": base["text"].replace("二等座", "一等座")},
            {"text": "", "names": []}, WebDriverException("张三"),
        ]
        for reading in cases:
            with self.subTest(reading=type(reading).__name__):
                adapter, page = self.page({"confirmation": True, "formReady": True})
                if isinstance(reading, Exception):
                    adapter.driver.execute_script.side_effect = reading
                else:
                    adapter.driver.execute_script.return_value = reading
                result = adapter._resolve_after_buy_click(self.intent, page)
                self.assertEqual(result.status, "verification")
                self.assertFalse(result.no_order)
                page.button.return_value.click.assert_not_called()
                page.regular.assert_not_called()
                self.assertNotIn("regular_submit", [e["stage"] for e in self.journal.run_events("r")])
                self.journal.record(self.intent, result)
                self.journal.dismiss(self.intent.intent_id)
                self.intent = replace(self.intent, intent_id=self.intent.intent_id + "x")
                self.journal.begin("r", self.intent, BASE_CONFIG)

    def test_confirmation_without_name_column_requires_exact_name_tokens(self):
        adapter, page = self.page({"confirmation": True})
        adapter.driver.execute_script.return_value = {
            "text": "2026-11-21 G1次 北京南站 — 上海虹桥站 二等座 张三丰", "names": []}
        result = adapter._resolve_after_buy_click(self.intent, page)
        self.assertEqual(result.status, "verification")
        page.button.return_value.click.assert_not_called()

    def test_form_opened_settles_prefill_before_regular_handoff(self):
        adapter, page = self.page({"formReady": True})
        def regular(*args, **kwargs):
            self.assertFalse(self.journal.submission_started(self.intent.intent_id))
            self.assertEqual(self.journal.run_events("r")[-1]["stage"], "prefill_form_opened")
            return OrderResult("verification")
        page.regular.side_effect = regular
        self.assertEqual(adapter._resolve_after_buy_click(self.intent, page).status, "verification")
        page.regular.assert_called_once()

    def test_processing_takes_precedence_over_form_and_human_dialog(self):
        adapter, page = self.page({"processing": True, "formReady": True, "verification": True})
        adapter._resolve_after_buy_click(self.intent, page)
        page.regular.assert_not_called()
        # A visible queue is not a receipt for a confirmation click we delivered.
        page._post_submit.assert_called_once_with(self.intent, False)
        self.assertTrue(self.journal.submission_started(self.intent.intent_id))

    def test_official_rejection_settles_before_dismiss_even_if_close_fails(self):
        adapter, page = self.page({"dialogs": ["票已售完"]})
        def close(*args):
            self.assertFalse(self.journal.submission_started(self.intent.intent_id))
            raise WebDriverException("关闭失败")
        adapter.driver.execute_script.side_effect = close
        result = adapter._resolve_after_buy_click(self.intent, page)
        self.assertEqual(self.journal.record(self.intent, result).status, "sold_out")
        adapter.driver.execute_script.assert_called_once_with(prefill.DISMISS_PREFILL_ALERT_JS)
        self.assertIsNone(self.journal.pending())


class BridgePrefillWorkerIntegrationTests(unittest.TestCase):
    def test_sold_out_all_arms_immediate_alternate_flow_in_monitor_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory, event_callback=lambda _: None)
            self.addCleanup(bridge.notification_service.close)
            plan = ArmedPrefillPlan(
                date="2026-11-21",
                passengers=("张三",),
                candidates=(PrefillCandidate("G8821", "2026-11-21", "大兴机场", "天津西", "二等座"),),
                target_timestamp=SALE_1600,
            )
            config = dict(BASE_CONFIG)
            task = MonitorTask(config, SALE_1600)
            bridge._task = task
            bridge.driver = Mock()
            bridge.state = bridge.state.__class__(login_ready=True)
            bridge._ensure_driver = Mock(return_value=bridge.driver)
            bridge._start_monitor_heartbeat = Mock()
            bridge._make_param_filler = Mock(return_value=Mock(return_value=True))
            bridge._prepare_query_page = Mock(return_value=True)
            bridge._send_keep_alive = Mock()
            bridge._valid_dates = Mock(return_value=["2026-11-21"])
            bridge._wait_for_target_time = Mock(return_value=True)

            created_monitors = []

            def make_monitor(*args, **kwargs):
                m = TicketMonitor(*args, **kwargs)
                m.prepare = Mock(return_value=True)
                m.run = Mock()
                created_monitors.append(m)
                return m

            fake_adapter = Mock()
            fake_adapter.prepare.return_value = plan
            fake_adapter.execute_armed.return_value = PrefillExecutionOutcome(
                "sold_out_all",
                sold_out_candidates=plan.candidates,
                last_intent=OrderIntent("regular", "G8821", "2026-11-21", "大兴机场", "天津西", "二等座", ("张三",)),
                last_result=OrderResult("sold_out", "官方提示余票不足", no_order=True),
            )

            with patch("railwatch_bridge.time.time", return_value=NOW_1550), \
                 patch("railwatch_bridge.guard_browser", return_value=nullcontext()), \
                 patch("railwatch_bridge.TicketMonitor", side_effect=make_monitor), \
                 patch("railwatch_bridge.PrefillAdapter", return_value=fake_adapter):
                bridge._monitor_worker(config, task)

            monitor = created_monitors[0]
            self.assertTrue(monitor._prefer_alternate)
            self.assertEqual(monitor._fallback_date, "2026-11-21")
            self.assertTrue(monitor._needs_navigation)
            self.assertFalse(monitor._candidate_ready("G8821", "二等座", "book"))
            monitor.run.assert_called_once()

    def test_prepare_fallback_restores_query_page_and_runs_normal_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory, event_callback=lambda _: None)
            self.addCleanup(bridge.notification_service.close)
            config = dict(BASE_CONFIG)
            task = MonitorTask(config, SALE_1600)
            bridge._task = task
            bridge.driver = Mock()
            bridge.state = bridge.state.__class__(login_ready=True)
            bridge._ensure_driver = Mock(return_value=bridge.driver)
            bridge._start_monitor_heartbeat = Mock()
            bridge._make_param_filler = Mock(return_value=Mock(return_value=True))
            bridge._prepare_query_page = Mock(return_value=True)
            bridge._send_keep_alive = Mock()
            bridge._valid_dates = Mock(return_value=["2026-11-21"])
            bridge._wait_for_target_time = Mock(return_value=True)

            created_monitors = []

            def make_monitor(*args, **kwargs):
                m = TicketMonitor(*args, **kwargs)
                m.prepare = Mock(return_value=True)
                m._apply_loop_date = Mock()
                m._fill_query_params = Mock(return_value=True)
                m.run = Mock()
                created_monitors.append(m)
                return m

            fake_adapter = Mock()
            fake_adapter.prepare.side_effect = PrefillFallback("时区不符", stage="timezone_mismatch")

            with patch("railwatch_bridge.time.time", return_value=NOW_1550), \
                 patch("railwatch_bridge.guard_browser", return_value=nullcontext()), \
                 patch("railwatch_bridge.TicketMonitor", side_effect=make_monitor), \
                 patch("railwatch_bridge.PrefillAdapter", return_value=fake_adapter):
                bridge._monitor_worker(config, task)

            self.assertEqual(bridge._prepare_query_page.call_count, 2)
            created_monitors[0].run.assert_called_once()
            fake_adapter.execute_armed.assert_not_called()

    def test_armed_plan_whose_record_fails_falls_back_without_buying_through_prefill(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory, event_callback=lambda _: None)
            self.addCleanup(bridge.notification_service.close)
            config = dict(BASE_CONFIG)
            task = MonitorTask(config, SALE_1600)
            bridge._task = task
            bridge.driver = Mock()
            bridge.state = bridge.state.__class__(login_ready=True)
            bridge._ensure_driver = Mock(return_value=bridge.driver)
            bridge._start_monitor_heartbeat = Mock()
            bridge._make_param_filler = Mock(return_value=Mock(return_value=True))
            bridge._prepare_query_page = Mock(return_value=True)
            bridge._send_keep_alive = Mock()
            bridge._valid_dates = Mock(return_value=["2026-11-21"])
            bridge._wait_for_target_time = Mock(return_value=True)
            record = bridge.order_journal.mark

            def mark(run_id, stage, *args, **kwargs):
                if stage == "prefill_armed":
                    raise RuntimeError("database is locked")
                return record(run_id, stage, *args, **kwargs)

            bridge.order_journal.mark = mark
            created_monitors = []

            def make_monitor(*args, **kwargs):
                m = TicketMonitor(*args, **kwargs)
                m.prepare = Mock(return_value=True)
                m._apply_loop_date = Mock()
                m._fill_query_params = Mock(return_value=True)
                m.run = Mock()
                created_monitors.append(m)
                return m

            fake_adapter = Mock()
            fake_adapter.prepare.return_value = ArmedPrefillPlan(
                date="2026-11-21",
                passengers=("张三",),
                candidates=(PrefillCandidate("G8821", "2026-11-21", "大兴机场", "天津西", "二等座"),),
                target_timestamp=SALE_1600,
            )

            with patch("railwatch_bridge.time.time", return_value=NOW_1550),                  patch("railwatch_bridge.guard_browser", return_value=nullcontext()),                  patch("railwatch_bridge.TicketMonitor", side_effect=make_monitor),                  patch("railwatch_bridge.PrefillAdapter", return_value=fake_adapter):
                bridge._monitor_worker(config, task)

            fake_adapter.execute_armed.assert_not_called()
            self.assertEqual(bridge._prepare_query_page.call_count, 2)
            created_monitors[0].run.assert_called_once()
            stages = [event["stage"] for event in bridge.order_journal.run_events(task.run_id)]
            self.assertIn("prefill_fallback", stages)
            self.assertNotIn("prefill_armed", stages)


class BridgePrefillSafetyRegressionTests(unittest.TestCase):
    def bridge(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        bridge = RailWatchBridge(directory.name, event_callback=lambda _: None)
        self.addCleanup(bridge.notification_service.close)
        task = MonitorTask(BASE_CONFIG, SALE_1600)
        bridge._task = task
        bridge.driver = Mock()
        bridge.state = bridge.state.__class__(login_ready=True)
        bridge._ensure_driver = Mock(return_value=bridge.driver)
        bridge._start_monitor_heartbeat = Mock()
        bridge._make_param_filler = Mock(return_value=Mock(return_value=True))
        bridge._prepare_query_page = Mock(return_value=True)
        bridge._send_keep_alive = Mock()
        bridge._valid_dates = Mock(return_value=["2026-11-21"])
        bridge._wait_for_target_time = Mock(return_value=True)
        bridge._notify_async = Mock()
        return bridge, task

    def run_prefill_failure(self, result):
        bridge, task = self.bridge()
        monitors, run_states = [], []
        clock = [SALE_1600 - 90]
        waited = []
        def wait(current_task, seconds):
            self.assertIs(current_task, task)
            self.assertEqual(bridge._prepare_query_page.call_count, 1)
            waited.append(seconds)
            clock[0] += seconds
        bridge._task_wait = Mock(side_effect=wait)
        def monitor(*args, **kwargs):
            value = TicketMonitor(*args, **kwargs)
            value.prepare = Mock(return_value=True)
            value._apply_loop_date = Mock()
            value._fill_query_params = Mock(return_value=True)
            value.run = Mock(side_effect=lambda: run_states.append((sum(waited), value._needs_navigation)))
            monitors.append(value)
            return value
        adapter = Mock()
        fallback = PrefillFallback("查询需要等待或人工处理", stage="query_prepare", query_result=result)
        adapter.prepare.side_effect = fallback
        with patch("railwatch_bridge.time.time", side_effect=lambda: clock[0]), \
             patch("railwatch_bridge.guard_browser", return_value=nullcontext()), \
             patch("railwatch_bridge.TicketMonitor", side_effect=monitor), \
             patch("railwatch_bridge.PrefillAdapter", return_value=adapter):
            bridge._monitor_worker(dict(BASE_CONFIG), task)
        return bridge, task, monitors[0], waited, run_states

    def test_preparation_rate_limit_waits_full_server_cooldown_before_monitor(self):
        result = {"status": "rate_limited", "http_status": 429, "retry_after_seconds": 300}
        bridge, task, monitor, waited, run_states = self.run_prefill_failure(result)
        self.assertGreaterEqual(sum(waited), 300)
        self.assertEqual(run_states, [(sum(waited), True)])
        monitor.run.assert_called_once()
        self.assertTrue(monitor._needs_navigation)
        self.assertTrue(monitor._sale_retry_disabled)
        event = next(e for e in bridge.order_journal.run_events(task.run_id) if e["stage"] == "prefill_fallback")
        self.assertEqual(event["detail"]["query_status"], "rate_limited")
        self.assertEqual(event["detail"]["retry_after_seconds"], 300)

    def test_preparation_missing_cooldown_or_human_state_pauses_on_current_page(self):
        for result in ({"status": "rate_limited", "http_status": 429},
                       {"status": "human_action", "reason": "请完成核验"},
                       {"status": "unknown", "reason": "无法读取提示"}):
            with self.subTest(status=result["status"]):
                bridge, task, monitor, waited, _ = self.run_prefill_failure(result)
                self.assertTrue(task.cancel.is_set())
                self.assertEqual(task.status, "human_action")
                monitor.run.assert_not_called()
                self.assertEqual(bridge._prepare_query_page.call_count, 1)
                self.assertEqual(waited, [])
                self.assertTrue(bridge.state.human_action)

    def test_partial_prefill_fallback_keeps_regular_query_preference(self):
        bridge, task = self.bridge()
        plan = ArmedPrefillPlan("2026-11-21", ("张三",), (
            PrefillCandidate("G8821", "2026-11-21", "大兴机场", "天津西", "二等座"),
            PrefillCandidate("G8863", "2026-11-21", "北京大兴", "天津西", "二等座")), SALE_1600)
        monitors = []
        def monitor(*args, **kwargs):
            value = TicketMonitor(*args, **kwargs)
            value.prepare = Mock(return_value=True)
            value.run = Mock()
            monitors.append(value)
            return value
        adapter = Mock()
        adapter.prepare.return_value = plan
        adapter.execute_armed.return_value = PrefillExecutionOutcome("fallback_to_query", plan.candidates[:1])
        with patch("railwatch_bridge.time.time", return_value=NOW_1550), \
             patch("railwatch_bridge.guard_browser", return_value=nullcontext()), \
             patch("railwatch_bridge.TicketMonitor", side_effect=monitor), \
             patch("railwatch_bridge.PrefillAdapter", return_value=adapter):
            bridge._monitor_worker(dict(BASE_CONFIG), task)
        self.assertFalse(monitors[0]._prefer_alternate)
        self.assertTrue(monitors[0]._needs_navigation)
        self.assertFalse(monitors[0]._candidate_ready("G8821", "二等座", "book"))
        monitors[0].run.assert_called_once()

    def test_resume_ambiguous_prefill_click_only_reconciles(self):
        bridge, task = self.bridge()
        intent = OrderIntent("regular", "G1", "2026-11-21", "北京南", "上海虹桥", "二等座", ("张三",))
        bridge.order_journal.begin("original", intent, BASE_CONFIG)
        bridge.order_journal.mark("original", "prefill_submit", intent.intent_id)
        bridge.order_journal.record(intent, OrderResult("unknown"))
        page = Mock(spec=OrderPage)
        page.result.return_value = OrderResult("unknown")
        page.snapshot.return_value = {"formReady": True}
        page.regular.return_value = OrderResult("unknown")
        page.reconcile.return_value = OrderResult("unknown")
        with patch("railwatch_bridge.guard_browser", return_value=nullcontext()), \
             patch("railwatch_bridge.OrderPage", return_value=page):
            bridge._resume_order_worker(task, bridge.order_journal.pending())
        page.regular.assert_not_called()
        page.reconcile.assert_called_once_with(intent, known_id="", navigate=True, allow_empty=False)
        self.assertIsNotNone(bridge.order_journal.pending())


if __name__ == "__main__":
    unittest.main()
