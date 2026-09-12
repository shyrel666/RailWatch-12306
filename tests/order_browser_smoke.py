"""Actual Chrome + visible DOM; isolated profile and blocked railway network."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from railwatch_bridge import CHROMEDRIVER_PATH
from railwatch_order_page import OrderPage
from railwatch_orders import OrderIntent
from railwatch_submit_flow import SubmitFlow


class OrderBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = tempfile.TemporaryDirectory(prefix="railwatch-order-browser-")
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-background-networking")
        options.add_argument(f"--user-data-dir={cls.profile.name}")
        cls.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
        cls.driver.execute_cdp_cmd("Network.enable", {})
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*"]})

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile.cleanup()

    def setUp(self):
        self.driver.get((Path(__file__).parent / "fixtures/orders.html").resolve().as_uri())
        self.page = OrderPage(self.driver, allow_fixture=True)
        self.intent = OrderIntent("regular", "G101", "2026-09-10", "北京", "上海", "二等座", ("张三",), "18:00")

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def test_regular_order_verified_once_then_payment_observed(self):
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual((result.status, result.order_id), ("pending_payment", "E123456"))
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])
        self.js("fixture.record('已支付')")
        self.assertEqual(self.page.result(self.intent, known_id="E123456").status, "fulfilled")

    def test_priced_seat_and_official_train_station_suffixes_submit_once(self):
        self.js("""
          el('ticket_info').innerText='2026-09-10（周四） G101次 北京站（09:29开）—上海站（19:00到）';
          const original=people;
          people=(...args)=>{ original(...args);
            document.querySelectorAll('select[id^="seatType_"] option').forEach(o=>o.text+='（927.0元）');
          };
        """)
        result = self.page.regular(self.driver.find_element('id', 'book'), self.intent)
        self.assertEqual(result.status, 'pending_payment')
        self.assertEqual(self.js('return [fixture.regularClicks,fixture.confirmClicks]'), [1, 1])

    def test_official_packed_summary_in_ticket_tit_id_submits(self):
        # Measured on the real confirm page: no #ticket_info, and the summary in
        # #ticket_tit_id glues tokens together with no spaces.
        self.js("""
          el('ticket_info').remove();
          const tit=document.createElement('div');
          tit.id='ticket_tit_id';
          tit.innerText='2026-09-10（周四）G101次北京站（09:29开）—上海站（19:00到）';
          el('regular').prepend(tit);
        """)
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])

    def test_readback_failure_logs_field_level_diff(self):
        original_poll = self.page.poll
        self.page.poll = lambda predicate, timeout=10: original_poll(predicate, min(timeout, 0.2))
        messages = []
        self.page.log = messages.append
        self.js("el('ticket_info').innerText='G999次 2026-09-10 北京 上海 一等座'")
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "verification")
        report = next((message for message in messages if "回读核对未通过" in message), "")
        self.assertIn("车次：期望 G101次，实际 未读到", report)
        self.assertIn("页面摘要：G999次", report)
        self.assertNotIn("张三", report)
        self.assertEqual(self.js("return fixture.regularClicks"), 0)

    def test_missing_or_ambiguous_seat_never_submits(self):
        for options in ['<option>高级软卧（927.0元）</option>',
                        '<option>二等座（927.0元）</option><option>二等座（900.0元）</option>',
                        '<option>一等座</option><option disabled>二等座（927.0元）</option>']:
            with self.subTest(options=options):
                self.setUp()
                self.js("""const original=people;
                  const options=arguments[0];
                  people=(...args)=>{original(...args);el('seatType_0').innerHTML=options;};""", options)
                result = self.page.regular(self.driver.find_element('id', 'book'), self.intent)
                self.assertEqual(result.status, 'verification')
                self.assertIn('席别', result.reason)
                self.assertEqual(self.js('return fixture.regularClicks'), 0)

    def test_pre_submit_exception_reports_stage_without_passenger_data(self):
        messages = []
        self.page.log = messages.append
        self.page.select_regular_seats = Mock(side_effect=RuntimeError('private-passenger-details'))
        result = self.page.regular(self.driver.find_element('id', 'book'), self.intent)
        self.assertEqual(result.status, 'verification')
        self.assertIn('尚未点击提交订单', result.reason)
        self.assertIn('选择席别', result.reason)
        self.assertNotIn('private-passenger-details', str(messages))
        self.assertEqual(self.js('return fixture.regularClicks'), 0)

    def test_route_is_read_from_selected_query_row(self):
        from railwatch_row_parser import RowParser
        self.js("""el('records').innerHTML='<div id="query-row"><div class="cdz"><strong>北京丰台</strong><br><strong>成都东</strong></div></div>';""")
        self.assertEqual(RowParser.selected_route(self.driver.find_element('id', 'query-row')), ('北京丰台', '成都东'))

    def test_seat_preference_reaches_confirmation_and_is_read_back(self):
        for preference, expected in [("靠窗优先", "A"), ("靠过道优先", "C"), ("无偏好", "B")]:
            with self.subTest(preference=preference):
                self.setUp()
                self.js("fixture.preferenceEnabled=true")
                messages = []
                self.page.log = messages.append
                flow = SubmitFlow(self.driver, {"seat_prefer":preference})
                flow.order_page = self.page
                result = flow.try_auto_submit(self.driver.find_element("id", "book"), "二等座", intent=self.intent)
                self.assertEqual(result.status, "pending_payment")
                self.assertEqual(self.js("return fixture.seatPreference"), expected)
                self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1,1])
                if preference != "无偏好":
                    self.assertTrue(any("已回读确认" in message for message in messages))

    def test_unavailable_preference_is_reported_without_repeating_submission(self):
        messages = []
        self.page.log = messages.append
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent, seat_preference="靠窗优先")
        self.assertEqual(result.status, "pending_payment")
        self.assertTrue(any("未能应用座位偏好" in message for message in messages))
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1,1])

    def test_candidate_order_binds_combination_and_payment_does_not_mean_fulfilled(self):
        selected = replace(self.intent, kind="alternate")
        result = self.page.alternate(self.driver.find_element("id", "candidate"), selected)
        self.assertEqual(result.status, "pending_payment")
        self.js("fixture.record('待兑现')")
        self.assertEqual(self.page.result(selected, known_id=result.order_id).status, "active")
        self.js("fixture.record('兑现成功')")
        self.assertEqual(self.page.result(selected, known_id=result.order_id).status, "fulfilled")
        self.assertEqual(self.js("return fixture.alternateClicks"), 1)

    def test_wrong_candidate_seat_and_extra_choices_never_submit(self):
        for script in ["document.querySelector('.ticket-info-txt span').innerText='一等座'",
                       "document.getElementById('addTrainInput').checked=true",
                       "document.getElementById('is_open').innerText='已开启'",
                       "document.getElementById('planList').innerHTML='<div class=group-ticket>G102</div>'"]:
            self.setUp()
            self.js(script)
            result = self.page.alternate(self.driver.find_element("id", "candidate"), replace(self.intent, kind="alternate"))
            self.assertEqual(result.status, "verification")
            self.assertEqual(self.js("return fixture.alternateClicks"), 0)

    def test_deadline_selection_failure_never_submits(self):
        result = self.page.alternate(self.driver.find_element("id", "candidate"), replace(self.intent, kind="alternate", deadline="19:30"))
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.alternateClicks"), 0)

    def test_duplicate_passenger_name_rejected(self):
        self.js("document.getElementById('normal_passenger_id').innerHTML+='<label title=张三><input type=checkbox>张三</label>'")
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.regularClicks"), 0)

    def test_sold_out_before_submission_can_fallback(self):
        self.js("fixture.mode='sold_out'")
        self.assertTrue(self.page.regular(self.driver.find_element("id", "book"), self.intent).can_fallback)
        self.assertEqual(self.js("return fixture.regularClicks"), 0)

    def test_verification_after_submit_does_not_confirm_or_retry(self):
        self.js("fixture.mode='verification'")
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 0])

    def test_generic_success_does_not_create_order_evidence(self):
        self.js("document.getElementById('records').innerHTML='<div class=success-tip>候补成功</div>'")
        self.assertEqual(self.page.result(replace(self.intent, kind="alternate")).status, "unknown")

    def test_order_identity_passengers_and_seat_must_match(self):
        self.js("fixture.record()")
        for changed in [replace(self.intent, seat="一等座"), replace(self.intent, train_code="G102"), replace(self.intent, passengers=("李四",)), replace(self.intent, date="2026-09-11")]:
            self.assertEqual(self.page.result(changed).status, "unknown")

    def test_accepted_confirmation_then_transport_failure_still_reads_order_without_retry(self):
        original_button = self.page.button
        def button(selectors):
            found = original_button(selectors)
            if found and selectors == ("#qr_submit_id",):
                def click():
                    found.click()
                    raise TimeoutError("Response lost after server acceptance")
                return Mock(click=click)
            return found
        self.page.button = button
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])

    def test_lost_confirmation_ack_with_delayed_dom_never_reclicks(self):
        self.js("""
          const submit=el('submitOrder_id').onclick;
          el('submitOrder_id').onclick=()=>{
            submit();
            el('qr_submit_id').onclick=()=>{
              fixture.confirmClicks++;
              setTimeout(()=>record(),800);
            };
          };
        """)
        original_button = self.page.button
        def button(selectors):
            found = original_button(selectors)
            if found and selectors == ("#qr_submit_id",):
                def click():
                    found.click()
                    raise TimeoutError("Acknowledgement lost while confirmation remains visible")
                return Mock(click=click)
            return found
        self.page.button = button
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])

    def test_timeout_or_stop_after_submit_never_replays_or_reports_sold_out(self):
        self.js("fixture.mode='timeout'")
        original_poll = self.page.poll
        self.page.poll = lambda predicate, timeout=10, ignore_stop=False: original_poll(
            predicate, min(timeout, 0.2), ignore_stop=ignore_stop)
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.can_fallback)
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 0])
        self.page.stop = lambda: True
        self.assertEqual(self.page.wait_result(self.intent).status, "unknown")
        self.assertEqual(self.js("return fixture.regularClicks"), 1)

    def test_stop_request_between_submit_and_confirm_still_completes_submission(self):
        # 抢票语义：提交已在途，停止请求不得放弃已到场的官方确认弹窗。
        state = {"stopped": False}
        self.page.stop = lambda: state["stopped"]
        original_poll = self.page.poll
        self.page.poll = lambda predicate, timeout=10, ignore_stop=False: original_poll(
            predicate, min(timeout, 0.2), ignore_stop=ignore_stop)
        original_button = self.page.button
        def button(selectors):
            found = original_button(selectors)
            if found and selectors == ("#submitOrder_id",):
                def click():
                    state["stopped"] = True  # 停止落在提交之后、弹窗渲染之前
                    found.click()
                return Mock(click=click)
            return found
        self.page.button = button
        messages = []
        self.page.log = messages.append
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])
        self.assertTrue(any("仍完成本次确认" in message for message in messages))

    def test_unconfirmed_dialog_keeps_page_and_requests_manual_confirm(self):
        self.js("fixture.mode='normal'")
        original_poll = self.page.poll
        self.page.poll = lambda predicate, timeout=10, ignore_stop=False: original_poll(
            predicate, min(timeout, 0.2), ignore_stop=ignore_stop)
        original_button = self.page.button
        def button(selectors):
            found = original_button(selectors)
            # The official dialog is up, but the confirm click is swallowed.
            if found and selectors == ("#qr_submit_id",):
                return Mock(click=lambda: None)
            return found
        self.page.button = button
        self.page.reconcile = Mock()
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "verification")
        self.assertIn("确认", result.reason)
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 0])
        self.assertIn("orders.html", self.driver.current_url)
        self.page.reconcile.assert_not_called()

    def test_relative_deadline_selects_offered_equivalent_and_reads_back(self):
        self.js("document.querySelector('#date_box li').innerText='开车前1小时'")
        result = self.page.alternate(self.driver.find_element("id", "candidate"), replace(self.intent, kind="alternate", deadline="开车前60分钟"))
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return document.getElementById('dafaultTime').innerText"), "开车前1小时")


if __name__ == "__main__":
    unittest.main(verbosity=2)
