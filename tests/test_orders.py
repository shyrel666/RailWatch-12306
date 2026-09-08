"""Order ownership and failure combinations: no live railway requests."""
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import nullcontext

from gui_12306_0 import TicketMonitor
from railwatch_bridge import RailWatchBridge
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_order_page import OrderPage
from railwatch_time import ServerTimeSync, resolve_sale_timestamp
from railwatch_task import MonitorTask


CONFIG = {"date": "2026-09-10", "from_station_cn": "北京", "to_station_cn": "上海",
          "passengers": "张三", "seat_keyword": "二等座", "train_code": "G101,G102",
          "auto_submit": True, "auto_alternate": True, "alternate_deadline": "18:00"}


def intent(kind="regular"):
    return OrderIntent.from_config(CONFIG, "G101", "二等座", kind)


def snapshot(state="待支付", **changes):
    value = {"url": "https://kyfw.12306.cn/otn/view/train_order.html", "dialogs": [],
             "orders": [{"order_id": "E123456", "kind": "regular", "text": "G101 2026-09-10 北京 上海 二等座 张三",
                         "state": state, "passengers": ["张三"]}]}
    value.update(changes)
    return value


class OrderEvidenceTests(unittest.TestCase):
    def read(self, value, selected=None, **kwargs):
        driver = Mock()
        driver.execute_script.return_value = value
        return OrderPage(driver).result(selected or intent(), **kwargs)

    def test_matching_order_required_for_success(self):
        for status, expected in [("待支付", "pending_payment"), ("已支付", "fulfilled"),
                                 ("已取消", "cancelled"), ("支付超时", "expired")]:
            with self.subTest(status=status):
                self.assertEqual(self.read(snapshot(status)).status, expected)
        for field, value in [("text", "G1010 2026-09-10 北京 上海 二等座 张三"),
                             ("text", "G101 2026-09-11 北京 上海 二等座 张三"),
                             ("text", "G101 2026-09-10 北京 上海 一等座 张三"),
                             ("passengers", ["张三丰"]), ("passengers", ["张三", "李四"]), ("order_id", "")]:
            data = snapshot()
            data["orders"][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.read(data).status, "unknown")

    def test_houbu_payment_is_not_fulfillment(self):
        for state, expected in [("已支付", "active"), ("待兑现", "active"), ("兑现成功", "fulfilled"), ("兑现失败", "failed")]:
            value = snapshot(state)
            value["orders"][0]["kind"] = "alternate"
            self.assertEqual(self.read(value, intent("alternate")).status, expected)

    def test_multi_combination_reverse_route_and_order_kind_rejected(self):
        for change in [{"text": "G101 G102 2026-09-10 北京 上海 二等座 张三"},
                       {"text": "G101 2026-09-10 北京 上海 二等座 一等座 张三"},
                       {"text": "G101 2026-09-10 2026-09-11 北京 上海 二等座 张三"},
                       {"text": "G101 2026-09-10 上海 北京 二等座 张三"}, {"kind": "alternate"}]:
            value = snapshot()
            value["orders"][0].update(change)
            self.assertEqual(self.read(value).status, "unknown")

    def test_generic_success_url_and_untrusted_origin_are_not_evidence(self):
        self.assertEqual(self.read(snapshot(orders=[], url="https://kyfw.12306.cn/otn/queryMyOrderNoComplete", dialogs=["提交成功"])).status, "verification")
        self.assertEqual(self.read(snapshot(url="https://other.example/order")).status, "unknown")
        self.assertEqual(self.read(snapshot(url="file:///fake-order.html")).status, "unknown")
        self.assertEqual(self.read(snapshot(), known_id="OTHER").status, "unknown")

    def test_timeout_is_unknown_and_explicit_rejection_after_submit_requires_reconciliation(self):
        data = snapshot(orders=[], dialogs=["余票不足"])
        self.assertTrue(self.read(data, submitted=False).can_fallback)
        self.assertFalse(self.read(data, submitted=True).can_fallback)
        self.assertEqual(self.read(snapshot(orders=[], processing=True)).status, "unknown")
        self.assertEqual(self.read(snapshot(orders=[])).status, "unknown")

    def test_verification_limits_and_unknown_dialogs(self):
        for dialog in ["需要人脸核验", "登录失效", "操作过快", "候补订单已达上限", "未知业务提示"]:
            self.assertEqual(self.read(snapshot(orders=[], dialogs=[dialog])).status, "verification")

    def test_empty_pending_view_cannot_erase_known_order(self):
        data = snapshot(orders=[], pendingEmpty=True)
        self.assertTrue(self.read(data).no_order)
        self.assertEqual(self.read(data, known_id="E123456").status, "unknown")
        self.assertEqual(self.read(data, submitted=True).status, "unknown")
        self.assertTrue(self.read(data, submitted=True, allow_empty=True).no_order)

    def test_deadline_requires_date_and_exact_time(self):
        self.assertTrue(OrderPage.deadline_matches("2026年9月10日 18:00", "18:00", "2026-09-10"))
        self.assertFalse(OrderPage.deadline_matches("2026年9月9日 18:00", "18:00", "2026-09-10"))
        self.assertFalse(OrderPage.deadline_matches("开车前20分钟", "18:00", "2026-09-10"))
        self.assertTrue(OrderPage.deadline_matches("开车前1小时", "开车前60分钟", "2026-09-10"))
        self.assertFalse(OrderPage.deadline_matches("开车前20分钟", "开车前60分钟", "2026-09-10"))


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "orders.sqlite3"
        self.journal = OrderJournal(self.path)

    def test_crash_after_intent_before_result_blocks_new_submission(self):
        original = intent()
        self.journal.begin("first", original, CONFIG)
        restarted = OrderJournal(self.path)
        self.assertEqual(restarted.pending()["intent"]["intent_id"], original.intent_id)
        with self.assertRaises(RuntimeError): restarted.begin("second", intent(), CONFIG)
        restarted.record(original, OrderResult("pending_payment", order_id="E123456", evidence={"matched": True}))
        with self.assertRaises(RuntimeError): restarted.begin("second", intent(), CONFIG)

    def test_unknown_sold_out_keeps_ownership_and_verified_rejection_releases_it(self):
        original = intent()
        self.journal.begin("first", original, CONFIG)
        self.journal.record(original, OrderResult("sold_out"))
        self.assertIsNotNone(self.journal.pending())
        self.journal.record(original, OrderResult("sold_out", no_order=True))
        self.assertIsNone(self.journal.pending())

    def test_journal_rejects_unproven_success_and_preserves_known_order_during_verification(self):
        original = intent()
        self.journal.begin("first", original, CONFIG)
        for result in [OrderResult("fulfilled"), OrderResult("pending_payment", order_id="E123456"), OrderResult("not_submitted")]:
            self.assertEqual(self.journal.record(original, result).status, "unknown")
            self.assertIsNotNone(self.journal.pending())
        self.journal.record(original, OrderResult("pending_payment", order_id="E123456", evidence={"matched": True}))
        self.assertEqual(self.journal.record(original, OrderResult("verification")).order_id, "E123456")
        result = self.journal.record(original, OrderResult("not_submitted", no_order=True))
        self.assertEqual((result.status, result.order_id), ("unknown", "E123456"))

    def test_submit_marker_cannot_be_replayed_or_stolen_from_resume_owner(self):
        original = intent()
        self.journal.begin("first", original, CONFIG)
        self.journal.claim_resume("resume", original.intent_id)
        with self.assertRaises(RuntimeError): self.journal.mark("first", "regular_submit", original.intent_id)
        self.journal.mark("resume", "regular_submit", original.intent_id)
        with self.assertRaises(RuntimeError): self.journal.mark("resume", "regular_submit", original.intent_id)

    def test_atomic_claim_across_connections_and_resume(self):
        other = OrderJournal(self.path)
        original = intent()
        self.journal.begin("first", original, CONFIG)
        self.assertTrue(self.journal.claim_resume("resume", original.intent_id))
        self.assertFalse(other.claim_resume("other", original.intent_id))
        self.journal.release_resume("resume", original.intent_id)
        self.journal.mark("first", "regular_submit", original.intent_id)
        self.assertFalse(other.claim_resume("other", original.intent_id))

    def test_only_one_concurrent_submission(self):
        barrier = threading.Barrier(2)
        successes = []
        def begin():
            barrier.wait()
            try:
                OrderJournal(self.path).begin("race", intent(), CONFIG)
                successes.append(True)
            except RuntimeError: pass
        threads = [threading.Thread(target=begin) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(successes), 1)

    def test_bridge_restores_pending_state_without_browser_or_order_replay(self):
        original = intent("alternate")
        self.journal.begin("first", original, CONFIG)
        self.journal.record(original, OrderResult("pending_payment", order_id="E123456", evidence={"matched": True}))
        bridge = RailWatchBridge(self.temp.name)
        self.assertIsNone(bridge.driver)
        self.assertTrue(bridge.state.order["recovery_required"])
        self.assertEqual(bridge.state.order["stage"], "alternate_pending_payment")
        with self.assertRaises(RuntimeError): bridge.start_monitor(CONFIG, confirmed=True)

    def test_restart_reconciles_existing_pending_order_without_submitting_again(self):
        original = intent()
        self.journal.begin("first", original, CONFIG)
        self.journal.mark("first", "regular_submit", original.intent_id)
        bridge = RailWatchBridge(self.temp.name)
        bridge._task = task = MonitorTask(CONFIG)
        page = Mock()
        page.result.return_value = OrderResult("pending_payment", order_id="E123456", evidence={"matched": True})
        with patch.object(bridge, "_ensure_driver", return_value=Mock()), patch.object(bridge, "_start_monitor_heartbeat"), patch.object(bridge, "_observe_order"), patch.object(bridge, "_notify_async"), patch("railwatch_bridge.guard_browser", return_value=nullcontext()), patch("railwatch_bridge.OrderPage", return_value=page):
            bridge._resume_order_worker(task, self.journal.pending())
        page.regular.assert_not_called()
        page.alternate.assert_not_called()
        self.assertEqual(bridge.state.order["order_id"], "E123456")


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = OrderJournal(Path(self.temp.name) / "orders.sqlite3")
        self.events, self.humans = [], []
        self.monitor = TicketMonitor(Mock(), CONFIG, log_callback=lambda _: None,
                                     order_journal=self.journal, run_id="test", on_order=lambda *args: self.events.append(args),
                                     human_action_callback=self.humans.append)
        self.hit = ("G101", "二等座", "有", Mock(), Mock(), "book")

    def test_regular_rejection_routes_to_houbu_without_sleep(self):
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=OrderResult("sold_out", no_order=True))
        self.monitor._sleep = Mock()
        self.assertFalse(self.monitor._execute_order(self.hit))
        self.assertTrue(self.monitor._prefer_alternate)
        self.assertTrue(self.monitor._needs_navigation)
        self.monitor._sleep.assert_not_called()
        self.assertIsNone(self.journal.pending())
        self.monitor.travel_dates = ["2026-09-10", "2026-09-11"]
        self.monitor._apply_loop_date(2)
        self.assertEqual(self.monitor.current_loop_date, "2026-09-10")

    def test_unknown_submission_stops_and_retains_intent_without_houbu(self):
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=OrderResult("unknown"))
        self.monitor.alternate_flow.try_alternate_order = Mock()
        self.assertTrue(self.monitor._execute_order(self.hit))
        self.monitor.alternate_flow.try_alternate_order.assert_not_called()
        self.assertIsNotNone(self.journal.pending())
        self.assertEqual(len(self.humans), 1)

    def test_legacy_none_is_unknown_not_success(self):
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=None)
        self.monitor._execute_order(self.hit)
        self.assertEqual(self.events[-1][1].status, "unknown")

    def test_failed_result_persistence_stops_on_current_page_and_retains_intent(self):
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=OrderResult("unknown"))
        with patch.object(self.journal, "record", side_effect=OSError("disk full")):
            self.assertTrue(self.monitor._execute_order(self.hit))
        self.assertIsNotNone(self.journal.pending())
        self.monitor.driver.get.assert_not_called()

    def test_all_rows_checked_then_user_priority_applied(self):
        rows = [Mock(text="G102 北京 上海"), Mock(text="G101 北京 上海")]
        self.monitor.driver.find_element.return_value.find_elements.return_value = rows
        self.monitor._find_book_button = lambda row: row
        self.monitor._find_alternate_button = lambda row, seat: row
        self.monitor._get_seat_value = lambda row, *args: "无" if row is rows[0] else "有"
        self.assertEqual(self.monitor._find_hit_row({})[0], "G101")
        self.monitor._get_seat_value = lambda *args: "有"
        self.assertEqual(self.monitor._find_hit_row({})[0], "G101")
        self.monitor._get_seat_value = lambda *args: "无"
        hit = self.monitor._find_hit_row({})
        self.assertEqual((hit[0], hit[-1]), ("G101", "alternate"))

    def test_failed_final_submit_reconciles_before_fallback(self):
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=OrderResult("unknown", "官方提示余票不足"))
        self.monitor.order_page.reconcile = Mock(return_value=OrderResult("pending_payment", order_id="E123456", evidence={"matched": True}))
        self.assertTrue(self.monitor._execute_order(self.hit))
        self.assertFalse(self.monitor._prefer_alternate)
        self.assertEqual(self.journal.pending()["result"]["order_id"], "E123456")


class ScheduleTests(unittest.TestCase):
    def test_hot_clock_never_syncs_or_applies_http_offset(self):
        clock = ServerTimeSync()
        clock._offset_seconds = 180
        clock.sync = Mock(side_effect=AssertionError("network in hot path"))
        with patch("railwatch_time.time.time", return_value=100):
            self.assertEqual(clock.server_timestamp(), 100)
        clock.sync.assert_not_called()

    def test_explicit_beijing_sale_time_required(self):
        for config in [{"target_time": "08:00:00"}, {"sale_at": "2026-09-10T08:00:00"}, {"sale_at": "2026-09-10T08:00:00Z"}]:
            with self.assertRaises(ValueError): resolve_sale_timestamp(config)
        self.assertGreater(resolve_sale_timestamp({"sale_at": "2026-09-10T08:00:00+08:00"}), 0)

    def test_freeze_window_has_no_navigation_or_network_and_stops_on_clock_jump(self):
        for jump in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                bridge = RailWatchBridge(tmp)
                bridge._task = MonitorTask({})
                bridge._send_keep_alive = Mock()
                bridge._prewarm_query_page = Mock()
                wall, mono = [100.0], [100.0]
                def wait(seconds):
                    wall[0] += seconds + (2 if jump else 0)
                    mono[0] += seconds
                bridge._task.cancel.wait = wait
                with patch("railwatch_bridge.time.time", lambda: wall[0]), patch("railwatch_bridge.time.monotonic", lambda: mono[0]):
                    self.assertEqual(bridge._wait_for_target_timestamp(101, {"keep_alive": True}), not jump)
                bridge._send_keep_alive.assert_not_called()
                bridge._prewarm_query_page.assert_not_called()

    def test_resume_and_user_stop_cancel_wait_without_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            bridge._task = MonitorTask({})
            bridge._notify_async = Mock()
            bridge.system_resumed()
            self.assertTrue(bridge._task.cancel.is_set())
            self.assertFalse(bridge._wait_for_target_timestamp(10**12, {}))


if __name__ == "__main__":
    unittest.main()
