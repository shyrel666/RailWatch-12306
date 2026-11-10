"""启动前已购行程检查：宁可漏报，不误拦；只读，读不到只警告。"""
from contextlib import nullcontext
import datetime as dt
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent
from railwatch_policies import ORDER_POLICIES, validate_order_policies
from railwatch_task import MonitorTask, TaskCancelled
from railwatch_train_schedules import TrainSchedules
from railwatch_trip_check import (ORDER_URL, TAB_STATE_JS, describe_trip, read_existing_orders, trip_conflicts)

BEIJING = dt.timezone(dt.timedelta(hours=8))
SALE = dt.datetime(2026, 11, 10, 16, 15, tzinfo=BEIJING).timestamp()
CONFIG = {"from_station_cn": "天津西", "to_station_cn": "大兴机场", "date": "2026-11-24", "date_range": "单日",
          "train_code": "G8846", "seat_keyword": "二等座", "passengers": "样本乘客1",
          "timer_enabled": True, "auto_submit": True, "auto_alternate": False,
          "sale_at": "2026-11-10T16:15:00+08:00", "interval": 3, "smart_rate": True}
DATES = ["2026-11-24"]


def card(**changes):
    """What OrderPage.snapshot reads from the real paid card sampled on 2026-11-10."""
    record = {"order_id": "EDEMOORDER1", "kind": "regular", "state": "已支付 退票", "state_conflict": False,
              "payment": False, "passengers": ["样本乘客1"], "train_codes": ["G8846"],
              "text": "天津西 大兴机场 G8846 2026-11-24 13:24 开 样本乘客1 打印信息单 居民身份证 "
                      "二等座 01车01A号 成人票 46.5元 已支付 退票"}
    record.update(changes)
    return record


class TripConflictTests(unittest.TestCase):
    def test_same_passenger_date_and_target_train_is_the_trip_the_task_would_buy_again(self):
        found = trip_conflicts([card()], CONFIG, DATES)
        self.assertEqual(found, [{"train": "G8846", "date": "2026-11-24",
                                  "from_station": "天津西", "to_station": "大兴机场"}])
        self.assertEqual(describe_trip(found[0]), "G8846 2026-11-24 天津西 → 大兴机场")
        self.assertNotIn("样本乘客1", json.dumps(found, ensure_ascii=False))
        self.assertNotIn("EDEMOORDER1", json.dumps(found, ensure_ascii=False))

    def test_target_train_matches_even_when_the_task_names_cities(self):
        found = trip_conflicts([card()], {**CONFIG, "from_station_cn": "天津", "to_station_cn": "北京"}, DATES)
        self.assertEqual(found, [{"train": "G8846", "date": "2026-11-24", "from_station": "", "to_station": ""}])
        self.assertEqual(describe_trip(found[0]), "G8846 2026-11-24")

    def test_another_train_counts_only_on_an_exact_station_pair(self):
        other = {**CONFIG, "train_code": "G8848"}
        self.assertEqual(trip_conflicts([card()], other, DATES)[0]["train"], "G8846")
        # Same city, different station: unknown whether it is the same trip, so no stop.
        for changes in ({"from_station_cn": "天津"}, {"to_station_cn": "北京大兴"}, {"from_station_cn": "天津南"},
                        {"from_station_cn": "大兴机场", "to_station_cn": "天津西"}):
            with self.subTest(changes=changes):
                self.assertEqual(trip_conflicts([card()], {**other, **changes}, DATES), [])
        city = {**other, "from_station_cn": "天津", "to_station_cn": "北京"}
        self.assertEqual(trip_conflicts([card()], city, DATES, [("天津南", "北京南")]), [])
        self.assertEqual(trip_conflicts([card()], city, DATES, [("天津西", "大兴机场")])[0]["from_station"], "天津西")

    def test_only_a_configured_passenger_on_a_task_date_counts(self):
        self.assertEqual(trip_conflicts([card(passengers=["别人"])], CONFIG, DATES), [])
        both = {**CONFIG, "passengers": "样本乘客1,样本乘客2"}
        self.assertEqual(len(trip_conflicts([card()], both, DATES)), 1)
        self.assertEqual(trip_conflicts([card()], CONFIG, ["2026-11-23", "2026-11-25"]), [])
        self.assertEqual(len(trip_conflicts([card()], CONFIG, ["2026-11-23", "2026-11-24", "2026-11-25"])), 1)

    def test_unidentified_inactive_or_ambiguous_records_never_stop_a_task(self):
        for label, changes in (
                ("no order identity", {"order_id": ""}),
                ("waitlist card", {"kind": "alternate"}),
                ("refunded", {"state": "已退票"}),
                ("unknown state", {"state": "已出站"}),
                ("empty state", {"state": ""}),
                ("mixed ticket states", {"state_conflict": True}),
                ("two travel dates on one order", {"text": card()["text"] + " 2026-11-25"}),
                ("no travel date", {"text": "天津西 大兴机场 G8846 二等座"}),
                ("placeholder", {"order_id": "", "passengers": [], "train_codes": [], "text": "", "state": ""})):
            with self.subTest(label):
                self.assertEqual(trip_conflicts([card(**changes)], CONFIG, DATES), [])
        self.assertEqual(trip_conflicts([None, "text", {}], CONFIG, DATES), [])
        self.assertEqual(trip_conflicts(None, CONFIG, DATES), [])

    def test_unpaid_order_counts_and_duplicates_collapse(self):
        unpaid = card(order_id="EDEMOORDER2", state="", payment=True)
        self.assertEqual(len(trip_conflicts([card(), unpaid], CONFIG, DATES)), 1)
        self.assertEqual(len(trip_conflicts([card(state="待支付")], CONFIG, DATES)), 1)

    def test_train_schedules_supply_the_actual_station_pairs_of_target_trains(self):
        with tempfile.TemporaryDirectory() as directory:
            schedules = TrainSchedules(directory)
            row = {"train": "G8848", "from_station": "天津西", "to_station": "大兴机场",
                   "departure_time": "15:00", "arrival_time": "15:53", "arrival_day_offset": 0}
            schedules.observe([row, {**row, "train": "G1", "from_station": "北京南", "to_station": "上海虹桥"}], "2026-11-24")
            self.assertEqual(schedules.routes(["G8848"]), [("天津西", "大兴机场")])
            self.assertEqual(schedules.routes([]), [])

    def test_policy_values_are_range_checked_and_leave_the_prefill_its_lead(self):
        self.assertIs(validate_order_policies(ORDER_POLICIES), ORDER_POLICIES)
        floor = ORDER_POLICIES["prefill_min_lead_seconds"] + ORDER_POLICIES["trip_check_timeout_seconds"]
        validate_order_policies({**ORDER_POLICIES, "trip_check_min_lead_seconds": floor})
        for key, value in (("trip_check_enabled", 1), ("trip_check_enabled", None), ("trip_check_timeout_seconds", 2),
                           ("trip_check_timeout_seconds", 31), ("trip_check_min_lead_seconds", floor - 1),
                           ("trip_check_min_lead_seconds", 901)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_order_policies({**ORDER_POLICIES, key: value})


class FakeTabs:
    """A driver and page whose order tabs change only through the tab control."""

    def __init__(self, unfinished, untraveled, *, unfinished_empty=True, loading=0, official=True):
        self.records = {"未完成订单": unfinished, "未出行订单": untraveled}
        self.unfinished_empty, self.loading, self.official = unfinished_empty, loading, official
        self.active, self.elapsed, self.handles, self.closed = "未完成订单", 0.0, ["main"], []
        self.tab = Mock()
        self.tab.click.side_effect = lambda: setattr(self, "active", "未出行订单")
        self.driver = Mock()
        self.driver.current_window_handle = "main"
        self.driver.window_handles = self.handles
        self.driver.timeouts.page_load = 30
        self.driver.switch_to.new_window.side_effect = self.open_tab
        self.driver.switch_to.window.side_effect = lambda handle: setattr(self.driver, "current_window_handle", handle)
        self.driver.close.side_effect = self.close_tab
        self.driver.execute_script.side_effect = lambda script: {"active": [self.active], "loading": self.loading}
        self.page = Mock(spec=OrderPage)
        self.page.driver, self.page.poll_interval = self.driver, 0.1
        self.page.stop = Mock(return_value=False)
        self.page.wait = Mock(side_effect=lambda seconds: setattr(self, "elapsed", self.elapsed + seconds))
        self.page.snapshot = Mock(side_effect=self.snapshot)
        self.page._recovery_tab = Mock(return_value=self.tab)

    def open_tab(self, kind):
        self.handles.append("temporary")
        self.driver.current_window_handle = "temporary"

    def close_tab(self):
        self.closed.append(self.driver.current_window_handle)
        self.handles.remove(self.driver.current_window_handle)

    def snapshot(self):
        if not self.official:
            return {}
        records = self.records[self.active]
        return {"url": ORDER_URL, "orders": list(records),
                "pendingEmpty": self.active == "未完成订单" and self.unfinished_empty and not records}

    def read(self, **options):
        with patch("railwatch_trip_check.time.monotonic", side_effect=lambda: self.elapsed):
            return read_existing_orders(self.page, **options)

    def assert_restored(self, case):
        case.assertEqual(self.closed, ["temporary"])
        case.assertEqual(self.handles, ["main"])
        case.assertEqual(self.driver.current_window_handle, "main")
        case.assertEqual(self.driver.set_page_load_timeout.call_args.args, (30,))


class ReadExistingOrdersTests(unittest.TestCase):
    FAILURE_PANEL = [{"order_id": "", "passengers": [], "train_codes": [], "text": "哎呀，出票失败了！", "state": ""}]

    def test_reads_both_tabs_in_a_temporary_tab_and_clicks_nothing_but_the_tab(self):
        unpaid, paid = card(order_id="E1", state="待支付"), card()
        tabs = FakeTabs([unpaid], [paid])
        timing = {}
        self.assertEqual(tabs.read(timing=timing), [unpaid, paid])
        tabs.driver.get.assert_called_once_with(ORDER_URL)
        tabs.page._recovery_tab.assert_called_once_with("未出行订单", ORDER_URL)
        tabs.tab.click.assert_called_once()
        self.assertEqual({call.args[0] for call in tabs.driver.execute_script.call_args_list}, {TAB_STATE_JS})
        # Only the second, agreeing read of the list is waited for.
        self.assertAlmostEqual(tabs.elapsed, 0.1, places=6)
        self.assertEqual(timing, {"navigation_ms": 0, "tabs_ms": 0, "untraveled_ms": 100})
        tabs.assert_restored(self)

    def test_live_failure_of_2026_11_10_slow_page_and_failure_panel_still_reads_the_paid_ticket(self):
        # The order page took over seven seconds to load, and the unfinished tab kept a
        # failure panel: no order and no official "none" statement. Ten seconds were not
        # enough while that tab was waited on first.
        tabs = FakeTabs(self.FAILURE_PANEL, [card()], unfinished_empty=False)
        tabs.driver.get.side_effect = lambda url: setattr(tabs, "elapsed", tabs.elapsed + 7.5)
        timing = {}
        self.assertEqual(tabs.read(budget=10.0, timing=timing), [card()])
        self.assertAlmostEqual(tabs.elapsed, 7.6, places=6)
        self.assertEqual(timing, {"navigation_ms": 7500, "tabs_ms": 0, "untraveled_ms": 100})
        tabs.assert_restored(self)

    def test_empty_untraveled_tab_is_concluded_only_after_the_full_settle(self):
        tabs = FakeTabs([], [])
        self.assertEqual(tabs.read(settle=3.0), [])
        self.assertAlmostEqual(tabs.elapsed, 3.0, places=6)
        tabs.assert_restored(self)

    def test_list_that_is_still_growing_is_read_once_two_reads_agree(self):
        first, second = card(order_id="E1"), card(order_id="E2")
        tabs = FakeTabs([], [first])
        grow = iter([lambda: tabs.records["未出行订单"].append(second)])
        def wait(seconds):
            tabs.elapsed += seconds
            next(grow, lambda: None)()
        tabs.page.wait.side_effect = wait
        self.assertEqual(tabs.read(), [first, second])

    def test_unreadable_pages_return_none_with_the_reason_and_still_restore_the_browser(self):
        cases = {"not_official_page": FakeTabs([], [], official=False),
                 "loading": FakeTabs([], [], loading=1),
                 "tab_control_missing": FakeTabs([], [])}
        cases["tab_control_missing"].page._recovery_tab.return_value = None
        stuck = FakeTabs([], [card()])
        stuck.tab.click.side_effect = None  # The click does not activate the tab.
        cases["tab_not_active"] = stuck
        for reason, tabs in cases.items():
            with self.subTest(reason):
                timing = {}
                self.assertIsNone(tabs.read(settle=1.0, timing=timing))
                self.assertEqual(timing["reason"], reason)
                tabs.assert_restored(self)

    def test_budget_bounds_the_whole_read_and_a_cut_wait_never_means_empty(self):
        tabs = FakeTabs([], [])
        tabs.driver.get.side_effect = lambda url: setattr(tabs, "elapsed", tabs.elapsed + 8.0)
        timing = {}
        self.assertIsNone(tabs.read(budget=10.0, settle=3.0, timing=timing))
        self.assertLessEqual(tabs.elapsed, 10.0 + 1e-6)
        self.assertEqual((timing["reason"], timing["navigation_ms"]), ("budget", 8000))
        tabs.assert_restored(self)
        # A ticket that does show within the remaining time is still found.
        late = FakeTabs([], [card()])
        late.driver.get.side_effect = lambda url: setattr(late, "elapsed", late.elapsed + 9.5)
        self.assertEqual(late.read(budget=10.0), [card()])

    def test_navigation_failure_keeps_its_timing_and_restores_the_browser(self):
        tabs = FakeTabs([], [card()])
        def timeout(url):
            tabs.elapsed += 20.0
            raise RuntimeError("page load timed out")
        tabs.driver.get.side_effect = timeout
        timing = {}
        with self.assertRaises(RuntimeError):
            tabs.read(timing=timing)
        self.assertEqual(timing, {"navigation_ms": 20000})
        tabs.assert_restored(self)

    def test_cancellation_unwinds_and_restores_the_original_tab(self):
        tabs = FakeTabs([], [])
        tabs.page.stop.side_effect = lambda: tabs.elapsed >= 0.5
        with self.assertRaises(TaskCancelled):
            tabs.read()
        tabs.assert_restored(self)
        before = FakeTabs([], [])
        before.page.stop.return_value = True
        with self.assertRaises(TaskCancelled):
            before.read()
        before.driver.switch_to.new_window.assert_not_called()


class BridgeTripCheckTests(unittest.TestCase):
    def bridge(self, config=CONFIG, *, now=SALE - 600):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        events = []
        bridge = RailWatchBridge(directory.name, event_callback=events.append)
        self.addCleanup(bridge.notification_service.close)
        task = MonitorTask(dict(config), SALE if config.get("timer_enabled") else None)
        bridge._task = task
        bridge.driver = Mock()
        bridge._notify_async = Mock()
        clock = patch("railwatch_bridge.time.time", return_value=now)
        clock.start()
        self.addCleanup(clock.stop)
        return bridge, task, events

    TIMING = {"navigation_ms": 7200, "tabs_ms": 40, "untraveled_ms": 300}

    def check(self, bridge, task, orders, reason=None):
        def read_orders(page, *, budget, timing):
            timing.update(self.TIMING, **({"reason": reason} if reason else {}))
            return orders
        with patch("railwatch_bridge.read_existing_orders", side_effect=read_orders) as read:
            blocked = bridge._existing_trip_blocks(bridge.driver, task.config, task)
        return blocked, read

    def results(self, bridge, task):
        return [event["detail"] for event in bridge.order_journal.run_events(task.run_id) if event["stage"] == "trip_check"]

    def test_held_trip_stops_the_task_and_names_only_the_trip(self):
        bridge, task, events = self.bridge()
        blocked, read = self.check(bridge, task, [card()])
        self.assertTrue(blocked)
        self.assertTrue(task.cancel.is_set())
        self.assertEqual(read.call_args.kwargs["budget"], ORDER_POLICIES["trip_check_timeout_seconds"])
        action = bridge.state.human_action
        self.assertEqual(action["title"], "已有同行程车票")
        self.assertIn("G8846 2026-11-24 天津西 → 大兴机场", action["message"])
        self.assertIn("未取消或修改任何订单", action["message"])
        self.assertEqual(self.results(bridge, task), [{"result": "conflict", "trips": [
            {"train": "G8846", "date": "2026-11-24", "from_station": "天津西", "to_station": "大兴机场"}], **self.TIMING}])
        # The task's own settings name its passengers; what the check itself reports must not.
        reported = [event for event in events if event["event"] in ("humanAction", "log")]
        self.assertEqual({event["event"] for event in reported}, {"humanAction", "log"})
        told = json.dumps([reported, self.results(bridge, task), dict(action)], ensure_ascii=False, default=str)
        self.assertNotIn("样本乘客1", told)
        self.assertNotIn("EDEMOORDER1", told)
        bridge._notify_async.assert_called_once()
        bridge.driver.set_page_load_timeout.assert_called_with(30)

    def test_clear_or_unrelated_orders_let_the_task_continue(self):
        for orders in ([], [card(passengers=["别人"])], [card(text=card()["text"].replace("2026-11-24", "2026-11-25"))]):
            with self.subTest(orders=len(orders)):
                bridge, task, _ = self.bridge()
                blocked, _ = self.check(bridge, task, orders)
                self.assertFalse(blocked)
                self.assertFalse(task.cancel.is_set())
                self.assertEqual(self.results(bridge, task), [{"result": "clear", "orders": len(orders), **self.TIMING}])
                self.assertFalse(bridge.state.human_action)

    def test_unreadable_orders_only_warn_and_record_where_the_time_went(self):
        bridge, task, _ = self.bridge()
        logs = []
        bridge.log = lambda message, level="INFO": logs.append((level, message))
        blocked, _ = self.check(bridge, task, None, reason="budget")
        self.assertFalse(blocked)
        self.assertFalse(task.cancel.is_set())
        self.assertEqual(self.results(bridge, task), [{"result": "unreadable", "reason": "budget", **self.TIMING}])
        self.assertEqual(logs, [("WARN", "未能读取官方未出行订单（超出检查时限；打开订单页 7.2 秒，等待标签 0.0 秒，读取未出行订单 0.3 秒），"
                                         "已跳过已购行程检查，任务继续；请自行确认未重复购票。")])

    def test_failed_read_only_warns_with_the_error_type_and_no_account_data(self):
        bridge, task, _ = self.bridge()
        logs = []
        bridge.log = lambda message, level="INFO": logs.append((level, message))
        def fail(page, *, budget, timing):
            timing["navigation_ms"] = 20000
            raise RuntimeError("样本乘客1 EDEMOORDER1")
        with patch("railwatch_bridge.read_existing_orders", side_effect=fail):
            self.assertFalse(bridge._existing_trip_blocks(bridge.driver, task.config, task))
        self.assertFalse(task.cancel.is_set())
        self.assertEqual(self.results(bridge, task), [{"result": "unreadable", "navigation_ms": 20000, "reason": "RuntimeError"}])
        self.assertIn("读取中断（RuntimeError）；打开订单页 20.0 秒", logs[0][1])
        self.assertNotIn("样本乘客1", str(logs))
        self.assertNotIn("EDEMOORDER1", str(logs))

    def test_lost_browser_session_is_not_swallowed(self):
        from selenium.common.exceptions import InvalidSessionIdException
        bridge, task, _ = self.bridge()
        with patch("railwatch_bridge.read_existing_orders", side_effect=InvalidSessionIdException("gone")), \
                self.assertRaises(InvalidSessionIdException):
            bridge._existing_trip_blocks(bridge.driver, task.config, task)

    def test_check_is_skipped_close_to_the_sale_without_touching_the_browser(self):
        lead = ORDER_POLICIES["trip_check_min_lead_seconds"]
        bridge, task, _ = self.bridge(now=SALE - lead + 1)
        blocked, read = self.check(bridge, task, [card()])
        self.assertFalse(blocked)
        read.assert_not_called()
        self.assertEqual(self.results(bridge, task), [{"result": "skipped"}])
        bridge, task, _ = self.bridge(now=SALE - lead)
        self.assertTrue(self.check(bridge, task, [card()])[0])

    def test_immediate_tasks_are_checked_and_reminder_only_tasks_are_not(self):
        bridge, task, _ = self.bridge({**CONFIG, "timer_enabled": False, "auto_submit": False, "auto_alternate": True})
        self.assertTrue(self.check(bridge, task, [card()])[0])
        bridge, task, _ = self.bridge({**CONFIG, "auto_submit": False})
        blocked, read = self.check(bridge, task, [card()])
        self.assertFalse(blocked)
        read.assert_not_called()
        self.assertEqual(self.results(bridge, task), [])

    def test_packaged_switch_and_an_unresolved_order_disable_the_check(self):
        bridge, task, _ = self.bridge()
        with patch.dict("railwatch_policies.ORDER_POLICIES", {"trip_check_enabled": False}):
            blocked, read = self.check(bridge, task, [card()])
        self.assertFalse(blocked)
        read.assert_not_called()
        bridge, task, _ = self.bridge()
        bridge.order_journal.begin("earlier", OrderIntent("regular", "G1", "2026-11-24", "北京南", "上海虹桥", "二等座", ("样本乘客1",)), {})
        blocked, read = self.check(bridge, task, [card()])
        self.assertFalse(blocked)
        read.assert_not_called()

    def test_last_seen_station_pairs_of_target_trains_extend_the_route_match(self):
        bridge, task, _ = self.bridge({**CONFIG, "train_code": "G8848", "from_station_cn": "天津", "to_station_cn": "北京"})
        self.assertFalse(self.check(bridge, task, [card()])[0])
        bridge, task, _ = self.bridge({**CONFIG, "train_code": "G8848", "from_station_cn": "天津", "to_station_cn": "北京"})
        bridge.train_schedules.observe([{"train": "G8848", "from_station": "天津西", "to_station": "大兴机场",
                                         "departure_time": "15:00", "arrival_time": "15:53", "arrival_day_offset": 0}], "2026-11-24")
        self.assertTrue(self.check(bridge, task, [card()])[0])

    def test_worker_stops_before_creating_a_monitor_or_preparing_the_prefill(self):
        bridge, task, _ = self.bridge()
        bridge.state = bridge.state.__class__(login_ready=True)
        bridge._ensure_driver = Mock(return_value=bridge.driver)
        bridge._start_monitor_heartbeat = Mock()
        bridge._make_param_filler = Mock(return_value=Mock(return_value=True))
        bridge._prepare_query_page = Mock(return_value=True)
        bridge._send_keep_alive = Mock()
        with patch("railwatch_bridge.guard_browser", return_value=nullcontext()), \
                patch("railwatch_bridge.read_existing_orders", return_value=[card()]), \
                patch("railwatch_bridge.TicketMonitor") as monitor, patch("railwatch_bridge.PrefillAdapter") as adapter:
            bridge._monitor_worker(task.config, task)
        monitor.assert_not_called()
        adapter.assert_not_called()
        self.assertEqual(bridge.state.human_action["title"], "已有同行程车票")
        self.assertIsNone(bridge.order_journal.pending())


class LiveConflictNoticeTests(unittest.TestCase):
    """官方行程冲突提示（2026-11-10 实测原文）给出明确原因，仍保留提交权限。"""

    def setUp(self):
        sample = json.loads((Path(__file__).parent / "fixtures/order-conflict-live-20261110.json").read_text(encoding="utf-8"))
        # The snapshot collapses whitespace the same way.
        self.dialogs = [re.sub(r"\s+", " ", item["text"]).strip() for item in sample["observations"][0]["dialogs"]]
        self.page = OrderPage(Mock(), wait=lambda _: None)
        self.intent = OrderIntent("regular", "G8846", "2026-11-24", "天津西", "大兴机场", "二等座", ("样本乘客1",))

    def snap(self, **changes):
        return {"url": "https://kyfw.12306.cn/otn/confirmPassenger/initDc", "orders": [], "dialogs": self.dialogs, **changes}

    def test_both_layers_of_the_live_notice_read_as_one_conflict(self):
        self.assertEqual(len(self.dialogs), 2)
        for submitted in (True, False):
            result = self.page._result_from_snapshot(self.snap(), self.intent, submitted=submitted)
            self.assertEqual(result.status, "verification")
            self.assertIn("行程冲突", result.reason)
            self.assertIn("不会自动重试", result.reason)
            self.assertTrue(result.evidence["trip_conflict"])
            self.assertFalse(result.no_order)
            self.assertFalse(result.can_fallback)
            self.assertNotIn("身份已脱敏", result.reason)

    def test_a_delivered_confirmation_is_not_reconciled_or_resubmitted(self):
        self.page.snapshot = lambda: self.snap()
        result = self.page._post_submit(self.intent, True)
        self.assertEqual(result.status, "verification")
        self.assertIn("行程冲突", result.reason)
        self.page.driver.get.assert_not_called()

    def test_other_or_mixed_prompts_keep_their_own_handling(self):
        generic = "存在未识别的订单提示，请在官方页面检查"
        for label, changes, reason in (
                ("another dialog beside it", {"dialogs": self.dialogs + ["请完成其他操作"]}, generic),
                ("captcha takes precedence", {"verification": True}, "请在官方页面完成登录、核验或处理限制"),
                ("queue still shown", {"processing": True}, "官方仍在处理订单，请勿重复提交"),
                ("different failure", {"dialogs": ["提示 订票失败! 原因： 当前时间不可以订票"]}, generic)):
            with self.subTest(label):
                self.assertEqual(self.page._result_from_snapshot(self.snap(**changes), self.intent, submitted=True).reason, reason)


if __name__ == "__main__":
    unittest.main()
