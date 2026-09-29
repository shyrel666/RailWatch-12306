"""Order ownership and failure combinations: no live railway requests."""
import tempfile
import threading
import unittest
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import nullcontext

from gui_12306_0 import TicketMonitor
from railwatch_bridge import RailWatchBridge
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_order_page import OrderPage, seat_label
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
    def test_priced_seat_labels_preserve_exact_class(self):
        for value in ('二等座（927.0元）', '二等座 (￥927.00元)', '二等座（¥927元）', '二等座'):
            self.assertEqual(seat_label(value), '二等座')
        for value in ('高级软卧', '二等座/一等座', '二等座（不可用）'):
            self.assertEqual(seat_label(value), value)

    def test_regular_form_requires_exact_route_train_and_seat(self):
        selected = replace(intent(), from_station='北京丰台', to_station='成都东')
        data = {'regular': '2026-09-10（周四） G101次 北京丰台站（09:29开）—成都东站（19:00到）',
                'passengers': ['张三'], 'seats': ['二等座（927.0元）'], 'ticketTypes': ['成人票']}
        page = OrderPage(Mock())
        page.snapshot = lambda: data
        self.assertTrue(page.verify_form(selected))
        for ticket_type in ([], ["学生票"], ["儿童票"]):
            page.snapshot = lambda ticket_type=ticket_type: {**data, "ticketTypes": ticket_type}
            self.assertFalse(page.verify_form(selected))
        page.snapshot = lambda: data
        for changed in (replace(selected, from_station='北京'), replace(selected, to_station='成都'),
                        replace(selected, train_code='G10'), replace(selected, seat='一等座'),
                        replace(selected, from_station='成都东', to_station='北京丰台')):
            self.assertFalse(page.verify_form(changed))

    def test_packed_official_summary_without_spaces_verifies(self):
        # The official confirm page glues tokens together; measured 2026-09-11:
        # 2026-09-12（周六）G1307次北京丰台站（09:29开）—成都东站（19:00到）
        selected = replace(intent(), from_station='北京丰台', to_station='成都东', train_code='G1307')
        data = {'regular': '2026-09-10（周四）G1307次北京丰台站（09:29开）—成都东站（19:00到）',
                'passengers': ['张三'], 'seats': ['二等座（¥927.0元）'], 'ticketTypes': ['成人票']}
        page = OrderPage(Mock())
        page.snapshot = lambda: data
        self.assertTrue(page.verify_form(selected))
        # A longer station or train sharing the prefix must still be rejected.
        for changed in (replace(selected, from_station='北京'), replace(selected, to_station='成都'),
                        replace(selected, train_code='G130'), replace(selected, train_code='G13071')):
            self.assertFalse(page.verify_form(changed))

    def test_train_and_station_tokens_reject_extension_only(self):
        from railwatch_order_page import form_token, train_token
        packed = '2026-09-10（周四）G101次北京丰台站（09:29开）—上海虹桥站（19:00到）'
        self.assertTrue(train_token(packed, 'G101'))
        self.assertFalse(train_token(packed, 'G10'))
        self.assertFalse(train_token(packed, 'G1011'))
        self.assertFalse(train_token('G1010次', 'G101'))
        self.assertTrue(form_token(packed, '北京丰台', '站'))
        self.assertFalse(form_token(packed, '北京', '站'))
        self.assertTrue(form_token(packed, '上海虹桥', '站'))
        self.assertFalse(form_token(packed, '上海', '站'))
        self.assertFalse(form_token(packed, '丰台', '站'))

    def test_order_record_matches_packed_official_text(self):
        record = {'order_id': 'E123456', 'kind': 'regular',
                  'text': 'G1307 2026年09月10日 北京丰台—成都东 二等座（¥927.0元） 张三',
                  'state': '待支付', 'passengers': ['张三']}
        selected = replace(intent(), from_station='北京丰台', to_station='成都东', train_code='G1307')

        def read_with(order_text, target):
            driver = Mock()
            driver.execute_script.return_value = {
                'url': 'https://kyfw.12306.cn/otn/view/train_order.html', 'dialogs': [], 'details': [],
                'orders': [{**record, 'text': order_text}]}
            return OrderPage(driver).result(target)

        self.assertEqual(read_with(record['text'], selected).status, 'pending_payment')
        for changed in (replace(selected, train_code='G130'), replace(selected, from_station='北京'),
                        replace(selected, to_station='成都'), replace(selected, seat='一等座')):
            self.assertEqual(read_with(record['text'], changed).status, 'unknown')

    def test_numeric_train_code_cannot_match_a_fare(self):
        selected = replace(intent(), train_code="1461")
        wrong_train = snapshot()
        wrong_train["orders"][0]["text"] = "1462次 2026-09-10 北京 上海 二等座 张三 ¥1461.0元"
        self.assertEqual(self.read(wrong_train, selected).status, "unknown")

        matching_train = snapshot()
        matching_train["orders"][0]["text"] = "1461次 2026-09-10 北京 上海 二等座 张三 ¥88.0元"
        self.assertEqual(self.read(matching_train, selected).status, "pending_payment")

        structured = snapshot()
        structured["orders"][0].update({
            "train_code": "1462",
            "text": "2026-09-10 北京 上海 二等座 张三 ¥1461.0元",
        })
        self.assertEqual(self.read(structured, selected).status, "unknown")

    def read(self, value, selected=None, **kwargs):
        driver = Mock()
        driver.execute_script.return_value = value
        return OrderPage(driver).result(selected or intent(), **kwargs)

    def test_matching_order_required_for_success(self):
        for status, expected in [("待支付", "pending_payment"), ("已支付", "fulfilled"),
                                 ("已取消", "cancelled"), ("支付超时", "expired")]:
            with self.subTest(status=status):
                self.assertEqual(self.read(snapshot(status), known_id="E123456").status, expected)
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
            self.assertEqual(self.read(value, intent("alternate"), known_id="E123456").status, expected)

    def test_multi_combination_reverse_route_and_order_kind_rejected(self):
        for change in [{"text": "G101 G102 2026-09-10 北京 上海 二等座 张三"},
                       {"text": "G101 2026-09-10 北京 上海 二等座 一等座 张三"},
                       {"text": "G101 2026-09-10 2026-09-11 北京 上海 二等座 张三"},
                       {"text": "G101 2026-09-10 上海 北京 二等座 张三"}, {"kind": "alternate"}]:
            value = snapshot()
            value["orders"][0].update(change)
            self.assertEqual(self.read(value).status, "unknown")

    def test_structured_and_textual_train_evidence_must_agree(self):
        for fields in [
            {"train_code": "G101", "text": "G101次 G102次"},
            {"train_codes": ["G101", "G102"], "text": "G101"},
            {"train_codes": ["G102"], "text": "G101次"},
            {"train_code": "G101", "text": "G101次 G102"},
            {"train_code": "G101", "text": "G101 1461次"},
        ]:
            with self.subTest(fields=fields):
                value = snapshot()
                value["orders"][0].update(fields)
                value["orders"][0]["text"] += " 2026-09-10 北京 上海 二等座 张三"
                self.assertEqual(self.read(value).status, "unknown")

    def test_numeric_structured_train_evidence_ignores_fares_but_not_conflicting_trains(self):
        selected = replace(intent(), train_code="1461")
        for codes, text, expected in [
            (["1461"], "1461 ¥1462.0元", "pending_payment"),
            (["1461", "1461"], "1461 ¥1462.0元", "pending_payment"),
            ([], "¥1461.0元", "unknown"),
            (["1461", "1462"], "1461", "unknown"),
            (["1461"], "1461 G102", "unknown"),
        ]:
            with self.subTest(codes=codes, text=text):
                value = snapshot()
                value["orders"][0].update(train_codes=codes, text=text + " 2026-09-10 北京 上海 二等座 张三")
                self.assertEqual(self.read(value, selected).status, expected)

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
        self.assertFalse(self.read(data).no_order)
        self.assertEqual(self.read(data, known_id="E123456").status, "unknown")
        self.assertEqual(self.read(data, submitted=True).status, "unknown")
        self.assertFalse(self.read(data, submitted=True, allow_empty=True).no_order)

    def test_deadline_requires_date_and_exact_time(self):
        self.assertTrue(OrderPage.deadline_matches("2026年9月10日 18:00", "18:00", "2026-09-10"))
        self.assertFalse(OrderPage.deadline_matches("2026年9月9日 18:00", "18:00", "2026-09-10"))
        self.assertFalse(OrderPage.deadline_matches("开车前20分钟", "18:00", "2026-09-10"))
        self.assertTrue(OrderPage.deadline_matches("开车前1小时", "开车前60分钟", "2026-09-10"))
        self.assertFalse(OrderPage.deadline_matches("开车前20分钟", "开车前60分钟", "2026-09-10"))
        self.assertTrue(OrderPage.deadline_matches("开车前1天", "开车前24小时", "2026-09-10"))
        self.assertTrue(OrderPage.deadline_matches("开车前1440分钟", "开车前1天", "2026-09-10"))
        self.assertFalse(OrderPage.deadline_matches("开车前12小时", "开车前1天", "2026-09-10"))


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
        self.addCleanup(self.journal.release_resume, "resume", original.intent_id)
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

    def test_query_telemetry_is_batched_and_bounded_without_pruning_order_evidence(self):
        journal = OrderJournal(self.path, telemetry_batch_size=3, telemetry_limit=4)
        journal.record_telemetry("run", "query_click")
        journal.record_telemetry("run", "query_result")
        with journal.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_events").fetchone()[0], 0)
        for index in range(5):
            journal.record_telemetry("run", "query_click", detail={"index": index})
        journal.flush_telemetry()
        journal.mark("run", "verification")
        with journal.connection() as db:
            telemetry = db.execute(
                "SELECT COUNT(*) FROM order_events WHERE stage IN ('query_click','query_result')"
            ).fetchone()[0]
            evidence = db.execute(
                "SELECT COUNT(*) FROM order_events WHERE stage='verification'"
            ).fetchone()[0]
        self.assertEqual(telemetry, 4)
        self.assertEqual(evidence, 1)

    def test_telemetry_write_failure_does_not_interrupt_the_query_path(self):
        journal = OrderJournal(self.path, telemetry_batch_size=1)
        with patch.object(journal, "flush_telemetry", side_effect=sqlite3.OperationalError("busy")):
            self.assertFalse(journal.record_telemetry("run", "query_click"))
            journal.mark("run", "verification")
        with journal.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM order_events WHERE stage='verification'").fetchone()[0], 1)

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

    def test_order_uses_selected_row_stations_and_preserves_query_config(self):
        self.monitor.row_parser.selected_route = Mock(return_value=('北京丰台', '上海虹桥'))
        self.monitor.submit_flow.try_auto_submit = Mock(return_value=OrderResult('unknown'))
        self.monitor._execute_order(self.hit)
        pending = self.journal.pending()
        self.assertEqual((pending['intent']['from_station'], pending['intent']['to_station']), ('北京丰台', '上海虹桥'))
        self.assertEqual(pending['config']['from_station_cn'], '北京')
        self.assertEqual(self.monitor.submit_flow.try_auto_submit.call_args.kwargs['intent'].to_station, '上海虹桥')

    def test_post_submit_sold_out_cannot_navigate_or_enable_fallback(self):
        self.monitor.submit_flow.try_auto_submit = Mock(
            return_value=OrderResult("unknown", "官方提示余票不足"))
        self.monitor.order_page.reconcile = Mock(return_value=OrderResult("unknown"))
        self.assertTrue(self.monitor._execute_order(self.hit))
        self.assertIs(self.monitor.order_page.reconcile.call_args.kwargs["navigate"], False)
        self.assertFalse(self.monitor._prefer_alternate)
        self.assertIsNotNone(self.journal.pending())

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
        self.monitor.row_parser.snapshot_rows = lambda seats: [
            {"train":row.text.split()[0], "element":row, "seats":{"二等座":self.monitor._get_seat_value(row)}} for row in rows]
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
    def test_legacy_preparation_settings_and_http_offset_do_not_advance_query_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = RailWatchBridge(tmp)
            try:
                bridge.server_time_sync = Mock()
                bridge.server_time_sync.offset_seconds = 5
                bridge.server_time_sync.server_timestamp.return_value = 1000
                bridge._wait_for_target_timestamp = Mock(return_value=True)
                for prepare in (0, 2, 30):
                    config = {"_target_timestamp": 1000, "prepare_time": prepare, "prewarm_lead_seconds": 120}
                    self.assertTrue(bridge._wait_for_target_time(config))
                    bridge._wait_for_target_timestamp.assert_called_with(1000, config)
                bridge.server_time_sync.sync.assert_not_called()
            finally:
                bridge.notification_service.close()

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


class OrderResultWaitingTests(unittest.TestCase):
    def setUp(self):
        self.elapsed = 0.0
        self.logs = []
        self.page = OrderPage(Mock(), wait=self.advance, log=self.logs.append)
        clock = patch("railwatch_order_page.time.monotonic", lambda: self.elapsed)
        clock.start()
        self.addCleanup(clock.stop)

    def advance(self, seconds):
        self.elapsed += seconds

    def test_slow_payment_page_without_recognized_progress_gets_sixty_seconds(self):
        self.page.snapshot = lambda: snapshot() if self.elapsed >= 45 else snapshot(orders=[])
        self.page.reconcile = Mock()
        result = self.page._post_submit(intent(), True)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.elapsed, 45)
        self.page.reconcile.assert_not_called()

    def test_official_queue_outlives_timeout_then_payment_page_gets_fresh_grace(self):
        def read():
            if self.elapsed < 120:
                return snapshot(orders=[], processing=True, confirmation=True)
            return snapshot() if self.elapsed >= 150 else snapshot(orders=[])
        self.page.snapshot = read
        self.page.reconcile = Mock()
        result = self.page._post_submit(intent(), True)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.elapsed, 150)
        self.assertEqual(len(self.logs), 4)
        self.page.reconcile.assert_not_called()

    def test_alternate_submission_waits_for_delayed_order_without_repeating_clicks(self):
        selected = intent("alternate")
        submitted = [False]
        def read():
            if not submitted[0]:
                return snapshot(orders=[], details=[{}])
            if self.elapsed < 90:
                return snapshot(orders=[], processing=True)
            value = snapshot()
            value["orders"][0]["kind"] = "alternate"
            return value
        self.page.snapshot = read
        self.page.prepare_people = Mock(return_value=True)
        self.page.set_deadline = Mock(return_value=True)
        self.page.verify_form = Mock(return_value=True)
        submit, candidate = Mock(), Mock()
        submit.click.side_effect = lambda: submitted.__setitem__(0, True)
        self.page.button = Mock(return_value=submit)
        result = self.page.alternate(candidate, selected)
        self.assertEqual((result.status, result.order_id), ("pending_payment", "E123456"))
        self.assertEqual(self.elapsed, 90)
        candidate.click.assert_called_once()
        submit.click.assert_called_once()
        self.page.driver.get.assert_not_called()

    def test_unrecognized_page_times_out_without_authorizing_fallback(self):
        for kind in ("regular", "alternate"):
            with self.subTest(kind=kind):
                self.elapsed = 0
                self.page.snapshot = lambda: snapshot(orders=[])
                result = self.page.wait_result(intent(kind))
                self.assertEqual(self.elapsed, 60)
                self.assertEqual(result.status, "unknown")
                self.assertFalse(result.can_fallback)
                self.assertFalse(result.no_order)
                self.page.driver.get.assert_not_called()

    def test_disappeared_queue_does_not_wait_forever_on_an_unrecognized_page(self):
        self.page.snapshot = lambda: snapshot(orders=[], processing=self.elapsed < 30)
        result = self.page.wait_result(intent())
        self.assertEqual(result.status, "unknown")
        self.assertGreaterEqual(self.elapsed, 89)
        self.assertLessEqual(self.elapsed, 90)

    def test_stop_during_official_queue_preserves_page_and_order(self):
        self.page.snapshot = lambda: snapshot(orders=[], processing=True, confirmation=True)
        self.page.stop = lambda: self.elapsed >= 2
        self.page.reconcile = Mock()
        result = self.page._post_submit(intent(), True)
        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.can_fallback)
        self.assertEqual(self.elapsed, 2)
        self.page.reconcile.assert_not_called()

    def test_verification_interrupts_queue_wait_immediately(self):
        self.page.snapshot = lambda: snapshot(orders=[], processing=True,
                                             verification=self.elapsed >= 3)
        result = self.page.wait_result(intent())
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.elapsed, 3)

    def test_queue_does_not_hide_matched_terminal_order(self):
        for state, expected in (("待支付", "pending_payment"), ("支付超时", "expired"),
                                ("已取消", "cancelled")):
            with self.subTest(state=state):
                self.page.snapshot = lambda: snapshot(state, processing=True)
                result = self.page.wait_result(intent(), known_id="E123456")
                self.assertEqual(result.status, expected)
                self.assertEqual(self.elapsed, 0)


class RegularConfirmationTests(unittest.TestCase):
    """提交后正常确认；停止不再点击，未知保留核对，页面不乱跳。"""

    def _page(self):
        from railwatch_order_page import OrderPage
        page = OrderPage(Mock())
        page.snapshot = lambda: {"formReady": True}
        page.result = lambda *a, **k: OrderResult("unknown")
        page.prepare_people = lambda names: True
        page.select_regular_seats = lambda target: True
        page.verify_form = lambda target: True
        page.wait_result = lambda target, submitted=True, timeout=10: OrderResult(
            "unknown", "未获得匹配的订单证据，请打开官方订单详情核对")
        return page

    def test_timing_preserves_slow_page_and_passenger_costs_without_extra_writes(self):
        page = self._page()
        elapsed = [0.0]
        events = []
        page.mark = lambda stage, detail=None: events.append((stage, detail))
        def delay(seconds):
            elapsed[0] += seconds
            self.assertFalse(any(stage == "order_timing" for stage, _ in events))
            return True
        book, submit, confirm = Mock(), Mock(), Mock()
        book.click.side_effect = lambda: delay(6)
        page.prepare_people = lambda target: delay(.5)
        page.select_regular_seats = lambda target: delay(.25)
        page.verify_form = lambda target: delay(.1)
        page.button = lambda selectors: submit if selectors == ("#submitOrder_id",) else confirm
        page.wait_result = lambda *a, **k: OrderResult("pending_payment", order_id="E123456")
        with patch("railwatch_order_page.time.monotonic", lambda: elapsed[0]):
            result = page.regular(book, intent())
        self.assertEqual(result.status, "pending_payment")
        saved = [detail for stage, detail in events if stage == "order_timing"]
        self.assertEqual(len(saved), 1)
        steps = {step["id"]: step["duration_ms"] for step in saved[0]["steps"]}
        self.assertEqual((steps["page_load"], steps["passengers"], steps["seats"], steps["readback"]),
                         (6000, 500, 250, 100))
        submit.click.assert_called_once()
        confirm.click.assert_called_once()

    def test_timing_write_failure_does_not_change_result_and_failed_readback_is_recorded(self):
        page = self._page()
        page.prepare_people = lambda target: False
        events = []
        page.mark = lambda stage, detail=None: events.append((stage, detail))
        result = page.regular(Mock(), intent())
        self.assertEqual(result.status, "verification")
        self.assertEqual([s["id"] for s in events[0][1]["steps"]], ["page_load", "passengers"])
        page.mark = Mock(side_effect=OSError("disk full"))
        self.assertEqual(page.regular(Mock(), intent()).status, "verification")

    def test_confirmation_clicks_directly_even_when_modal_readback_differs(self):
        # 弹窗打开时回读会把乘客在背景页和弹窗表格各读一遍，核对必然失败；
        # 自动化模式下必须跳过二次核对直接确认。
        page = self._page()
        state = {"dialog": False}
        page.verify_form = lambda target: not state["dialog"]
        page.wait_result = lambda target, submitted=True, timeout=10: OrderResult(
            "pending_payment", order_id="E123456", evidence={"matched": True})
        confirm = Mock()
        def button(selectors):
            if selectors == ("#qr_submit_id",):
                state["dialog"] = True
                return confirm
            submit = Mock()
            submit.click.side_effect = lambda: state.update(dialog=True)
            return submit
        page.button = button
        result = page.regular(Mock(), intent())
        confirm.click.assert_called_once()
        self.assertEqual((result.status, result.order_id), ("pending_payment", "E123456"))

    def test_delayed_dialog_after_ten_seconds_is_still_confirmed_automatically(self):
        page = self._page()
        elapsed = [0.0]
        page.wait = lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
        submit, confirm = Mock(), Mock()
        page.button = lambda selectors: (submit if selectors == ("#submitOrder_id",)
                                         else confirm if elapsed[0] >= 12 else None)
        page.wait_result = Mock(return_value=OrderResult("pending_payment", order_id="E123456"))
        with patch("railwatch_order_page.time.monotonic", lambda: elapsed[0]):
            result = page.regular(Mock(), intent())
        self.assertEqual(result.status, "pending_payment")
        submit.click.assert_called_once()
        confirm.click.assert_called_once()
        self.assertGreaterEqual(elapsed[0], 12)

    def test_rejected_confirmation_click_reacquires_button_and_submits(self):
        from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
        for error in (ElementClickInterceptedException, StaleElementReferenceException):
            with self.subTest(error=error.__name__):
                page = self._page()
                submit, blocked, refreshed = Mock(), Mock(), Mock()
                blocked.click.side_effect = error("not dispatched")
                buttons = iter([blocked, refreshed])
                page.button = lambda selectors: (submit if selectors == ("#submitOrder_id",)
                                                 else next(buttons))
                page.wait_result = Mock(return_value=OrderResult("pending_payment", order_id="E123456"))
                result = page.regular(Mock(), intent())
                self.assertEqual(result.status, "pending_payment")
                submit.click.assert_called_once()
                blocked.click.assert_called_once()
                refreshed.click.assert_called_once()

    def test_verification_during_confirmation_retry_stops_clicking(self):
        from selenium.common.exceptions import ElementClickInterceptedException
        page = self._page()
        submit, confirm = Mock(), Mock()
        def blocked():
            page.result = lambda *a, **k: OrderResult("verification", "请完成人脸核验")
            raise ElementClickInterceptedException("verification overlay")
        confirm.click.side_effect = blocked
        page.button = lambda selectors: submit if selectors == ("#submitOrder_id",) else confirm
        result = page.regular(Mock(), intent())
        self.assertEqual(result.status, "verification")
        confirm.click.assert_called_once()

    def test_confirmation_is_not_clicked_when_stop_is_requested(self):
        page = self._page()
        state = {"stopped": False}
        page.stop = lambda: state["stopped"]
        confirm = Mock()
        def button(selectors):
            if selectors == ("#qr_submit_id",):
                return confirm
            submit = Mock()
            submit.click.side_effect = lambda: state.update(stopped=True)
            return submit
        page.button = button
        # Even if a dialog is available, stop must prevent any confirmation.
        poll_results = iter([True, True, None])
        page.poll = lambda predicate, timeout=10: next(poll_results, None)
        logs = []
        page.log = logs.append
        result = page.regular(Mock(), intent())
        confirm.click.assert_not_called()
        self.assertIn("已停止后续操作", result.reason)
        self.assertEqual(result.status, "unknown")

    def test_unknown_after_confirmation_reconciles_official_order_page(self):
        page = self._page()
        page.driver.execute_script.return_value = True  # DOM receipt, not a transport acknowledgement.
        page.button = lambda selectors: Mock()
        page.snapshot = lambda: {"formReady": True}
        page.reconcile = Mock(return_value=OrderResult("pending_payment", order_id="E123456",
                                                       evidence={"matched": True}))
        result = page.regular(Mock(), intent())
        self.assertEqual((result.status, result.order_id), ("pending_payment", "E123456"))
        page.reconcile.assert_called_once()

    def test_active_official_queue_does_not_navigate_away_on_wait_timeout(self):
        page = self._page()
        page.snapshot = lambda: {"processing": True}
        page.reconcile = Mock()
        result = page._post_submit(intent(), True)
        self.assertEqual(result.status, "unknown")
        page.reconcile.assert_not_called()

    def test_pending_dialog_reports_actionable_verification_without_navigation(self):
        page = self._page()
        page.button = lambda selectors: Mock()
        page.snapshot = lambda: {"formReady": True, "confirmation": True}
        page.reconcile = Mock()
        result = page.regular(Mock(), intent())
        self.assertEqual(result.status, "verification")
        self.assertIn("确认", result.reason)
        self.assertIn("继续处理", result.reason)
        page.reconcile.assert_not_called()

    def test_missing_dialog_keeps_page_and_never_reconciles(self):
        page = self._page()
        page.button = lambda selectors: Mock() if selectors == ("#submitOrder_id",) else None
        page.reconcile = Mock()
        # ready 与回读轮询需返回真值，确认弹窗轮询返回空。
        poll_results = iter([True, True, None])
        page.poll = lambda predicate, timeout=10, ignore_stop=False: next(poll_results, None)
        result = page.regular(Mock(), intent())
        self.assertEqual(result.status, "unknown")
        page.reconcile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
