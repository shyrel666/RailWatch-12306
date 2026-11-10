"""Headless Chrome smoke tests for official 12306 pre-fill fixtures; zero live network."""
import datetime as dt
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from railwatch_bridge import CHROMEDRIVER_PATH, RailWatchBridge
from railwatch_order_page import OrderPage
from railwatch_orders import OrderJournal
from railwatch_prefill import (
    BEIJING_TZ,
    CONFIRMATION_SNAPSHOT_JS,
    DISMISS_PREFILL_ALERT_JS,
    PrefillAdapter,
    PrefillFallback,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SALE_1600 = dt.datetime(2026, 11, 7, 16, 0, 0, tzinfo=BEIJING_TZ).timestamp()
NOW_1550 = SALE_1600 - 600.0


class PrefillBrowserSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = tempfile.TemporaryDirectory(prefix="railwatch-prefill-browser-")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument(f"--user-data-dir={cls.profile.name}")
        cls.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
        cls.driver.execute_cdp_cmd("Network.enable", {})
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*", "http://*"]})
        # Emulate Beijing timezone in Chrome so Date.prototype.getTimezoneOffset() === -480.
        cls.driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile.cleanup()

    def setUp(self):
        self.driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = OrderJournal(Path(self.temp.name) / "orders.sqlite3")
        self.config = {
            "from_station_cn": "北京南",
            "to_station_cn": "天津",
            "date": "2026-11-21",
            "train_code": "G8863,G8821,K7731,C2551",
            "seat_keyword": "二等座,一等座,硬卧,商务座",
            "passengers": "张三,赵六",
            "timer_enabled": True,
            "auto_submit": True,
            "auto_alternate": True,
            "sale_at": "2026-11-07T16:00:00+08:00",
        }

    def adapter(self, *, now=NOW_1550, query_init_url=None, prefill_order_url=None, log=None):
        return PrefillAdapter(
            self.driver,
            now=lambda: now,
            log=log,
            allow_fixture=True,
            query_init_url=query_init_url or (FIXTURES / "prefill-banners.html").resolve().as_uri(),
            prefill_order_url=prefill_order_url or (FIXTURES / "prefill-order.html").resolve().as_uri(),
        )

    def arm_single_or_pair(self, *, train_code="G8821", seat_keyword="二等座", passengers="张三"):
        self.driver.get((FIXTURES / "prefill-banners.html").resolve().as_uri())
        cfg = {
            **self.config,
            "train_code": train_code,
            "seat_keyword": seat_keyword,
            "passengers": passengers,
        }
        adapter = self.adapter()
        plan = adapter.prepare(cfg, SALE_1600, check_existing=False)
        adapter.prefill_order_url = self.driver.current_url
        return adapter, plan, cfg

    def fixture_clicks(self):
        return self.driver.execute_script("return window.fixture ? window.fixture.clicks : [];")

    def fixture_confirm_clicks(self):
        return self.driver.execute_script("return window.fixture ? window.fixture.confirmClicks : 0;")

    def fixture_form_submit_clicks(self):
        return self.driver.execute_script("return window.fixture ? window.fixture.formSubmitClicks : 0;")

    def test_end_to_end_prepare_selects_1600_trains_expands_icheck_and_verifies_tabs(self):
        self.driver.get((FIXTURES / "prefill-banners.html").resolve().as_uri())
        adapter = self.adapter()
        plan = adapter.prepare(self.config, SALE_1600, check_existing=False)

        # K7731 (08:00 + sleeper berths), C2551 (12:45), and 商务座 (regular=False) must be excluded.
        # Priority follows config: G8863 (二等座, 一等座) then G8821 (二等座, 一等座).
        self.assertEqual(
            [(c.train_code, c.from_station, c.to_station, c.seat) for c in plan.candidates],
            [
                ("G8863", "北京大兴", "天津西", "二等座"),
                ("G8863", "北京大兴", "天津西", "一等座"),
                ("G8821", "大兴机场", "天津西", "二等座"),
                ("G8821", "大兴机场", "天津西", "一等座"),
            ],
        )
        # First candidate's station tab (北京大兴 -> 天津西) must be armed active.
        active_from = self.driver.execute_script(
            "return document.querySelector('.lines-item.is-active strong.lines-name')?.textContent.trim();"
        )
        self.assertEqual(active_from, "北京大兴")

    def test_non_beijing_timezone_in_browser_triggers_clean_fallback(self):
        self.driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": "America/Chicago"})
        self.driver.get((FIXTURES / "prefill-banners.html").resolve().as_uri())
        with self.assertRaises(PrefillFallback) as ctx:
            self.adapter().prepare(self.config, SALE_1600, check_existing=False)
        self.assertEqual(ctx.exception.stage, "timezone_mismatch")

    def test_existing_prefill_account_conflict_is_protected(self):
        conflict_url = (FIXTURES / "prefill-order.html").resolve().as_uri() + "?passengers=" + "%E6%9D%8E%E5%9B%9B"
        adapter = self.adapter(prefill_order_url=conflict_url)
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.prepare(self.config, SALE_1600, check_existing=True)
        self.assertEqual(ctx.exception.stage, "account_conflict")

    def test_existing_matching_prefill_is_reused_after_adult_verification(self):
        reuse_cfg = {
            **self.config,
            "train_code": "G8863,G8821",
            "seat_keyword": "二等座",
            "passengers": "张三",
        }
        selected = "G8821|大兴机场|天津西|二等座;G8863|北京大兴|天津西|二等座"
        saved_url = (
            (FIXTURES / "prefill-order.html").resolve().as_uri()
            + f"?date=2026-11-21&selected={quote(selected)}&passengers=%E5%BC%A0%E4%B8%89"
        )
        logs = []
        adapter = self.adapter(
            query_init_url=(FIXTURES / "prefill-banners.html").resolve().as_uri(),
            prefill_order_url=saved_url,
            log=logs.append,
        )
        plan = adapter.prepare(reuse_cfg, SALE_1600, check_existing=True)
        self.assertEqual(
            [(c.train_code, c.from_station, c.to_station, c.seat) for c in plan.candidates],
            [("G8863", "北京大兴", "天津西", "二等座"), ("G8821", "大兴机场", "天津西", "二等座")],
        )
        self.assertTrue(any("已复用账号既有官方预填单" in msg for msg in logs))
        active_from = self.driver.execute_script(
            "return document.querySelector('.lines-item.is-active strong.lines-name')?.textContent.trim();"
        )
        self.assertEqual(active_from, "北京大兴")
        self.assertEqual(self.fixture_clicks(), [])
        self.assertIsNone(self.journal.pending())
        self.assertEqual(self.journal.run_events("reuse-same-city"), [])

    def test_saved_prefill_with_mismatched_actual_route_falls_through_to_entry(self):
        cfg = {
            **self.config,
            "train_code": "G8821",
            "seat_keyword": "二等座",
            "passengers": "张三",
        }
        # Saved G8821 is 大兴机场 -> 南京南, while this query's actual row is 大兴机场 -> 天津西.
        saved_other_route_url = (
            (FIXTURES / "prefill-order.html").resolve().as_uri()
            + f"?date=2026-11-21&selected={quote('G8821|大兴机场|南京南|二等座')}&passengers=%E5%BC%A0%E4%B8%89"
        )
        banners_actual_url = (
            (FIXTURES / "prefill-banners.html").resolve().as_uri()
            + f"?rows={quote('G8821|大兴机场|天津西')}"
        )
        logs = []
        adapter = self.adapter(
            query_init_url=banners_actual_url,
            prefill_order_url=saved_other_route_url,
            log=logs.append,
        )
        plan = adapter.prepare(cfg, SALE_1600, check_existing=True)
        self.assertFalse(any("已复用账号既有官方预填单" in msg for msg in logs))
        self.assertTrue(any("官方购票信息预填已完成核对" in msg for msg in logs))
        self.assertEqual(
            [(c.train_code, c.from_station, c.to_station, c.seat) for c in plan.candidates],
            [("G8821", "大兴机场", "天津西", "二等座")],
        )
        self.assertEqual(self.fixture_clicks(), [])
        self.assertIsNone(self.journal.pending())
        self.assertEqual(self.journal.run_events("route-mismatch"), [])

        # Also verify query-string row override (?rows=G8821|大兴机场|南京南) blocks reusing saved 大兴机场->天津西.
        saved_tianjin_url = (
            (FIXTURES / "prefill-order.html").resolve().as_uri()
            + f"?date=2026-11-21&selected={quote('G8821|大兴机场|天津西|二等座')}&passengers=%E5%BC%A0%E4%B8%89"
        )
        banners_nanjing_url = (
            (FIXTURES / "prefill-banners.html").resolve().as_uri()
            + f"?rows={quote('G8821|大兴机场|南京南')}"
        )
        logs_override = []
        adapter_override = self.adapter(
            query_init_url=banners_nanjing_url,
            prefill_order_url=saved_tianjin_url,
            log=logs_override.append,
        )
        adapter_override.prepare(cfg, SALE_1600, check_existing=True)
        self.assertFalse(any("已复用账号既有官方预填单" in msg for msg in logs_override))
        self.assertTrue(any("官方购票信息预填已完成核对" in msg for msg in logs_override))
        self.assertEqual(self.fixture_clicks(), [])
        self.assertIsNone(self.journal.pending())

    def test_student_passenger_rejected_during_prepare(self):
        self.driver.get((FIXTURES / "prefill-banners.html").resolve().as_uri())
        student_cfg = {**self.config, "passengers": "王小明"}
        with self.assertRaises(PrefillFallback) as ctx:
            self.adapter().prepare(student_cfg, SALE_1600, check_existing=False)
        self.assertIn(ctx.exception.stage, ("passenger_select", "editor_readback"))

    def test_armed_execution_handles_timeout_sold_out_cascade_and_confirm_form(self):
        self.driver.get((FIXTURES / "prefill-banners.html").resolve().as_uri())
        single_person_cfg = {**self.config, "passengers": "张三"}
        adapter = self.adapter()
        plan = adapter.prepare(single_person_cfg, SALE_1600, check_existing=False)
        order_uri = self.driver.current_url
        adapter.prefill_order_url = order_uri

        # 0. The page still counts ten minutes down: fall back at once instead of waiting to unlock.
        started = time.monotonic()
        behind_outcome = adapter.execute_armed(plan, self.journal, "smoke-behind", single_person_cfg)
        self.assertEqual(behind_outcome.action, "fallback_to_query")
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(self.journal.run_events("smoke-behind")[-1]["detail"]["stage"], "countdown_behind")
        self.assertEqual(self.fixture_clicks(), [])
        self.assertIsNone(self.journal.pending())

        # As on the live page, the countdown is empty in the last moments before unlocking.
        self.driver.execute_script("window.fixture.setCountdownText('');")

        # 1. While buttons remain display:none, unlock timeout leaves zero unresolved order.
        with mock.patch.dict("railwatch_prefill.ORDER_POLICIES", {"prefill_unlock_timeout_ms": 200}):
            timeout_outcome = adapter.execute_armed(plan, self.journal, "smoke-timeout", single_person_cfg)
        self.assertEqual(timeout_outcome.action, "fallback_to_query")
        self.assertEqual(self.journal.run_events("smoke-timeout")[-1]["detail"]["stage"], "unlock_timeout")
        self.assertIsNone(self.journal.pending())

        # 2. Simulate G8863 (both seats) sold out, then cross-tab switch to G8821 二等座 -> confirm form -> E888888!
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8863', '二等座', 'sold_out');
            window.fixture.setOutcome('G8863', '一等座', 'sold_out');
            window.fixture.setOutcome('G8821', '二等座', 'confirm_form');
            setTimeout(() => window.fixture.unlock(), 2200);
            """
        )
        # The button appears later than the former 1.5 s limit and is still bought through the pre-fill.
        outcome = adapter.execute_armed(plan, self.journal, "smoke-buy", single_person_cfg)
        self.assertEqual(outcome.action, "handled")
        entry = next(e for e in self.journal.run_events("smoke-buy") if e["stage"] == "prefill_submit")
        self.assertGreater(entry["detail"]["unlock_wait_ms"], 1500)
        self.assertEqual([(c.train_code, c.seat) for c in outcome.sold_out_candidates], [("G8863", "二等座"), ("G8863", "一等座")])
        self.assertEqual((outcome.last_intent.train_code, outcome.last_intent.seat), ("G8821", "二等座"))
        self.assertEqual((outcome.last_result.status, outcome.last_result.order_id), ("pending_payment", "E888888"))
        self.assertEqual(self.journal.pending()["result"]["order_id"], "E888888")

    def test_preclick_recheck_passengers_changed_falls_back_with_zero_clicks(self):
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8821", seat_keyword="二等座", passengers="张三")
        self.driver.execute_script(
            """
            window.fixture.unlock();
            window.fixture.setPassengers('李四');
            """
        )
        outcome = adapter.execute_armed(plan, self.journal, "recheck-passengers", cfg)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertEqual(outcome.sold_out_candidates, ())
        self.assertIsNone(outcome.last_intent)
        self.assertIsNone(outcome.last_result)
        self.assertEqual(self.fixture_clicks(), [])
        self.assertEqual(self.fixture_confirm_clicks(), 0)
        self.assertIsNone(self.journal.pending())
        events = self.journal.run_events("recheck-passengers")
        self.assertEqual([e["stage"] for e in events], ["prefill_fallback"])
        self.assertEqual(events[0]["detail"], {"stage": "passengers_changed", "train": "G8821", "seat": "二等座"})

    def test_preclick_recheck_residual_dialog_open_falls_back_with_zero_clicks(self):
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8821", seat_keyword="二等座", passengers="张三")
        self.driver.execute_script(
            """
            window.fixture.unlock();
            window.fixture.showDialog('请先处理残留提示');
            """
        )
        outcome = adapter.execute_armed(plan, self.journal, "recheck-dialog", cfg)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertEqual(outcome.sold_out_candidates, ())
        self.assertIsNone(outcome.last_intent)
        self.assertIsNone(outcome.last_result)
        self.assertEqual(self.fixture_clicks(), [])
        self.assertEqual(self.fixture_confirm_clicks(), 0)
        self.assertIsNone(self.journal.pending())
        events = self.journal.run_events("recheck-dialog")
        self.assertEqual([e["stage"] for e in events], ["prefill_fallback"])
        self.assertEqual(events[0]["detail"], {"stage": "dialog_open", "train": "G8821", "seat": "二等座"})

    def test_no_response_keeps_unknown_lock_and_blocks_resume(self):
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8863,G8821", seat_keyword="二等座", passengers="张三")
        adapter.TRANSITION_TIMEOUT_SECONDS = 0.25
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8863', '二等座', 'no_response');
            window.fixture.unlock();
            """
        )
        outcome = adapter.execute_armed(plan, self.journal, "no-response", cfg)
        self.assertEqual(outcome.action, "handled")
        self.assertEqual(outcome.sold_out_candidates, ())
        self.assertEqual(outcome.last_result.status, "unknown")
        self.assertFalse(outcome.last_result.no_order)
        self.assertEqual(self.fixture_clicks(), ["G8863|二等座"])
        self.assertEqual(self.fixture_confirm_clicks(), 0)

        pending = self.journal.pending()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["result"]["status"], "unknown")
        self.assertEqual(pending["intent"]["intent_id"], outcome.last_intent.intent_id)
        self.assertTrue(self.journal.submission_started(outcome.last_intent.intent_id))
        self.assertFalse(self.journal.claim_resume("resume-probe", outcome.last_intent.intent_id))

        events = self.journal.run_events("no-response")
        self.assertEqual(
            [e["stage"] for e in events],
            ["submitting", "inventory_found", "prefill_submit", "order_result", "unknown"],
        )

    def test_sold_out_with_verification_stops_cascade_preserves_dialog_and_locks(self):
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8863,G8821", seat_keyword="二等座", passengers="张三")
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8863', '二等座', 'sold_out_verify');
            window.fixture.unlock();
            """
        )
        outcome = adapter.execute_armed(plan, self.journal, "sold-out-verify", cfg)
        self.assertEqual(outcome.action, "handled")
        self.assertEqual(outcome.sold_out_candidates, ())
        self.assertEqual(outcome.last_result.status, "verification")
        self.assertFalse(outcome.last_result.no_order)
        self.assertEqual(self.fixture_clicks(), ["G8863|二等座"])
        self.assertEqual(self.fixture_confirm_clicks(), 0)

        detail_snap = adapter._detail_snapshot()
        self.assertEqual(len(detail_snap["dialogs"]), 1)
        self.assertIn("票已售完，请完成核验", detail_snap["dialogs"][0])
        self.assertTrue(OrderPage(self.driver, allow_fixture=True).snapshot()["verification"])

        pending = self.journal.pending()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["result"]["status"], "verification")
        self.assertTrue(self.journal.submission_started(outcome.last_intent.intent_id))
        self.assertFalse(self.journal.claim_resume("resume-probe", outcome.last_intent.intent_id))

        events = self.journal.run_events("sold-out-verify")
        self.assertEqual(
            [e["stage"] for e in events],
            ["submitting", "inventory_found", "prefill_submit", "order_result", "verification"],
        )

    def test_direct_confirm_verifies_up_box_and_confirms_once_to_pending_payment(self):
        logs = []
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8821", seat_keyword="二等座", passengers="张三")
        adapter.log = logs.append
        dom_checks = []
        orig_matches = adapter._confirmation_matches

        def spy_matches(intent):
            dom_checks.append(
                {
                    "has_qr_submit_id": self.driver.execute_script("return !!document.getElementById('qr_submit_id');"),
                    "ok_btn_id": self.driver.execute_script(
                        "return document.querySelector('.modal a.btn.btn-primary.ok')?.id ?? null;"
                    ),
                    "dismiss_result": self.driver.execute_script(DISMISS_PREFILL_ALERT_JS),
                    "confirm_snap": self.driver.execute_script(CONFIRMATION_SNAPSHOT_JS),
                }
            )
            return orig_matches(intent)

        adapter._confirmation_matches = spy_matches
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8821', '二等座', 'direct_confirm');
            window.fixture.unlock();
            """
        )
        outcome = adapter.execute_armed(
            plan, self.journal, "direct-confirm", cfg, seat_preference="靠窗优先"
        )
        self.assertEqual(len(dom_checks), 1)
        self.assertFalse(dom_checks[0]["has_qr_submit_id"])
        self.assertEqual(dom_checks[0]["ok_btn_id"], "")
        self.assertFalse(dom_checks[0]["dismiss_result"])
        self.assertEqual(dom_checks[0]["confirm_snap"]["names"], ["张三"])
        self.assertEqual(dom_checks[0]["confirm_snap"]["seats"], ["二等座"])
        self.assertEqual(dom_checks[0]["confirm_snap"]["ticket_types"], ["成人票"])
        self.assertTrue(dom_checks[0]["confirm_snap"]["no_seat_preference"])
        self.assertTrue(any("暂不支持自选席位" in msg for msg in logs))

        self.assertEqual(outcome.action, "handled")
        self.assertEqual((outcome.last_result.status, outcome.last_result.order_id), ("pending_payment", "E888888"))
        self.assertEqual(self.fixture_clicks(), ["G8821|二等座"])
        self.assertEqual(self.fixture_confirm_clicks(), 1)
        self.assertEqual(self.fixture_form_submit_clicks(), 0)

        pending = self.journal.pending()
        self.assertIsNotNone(pending)
        self.assertEqual((pending["result"]["status"], pending["result"]["order_id"]), ("pending_payment", "E888888"))

        stages = [e["stage"] for e in self.journal.run_events("direct-confirm")]
        self.assertEqual(
            stages,
            [
                "submitting",
                "inventory_found",
                "prefill_submit",
                "regular_submit",
                "regular_confirm_attempt",
                "regular_confirm_dispatched",
                "order_result",
                "pending_payment",
            ],
        )

    def test_verification_manual_recovery_queue_then_payment_notifies_without_resubmitting(self):
        adapter, plan, cfg = self.arm_single_or_pair()
        original_matches = adapter._confirmation_matches

        def inject_timeout(intent):
            matched = original_matches(intent)
            self.driver.execute_script("""
                document.querySelector('.modal a.btn.btn-primary.ok').onclick = e => {
                    e.preventDefault();
                    fixture.confirmClicks++;
                    showDialog('请完成验证码');
                };
            """)
            return matched

        adapter._confirmation_matches = inject_timeout
        self.driver.execute_script("fixture.setOutcome('G8821','二等座','direct_confirm');fixture.unlock();")
        outcome = adapter.execute_armed(plan, self.journal, 'timeout-recovery', cfg)
        self.assertEqual(outcome.last_result.status, 'verification')
        self.assertEqual(self.fixture_confirm_clicks(), 1)
        self.assertEqual(self.fixture_clicks(), ['G8821|二等座'])
        self.assertIn('regular_confirm_dispatched', [e['stage'] for e in self.journal.run_events('timeout-recovery')])
        selected = outcome.last_intent
        self.assertFalse(self.journal.claim_resume('must-not-resubmit', selected.intent_id))

        # Stand in for train_order navigation with its actual visible queue
        # structure. The queue lasts longer than the configured unknown grace.
        page = OrderPage(self.driver, allow_fixture=True)
        page.RESULT_UNKNOWN_TIMEOUT = .3
        page.RESULT_POLL_INTERVAL = .05
        native_get = self.driver.get
        fixture_url = self.driver.current_url

        def open_order_list(url):
            self.assertEqual(url, 'https://kyfw.12306.cn/otn/view/train_order.html')
            native_get(fixture_url)
            self.driver.execute_script("""
                document.getElementById('prefill-wrapper').style.display='none';
                document.body.insertAdjacentHTML('beforeend',
                  '<div class="order-queue" id="paiduizhong"><div class="queue-state"><div class="queue-info"><h2>车票购买排队中…</h2></div></div><div class="queue-right"><a id="cencle_paidui_btn">取消排队</a></div></div>');
                window.orderActions=0;
                document.addEventListener('click',()=>window.orderActions++);
                setTimeout(()=>document.getElementById('paiduizhong').remove(),600);
                setTimeout(()=>showUnpaidOrder({code:'G8821',from:'大兴机场',to:'天津西'},'二等座'),750);
            """)

        with mock.patch.object(self.driver, 'get', side_effect=open_order_list) as navigation:
            result = page.reconcile(selected, navigate=True)
        navigation.assert_called_once()
        self.assertEqual((result.status, result.order_id), ('pending_payment', 'E888888'))
        self.assertEqual(self.driver.execute_script('return window.orderActions'), 0)
        result = self.journal.record(selected, result)
        self.assertEqual(self.journal.pending()['result']['order_id'], 'E888888')

        bridge = RailWatchBridge(self.temp.name)
        self.addCleanup(bridge.notification_service.close)
        bridge.emit = mock.Mock()
        bridge._notify_async = mock.Mock()
        bridge._handle_order(selected, result)
        self.assertEqual(bridge.state.order['status'], 'pending_payment')
        self.assertEqual(bridge.state.order['order_id'], 'E888888')
        self.assertEqual(bridge._notify_async.call_args.kwargs['event_type'], 'payment')
        self.assertTrue(any(call.args[0] == 'notify' and call.args[1]['priority'] == 'urgent'
                            for call in bridge.emit.call_args_list))

    def test_system_busy_automatically_recovers_queue_and_notifies_with_one_submission(self):
        self.assert_temporary_error_recovers('系统忙，请稍后再试！')

    def test_network_timeout_automatically_recovers_queue_and_notifies_with_one_submission(self):
        self.assert_temporary_error_recovers('网络超时，请重试')

    def assert_temporary_error_recovers(self, message):
        adapter, plan, cfg = self.arm_single_or_pair()
        original_matches = adapter._confirmation_matches
        native_get = self.driver.get
        fixture_url = self.driver.current_url
        clicks_before_navigation = []
        def inject_busy(intent):
            matched = original_matches(intent)
            self.driver.execute_script("""
                const message = arguments[0];
                document.querySelector('.modal a.btn.btn-primary.ok').onclick = e => {
                    e.preventDefault();fixture.confirmClicks++;
                    showDialog(message);
                };
            """, message)
            return matched
        adapter._confirmation_matches = inject_busy
        self.driver.execute_script("fixture.setOutcome('G8821','二等座','direct_confirm');fixture.unlock();")
        def open_order_list(url):
            self.assertEqual(url, 'https://kyfw.12306.cn/otn/view/train_order.html')
            clicks_before_navigation.append((self.fixture_clicks(), self.fixture_confirm_clicks()))
            native_get(fixture_url)
            self.driver.execute_script("""
                document.getElementById('prefill-wrapper').style.display='none';
                document.body.insertAdjacentHTML('beforeend','<div class="order-queue" id="paiduizhong">车票购买排队中…</div>');
                window.orderActions=0;
                document.addEventListener('click',()=>window.orderActions++);
                setTimeout(()=>document.getElementById('paiduizhong').remove(),600);
                setTimeout(()=>showUnpaidOrder({code:'G8821',from:'大兴机场',to:'天津西'},'二等座'),750);
            """)
        bridge = RailWatchBridge(self.temp.name)
        self.addCleanup(bridge.notification_service.close)
        bridge.emit = mock.Mock()
        bridge._notify_async = mock.Mock()
        with mock.patch.object(self.driver, 'get', side_effect=open_order_list) as navigation, \
                mock.patch.object(OrderPage, 'RESULT_UNKNOWN_TIMEOUT', .3), \
                mock.patch.object(OrderPage, 'RESULT_POLL_INTERVAL', .05):
            outcome = adapter.execute_armed(plan, self.journal, 'automatic-recovery', cfg, on_order=bridge._handle_order)
        navigation.assert_called_once()
        self.assertEqual(clicks_before_navigation, [(['G8821|二等座'], 1)])
        self.assertEqual(self.driver.execute_script('return window.orderActions'), 0)
        self.assertEqual((outcome.last_result.status, outcome.last_result.order_id), ('pending_payment', 'E888888'))
        self.assertEqual(self.journal.pending()['result']['order_id'], 'E888888')
        stages = [event['stage'] for event in self.journal.run_events('automatic-recovery')]
        self.assertEqual(stages.count('regular_auto_reconcile'), 1)
        self.assertEqual(stages.count('regular_confirm_dispatched'), 1)
        self.assertNotIn('verification', stages)
        self.assertEqual(bridge._notify_async.call_args.kwargs['event_type'], 'payment')

    def test_legacy_qr_submit_id_confirm_still_works_and_multi_passenger_modal_succeeds(self):
        adapter, plan, cfg = self.arm_single_or_pair(
            train_code="G8821", seat_keyword="二等座", passengers="张三,赵六"
        )
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8821', '二等座', 'direct_confirm');
            window.fixture.setPassengers('张三\u3000赵六');
            window.fixture.unlock();
            """
        )
        outcome = adapter.execute_armed(plan, self.journal, "multi-direct-confirm", cfg)
        self.assertEqual(outcome.action, "handled")
        self.assertEqual((outcome.last_result.status, outcome.last_result.order_id), ("pending_payment", "E888888"))
        self.assertEqual(self.fixture_confirm_clicks(), 1)

        legacy_journal = OrderJournal(Path(self.temp.name) / "orders-legacy-qr.sqlite3")
        adapter_qr, plan_qr, cfg_qr = self.arm_single_or_pair(
            train_code="G8821", seat_keyword="二等座", passengers="张三"
        )
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8821', '二等座', 'legacy_qr_confirm');
            window.fixture.unlock();
            """
        )
        qr_outcome = adapter_qr.execute_armed(plan_qr, legacy_journal, "legacy-qr", cfg_qr)
        self.assertEqual((qr_outcome.last_result.status, qr_outcome.last_result.order_id), ("pending_payment", "E888888"))
        self.assertEqual(self.fixture_confirm_clicks(), 1)

    def test_editor_page_never_sets_order_form_ready(self):
        self.driver.get((FIXTURES / "prefill-editor.html").resolve().as_uri())
        snap = OrderPage(self.driver, allow_fixture=True).snapshot()
        self.assertFalse(snap["formReady"])
        self.assertFalse(snap["confirmation"])

    def test_mismatched_and_extra_passenger_confirm_dialogs_never_confirm(self):
        for mode in ("confirm_mismatch", "confirm_extra_passenger", "confirm_wrong_seat", "confirm_student_type"):
            with self.subTest(mode=mode):
                sub_journal = OrderJournal(Path(self.temp.name) / f"orders-{mode}.sqlite3")
                adapter, plan, cfg = self.arm_single_or_pair(train_code="G8821", seat_keyword="二等座", passengers="张三")
                self.driver.execute_script(
                    """
                    window.fixture.setOutcome('G8821', '二等座', arguments[0]);
                    window.fixture.unlock();
                    """,
                    mode,
                )
                run_id = f"bad-confirm-{mode}"
                outcome = adapter.execute_armed(plan, sub_journal, run_id, cfg)
                self.assertEqual(outcome.action, "handled")
                self.assertEqual(outcome.last_result.status, "verification")
                self.assertFalse(outcome.last_result.no_order)
                self.assertEqual(self.fixture_clicks(), ["G8821|二等座"])
                self.assertEqual(self.fixture_confirm_clicks(), 0)

                pending = sub_journal.pending()
                self.assertIsNotNone(pending)
                self.assertEqual(pending["result"]["status"], "verification")
                self.assertTrue(sub_journal.submission_started(outcome.last_intent.intent_id))

                stages = [e["stage"] for e in sub_journal.run_events(run_id)]
                self.assertEqual(
                    stages,
                    ["submitting", "inventory_found", "prefill_submit", "order_result", "verification"],
                )
                self.assertNotIn("regular_submit", stages)

    def test_confirm_over_form_skips_form_actions_and_scopes_confirmation_names(self):
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8821", seat_keyword="二等座", passengers="张三")
        captured_dom = []
        orig_matches = adapter._confirmation_matches

        def spy_confirmation_matches(intent):
            captured_dom.append(
                (
                    OrderPage(self.driver, allow_fixture=True).snapshot(),
                    self.driver.execute_script(CONFIRMATION_SNAPSHOT_JS),
                )
            )
            return orig_matches(intent)

        adapter._confirmation_matches = spy_confirmation_matches
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8821', '二等座', 'confirm_over_form');
            window.fixture.unlock();
            """
        )
        outcome = adapter.execute_armed(plan, self.journal, "confirm-over-form", cfg)

        # Assert real DOM readback while both background form table and .up-box confirmation table were visible.
        self.assertEqual(len(captured_dom), 1)
        page_snap, confirm_snap = captured_dom[0]
        self.assertTrue(page_snap["formReady"])
        self.assertTrue(page_snap["confirmation"])
        self.assertEqual(confirm_snap["names"], ["张三"])

        self.assertEqual(outcome.action, "handled")
        self.assertEqual((outcome.last_result.status, outcome.last_result.order_id), ("pending_payment", "E888888"))
        self.assertEqual(self.fixture_clicks(), ["G8821|二等座"])
        self.assertEqual(self.fixture_confirm_clicks(), 1)
        self.assertEqual(self.fixture_form_submit_clicks(), 0)

        pending = self.journal.pending()
        self.assertIsNotNone(pending)
        self.assertEqual((pending["result"]["status"], pending["result"]["order_id"]), ("pending_payment", "E888888"))

        stages = [e["stage"] for e in self.journal.run_events("confirm-over-form")]
        self.assertEqual(
            stages,
            [
                "submitting",
                "inventory_found",
                "prefill_submit",
                "regular_submit",
                "regular_confirm_attempt",
                "regular_confirm_dispatched",
                "order_result",
                "pending_payment",
            ],
        )
        self.assertNotIn("prefill_form_opened", stages)

    def test_mixed_sale_times_in_same_tab_enforces_detail_countdown_tolerance(self):
        cfg = {
            **self.config,
            "train_code": "G8821",
            "seat_keyword": "二等座",
            "passengers": "张三",
        }
        mixed_selected = (
            "C2551|大兴机场|天津西|二等座|11月7日12点45分起售;"
            "G8821|大兴机场|天津西|二等座|11月7日16点起售"
        )
        mismatch_url = (
            (FIXTURES / "prefill-order.html").resolve().as_uri()
            + f"?date=2026-11-21&selected={quote(mixed_selected)}&passengers=%E5%BC%A0%E4%B8%89"
            + f"&countdown={quote('18小时0分钟0秒')}"
        )
        adapter_bad = self.adapter(now=NOW_1550, prefill_order_url=mismatch_url)
        with self.assertRaises(PrefillFallback) as ctx:
            adapter_bad.prepare(cfg, SALE_1600, check_existing=True)
        self.assertEqual(ctx.exception.stage, "countdown_mismatch")
        bad_snap = adapter_bad._detail_snapshot()
        self.assertEqual([c["sale_label"] for c in bad_snap["cards"]], ["11月7日12点45分起售", "11月7日16点起售"])
        self.assertEqual(bad_snap["countdown_text"], "18小时0分钟0秒")
        self.assertEqual(self.fixture_clicks(), [])
        self.assertIsNone(self.journal.pending())
        self.assertEqual(self.journal.run_events("mixed-mismatch"), [])

        matching_url = (
            (FIXTURES / "prefill-order.html").resolve().as_uri()
            + f"?date=2026-11-21&selected={quote(mixed_selected)}&passengers=%E5%BC%A0%E4%B8%89"
            + f"&countdown={quote('0小时10分钟0秒')}"
        )
        adapter_ok = self.adapter(now=NOW_1550, prefill_order_url=matching_url)
        plan = adapter_ok.prepare(cfg, SALE_1600, check_existing=True)
        self.assertEqual(
            [(c.train_code, c.from_station, c.to_station, c.seat) for c in plan.candidates],
            [("G8821", "大兴机场", "天津西", "二等座")],
        )
        ok_snap = adapter_ok._detail_snapshot()
        self.assertEqual([c["sale_label"] for c in ok_snap["cards"]], ["11月7日12点45分起售", "11月7日16点起售"])
        self.assertEqual(ok_snap["countdown_text"], "0小时10分钟0秒")
        self.assertEqual(self.fixture_clicks(), [])
        self.assertIsNone(self.journal.pending())
        self.assertEqual(self.journal.run_events("mixed-ok"), [])

    def test_partial_sold_out_then_second_unlock_timeout_reports_only_first_sold_out(self):
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8863,G8821", seat_keyword="二等座", passengers="张三")
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8863', '二等座', 'sold_out');
            window.fixture.unlock('G8863', '二等座');
            """
        )
        with mock.patch.dict("railwatch_prefill.ORDER_POLICIES", {"prefill_unlock_timeout_ms": 300}):
            outcome = adapter.execute_armed(plan, self.journal, "partial-sold-out", cfg)
        self.assertEqual(outcome.action, "fallback_to_query")
        self.assertEqual([(c.train_code, c.seat) for c in outcome.sold_out_candidates], [("G8863", "二等座")])
        self.assertEqual(outcome.last_intent.train_code, "G8863")
        self.assertEqual(outcome.last_result.status, "sold_out")
        self.assertTrue(outcome.last_result.no_order)
        self.assertEqual(self.fixture_clicks(), ["G8863|二等座"])
        self.assertEqual(self.fixture_confirm_clicks(), 0)
        self.assertIsNone(self.journal.pending())

        events = self.journal.run_events("partial-sold-out")
        self.assertEqual(
            [e["stage"] for e in events],
            [
                "submitting",
                "inventory_found",
                "prefill_submit",
                "prefill_official_rejected",
                "order_result",
                "confirmed_failure",
                "prefill_fallback",
            ],
        )
        self.assertEqual(events[-1]["detail"], {"stage": "unlock_timeout", "train": "G8821", "seat": "二等座"})

    def test_stale_buy_button_after_rerender_relocates_once_without_unknown_lock(self):
        adapter, plan, cfg = self.arm_single_or_pair(train_code="G8821", seat_keyword="二等座", passengers="张三")
        orig_wait_buy = adapter._wait_buy_button
        rerendered = []

        def wait_buy_then_rerender(cand, timeout_seconds):
            btn = orig_wait_buy(cand, timeout_seconds)
            if btn is not None and not rerendered:
                rerendered.append(True)
                self.driver.execute_script("window.fixture.rerender();")
            return btn

        adapter._wait_buy_button = wait_buy_then_rerender
        self.driver.execute_script(
            """
            window.fixture.setOutcome('G8821', '二等座', 'sold_out');
            window.fixture.unlock();
            """
        )
        outcome = adapter.execute_armed(plan, self.journal, "stale-rerender", cfg)
        self.assertEqual(outcome.action, "sold_out_all")
        self.assertEqual(outcome.last_result.status, "sold_out")
        self.assertTrue(outcome.last_result.no_order)
        self.assertEqual(self.fixture_clicks(), ["G8821|二等座"])
        self.assertEqual(self.fixture_confirm_clicks(), 0)
        self.assertIsNone(self.journal.pending())

        events = self.journal.run_events("stale-rerender")
        self.assertEqual(
            [e["stage"] for e in events],
            [
                "submitting",
                "inventory_found",
                "prefill_submit",
                "prefill_click_rejected",
                "prefill_submit",
                "prefill_official_rejected",
                "order_result",
                "confirmed_failure",
            ],
        )
        self.assertEqual(events[3]["detail"], {"kind": "StaleElementReferenceException"})
        self.assertEqual({e["intent_id"] for e in events if e["intent_id"]}, {outcome.last_intent.intent_id})

    def test_prepare_rejects_persistent_detail_dialog_before_arming(self):
        cfg = {
            **self.config,
            "train_code": "G8821",
            "seat_keyword": "二等座",
            "passengers": "张三",
        }
        dialog_url = (
            (FIXTURES / "prefill-order.html").resolve().as_uri()
            + f"?date=2026-11-21&selected={quote('G8821|大兴机场|天津西|二等座')}&passengers=%E5%BC%A0%E4%B8%89"
            + f"&dialog={quote('请先核对提示')}"
        )
        adapter = self.adapter(prefill_order_url=dialog_url)
        with self.assertRaises(PrefillFallback) as ctx:
            adapter.prepare(cfg, SALE_1600, check_existing=True)
        self.assertEqual(ctx.exception.stage, "detail_dialog")
        self.assertEqual(len(adapter._detail_snapshot()["dialogs"]), 1)
        self.assertEqual(self.fixture_clicks(), [])
        self.assertEqual(self.fixture_confirm_clicks(), 0)
        self.assertIsNone(self.journal.pending())
        self.assertEqual(self.journal.run_events("detail-dialog"), [])

    def test_hidden_countdown_after_unlock_produces_empty_countdown_text(self):
        adapter, _, _ = self.arm_single_or_pair(train_code="G8821", seat_keyword="二等座", passengers="张三")
        before = adapter._detail_snapshot()
        self.assertTrue(before["unonsale_visible"])
        self.assertFalse(before["onsale_visible"])
        self.assertEqual(before["countdown_text"], "0小时10分钟0秒")

        self.driver.execute_script("window.fixture.unlock();")
        raw_node_text = self.driver.execute_script("return document.getElementById('countdown-text').textContent;")
        self.assertEqual(raw_node_text, "0小时10分钟0秒")

        after = adapter._detail_snapshot()
        self.assertFalse(after["unonsale_visible"])
        self.assertTrue(after["onsale_visible"])
        self.assertEqual(after["countdown_text"], "")
        self.assertEqual(self.fixture_clicks(), [])
        self.assertEqual(self.fixture_confirm_clicks(), 0)
        self.assertIsNone(self.journal.pending())
        self.assertEqual(self.journal.run_events("hidden-countdown"), [])


if __name__ == "__main__":
    unittest.main()
