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

    def test_official_processing_dialog_waits_for_matching_order(self):
        self.js("""
          const submit=el('submitOrder_id').onclick;
          el('submitOrder_id').onclick=()=>{
            submit();
            el('qr_submit_id').onclick=()=>{
              fixture.confirmClicks++;
              el('dialog').innerHTML='<div id="transforNotice_id" class="up-box"><i id="iamge_status_id" class="icon i-work"></i><div id="orderResultInfo_id"><div class="tit">正在处理，请稍候。</div><p>查看订单处理情况，请点击未完成订单</p></div></div>';
              setTimeout(()=>record(),600);
            };
          };
        """)
        self.page.reconcile = Mock()
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])
        self.page.reconcile.assert_not_called()

    def test_immediate_payment_table_requires_order_identity_and_stays_on_page(self):
        self.js("""
          const submit=el('submitOrder_id').onclick;
          el('submitOrder_id').onclick=()=>{
            submit();
            el('qr_submit_id').onclick=()=>{
              fixture.confirmClicks++;
              el('dialog').classList.add('hidden');
              el('regular').classList.add('hidden');
              el('records').innerHTML='<p>订单号：E123456</p><div id="show_title_ticket">2026-09-10（周四）G101次北京站（09:29开）—上海站（19:00到）</div><table><thead><tr><th>姓名</th><th>席别</th></tr></thead><tbody id="show_ticket_message"><tr><td>张三</td><td>二等座</td></tr></tbody></table><a id="payButton">网上支付</a>';
            };
          };
        """)
        self.page.reconcile = Mock()
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual((result.status,result.order_id), ("pending_payment","E123456"))
        self.page.reconcile.assert_not_called()
        for change in (replace(self.intent, seat="一等座"), replace(self.intent, passengers=("李四",)), replace(self.intent, date="2026-09-11"), replace(self.intent, train_code="G102")):
            self.assertEqual(self.page.result(change).status, "unknown")
        self.js("el('records').insertAdjacentHTML('beforeend','<p>订单号：E999999</p>')")
        self.assertEqual(self.page.result(self.intent).status, "unknown")

    def test_official_queue_and_hidden_dialogs_are_not_unknown_prompts(self):
        for title in ("订单已经提交，系统正在处理中，请稍等。", "订单已经提交，预计等待时间超过30分钟，请耐心等待。", "订单已经提交，最新预估等待时间10秒，请耐心等待。"):
            self.js("""el('dialog').innerHTML='<i id="iamge_status_id" class="icon i-queue"></i><div id="orderResultInfo_id"><div class="tit"></div></div>';show('dialog');document.querySelector('.tit').textContent=arguments[0];""", title)
            result = self.page.result(self.intent, submitted=True)
            self.assertEqual(result.status, "unknown")
            self.assertIn("仍在处理", result.reason)
        self.js("el('dialog').style.visibility='hidden'")
        snap = self.page.snapshot()
        self.assertEqual(snap['dialogs'], [])
        self.assertFalse(snap['processing'])

    def test_official_anchor_waits_for_delayed_handler_binding_before_click(self):
        # Official passengerInfo_js.js unbinds click and uses btn92 while its
        # timer runs; only after binding the handler does it switch to btn92s.
        self.js("""
          const submit=el('submitOrder_id').onclick;
          fixture.nativeConfirmClicks=0;
          el('submitOrder_id').onclick=()=>{
            submit();
            const button=el('qr_submit_id'), handler=button.onclick;
            button.onclick=null;
            button.className='btn92';
            button.addEventListener('click',()=>fixture.nativeConfirmClicks++);
            setTimeout(()=>{button.onclick=handler;button.className='btn92s';},1200);
          };
        """)
        original_wait = self.page.wait_result
        self.page.wait_result = lambda intent, submitted=True, timeout=10: original_wait(
            intent, submitted=submitted, timeout=0.2)
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.nativeConfirmClicks,fixture.confirmClicks]"), [1, 1, 1])

    def test_official_disabled_anchor_never_receives_a_confirmation_click(self):
        self.js("""
          const submit=el('submitOrder_id').onclick;
          fixture.nativeConfirmClicks=0;
          el('submitOrder_id').onclick=()=>{
            submit();
            const button=el('qr_submit_id');
            button.onclick=null;
            button.className='btn92';
            button.addEventListener('click',()=>fixture.nativeConfirmClicks++);
          };
        """)
        original_poll = self.page.poll
        self.page.poll = lambda predicate, timeout=10, ignore_stop=False: original_poll(
            predicate, min(timeout, 0.2), ignore_stop=ignore_stop)
        self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.nativeConfirmClicks,fixture.confirmClicks]"), [1, 0, 0])

    def test_delayed_official_confirmation_submits_without_manual_action(self):
        self.js("""
          const submit=el('submitOrder_id').onclick;
          el('submitOrder_id').onclick=()=>setTimeout(()=>{
            submit();
            el('dialog').insertAdjacentHTML('afterbegin',
              '<h3>请核对以下信息</h3><table><tr><th>姓名</th></tr><tr><td>张三</td></tr></table>');
            el('qr_submit_id').innerText='确认';
          }, 11000);
        """)
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])

    def test_confirmation_dom_replacement_is_retried_automatically(self):
        original_button = self.page.button
        replaced = []
        def button(selectors):
            found = original_button(selectors)
            if found and selectors == ("#qr_submit_id",) and not replaced:
                self.js("""
                  const old=el('qr_submit_id'), fresh=old.cloneNode(true);
                  fresh.onclick=old.onclick;
                  old.replaceWith(fresh);
                """)
                replaced.append(True)
            return found
        self.page.button = button
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])

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

    def test_numeric_train_code_is_read_from_the_train_marker_not_the_fare(self):
        selected = replace(self.intent, train_code="1461")
        self.js("""document.getElementById('records').innerHTML=`
          <div class="order-item"><div class="order-item-hd">订单号：E123456
          <span class="order-status">待支付</span></div>
          <p>1462次 2026年9月10日 北京 上海 二等座 ¥1461.0元</p>
          <div class="passenger-name"><strong title="张三">张三</strong></div></div>`""")
        self.assertEqual(self.page.result(selected).status, "unknown")
        self.js("document.querySelector('.order-item p').textContent='1461次 2026年9月10日 北京 上海 二等座 ¥88.0元'")
        self.assertEqual(self.page.result(selected).status, "pending_payment")

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

    def test_swallowed_native_click_dispatches_confirmation_automatically(self):
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
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])
        self.assertIn("orders.html", self.driver.current_url)
        self.page.reconcile.assert_not_called()

    def test_delivered_click_without_order_is_not_dispatched_again(self):
        self.js("""
          const submit=el('submitOrder_id').onclick;
          el('submitOrder_id').onclick=()=>{
            submit();
            el('qr_submit_id').onclick=()=>{fixture.confirmClicks++;};
          };
        """)
        original_poll = self.page.poll
        self.page.poll = lambda predicate, timeout=10, ignore_stop=False: original_poll(
            predicate, min(timeout, 0.2), ignore_stop=ignore_stop)
        result = self.page.regular(self.driver.find_element("id", "book"), self.intent)
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return [fixture.regularClicks,fixture.confirmClicks]"), [1, 1])

    def test_relative_deadline_selects_offered_equivalent_and_reads_back(self):
        self.js("document.querySelector('#date_box li').innerText='开车前1小时'")
        result = self.page.alternate(self.driver.find_element("id", "candidate"), replace(self.intent, kind="alternate", deadline="开车前60分钟"))
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return document.getElementById('dafaultTime').innerText"), "开车前1小时")


if __name__ == "__main__":
    unittest.main(verbosity=2)
