"""Native Chrome regression against sanitized official form/order structures."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from order_browser_smoke import OrderBrowserTests
from railwatch_order_page import OrderPage
from railwatch_alternate_options import NewTrainWindow
from test_multi_alternate import PRIMARY, CONFIG


class AlternateOptionsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OrderBrowserTests.setUpClass()
        cls.driver = OrderBrowserTests.driver
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["*12306.cn*", "https://*"]})

    @classmethod
    def tearDownClass(cls):
        OrderBrowserTests.tearDownClass()

    def setUp(self):
        self.driver.get((ROOT / "tests/fixtures/multi-alternate.html").as_uri())
        self.driver.execute_script((ROOT / "tests/fixtures/new-train-controls.js").read_text(encoding="utf-8"))
        self.page = OrderPage(self.driver, allow_fixture=True, poll_interval=.01)
        self.page.RESULT_UNKNOWN_TIMEOUT = .05
        self.intent = replace(PRIMARY, new_train_windows=(NewTrainWindow(PRIMARY.date, 8, 22),))
        self.stages = []
        self.page.mark = lambda stage, detail=None: self.stages.append((stage, detail))

    def js(self, script):
        return self.driver.execute_script(script)

    def submit(self, intent=None):
        return self.page.alternate(self.driver.find_element("id", "candidate"), intent or self.intent)

    def test_native_controls_save_conditions_capture_rate_and_match_order_details(self):
        result = self.submit()
        self.assertEqual((result.status, result.order_id), ("pending_payment", "E123456"), result.reason)
        self.assertEqual(self.js("return fixture.windows"), [{"date": PRIMARY.date, "start_hour": 8, "end_hour": 22}])
        self.assertEqual(self.js("return [fixture.newSaves,fixture.submitClicks,fixture.newDetails]"), [1, 1, 1])
        form = next(data for stage, data in self.stages if stage == "alternate_form")
        self.assertEqual(form["success_rate"], 40)
        self.assertEqual(form["new_train_windows"], self.js("return fixture.windows"))
        self.assertFalse(self.page.snapshot()["dialogs"])

    def test_multiple_dates_and_recovery_keep_saved_windows(self):
        intent = replace(self.intent, new_train_windows=(NewTrainWindow("2026-10-09", 10, 18), NewTrainWindow(PRIMARY.date, 8, 22)))
        saved = []
        self.page.bind_intent = saved.append
        self.js("fixture.collapsed=true")
        result = self.page.alternate(self.driver.find_element("id", "candidate"), intent, plan_config=CONFIG)
        self.assertEqual(result.status, "pending_payment", result.reason)
        self.assertEqual(saved[0].new_train_windows, intent.new_train_windows)
        recovered = OrderPage(self.driver, allow_fixture=True).reconcile(saved[0], known_id="E123456")
        self.assertEqual(recovered.status, "pending_payment", recovered.reason)
        self.assertEqual(self.js("return fixture.submitClicks"), 1)

    def test_wrong_conditions_or_changed_form_never_submit(self):
        cases = ["fixture.ruleRoute='北京南-上海'", "fixture.ruleSeat='一等座'", "fixture.windowDates=['2026-10-09']",
                 "fixture.changeSavedWindow=true", "fixture.onNewOpen=b=>b.querySelector('.linkeTime').disabled=true",
                 "fixture.onNewClose=()=>document.querySelector('#ticket_card_list .ticket-number').textContent='G999'"]
        for script in cases:
            with self.subTest(script=script):
                self.setUp()
                self.js(script)
                result = self.submit()
                self.assertEqual(result.status, "verification", result.reason)
                self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_order_conditions_mismatch_does_not_bind_id(self):
        self.js("fixture.orderSummary='乘车区间：北京-上海 席别：二等座 10月10日：0点-24点'")
        result = self.submit()
        self.assertEqual(result.status, "verification")
        self.assertFalse(result.order_id)
        self.assertEqual(self.js("return fixture.submitClicks"), 1)

    def test_identity_change_after_closing_order_conditions_is_not_adopted(self):
        self.js("fixture.onNewClose=()=>{const n=document.querySelector('.order-item-hd');if(n)n.textContent='候补单号：E999999';}")
        result = self.submit()
        self.assertEqual(result.status, "verification")
        self.assertFalse(result.order_id)

    def test_official_added_fulfillment_requires_known_id_marker_and_time_within_saved_window(self):
        self.assertEqual(self.submit().status, "pending_payment")
        self.js("fixture.record('兑现成功',[{train:'G999',date:'2026-10-10',from:'北京南',to:'上海虹桥',seat:'二等座'}]);"
                "document.querySelector('.order-item .ticket-card').classList.add('success');"
                "document.querySelector('.order-item .ticket-station-start').insertAdjacentHTML('beforeend','<div class=ticket-station-time>09:30</div>');"
                "document.querySelector('.order-item').insertAdjacentHTML('beforeend','<div class=success-temporary-train>临客 G999 兑现成功</div>');")
        self.assertEqual(self.page.result(self.intent).status, "unknown")
        result = self.page.reconcile(self.intent, known_id="E123456")
        self.assertEqual(result.status, "fulfilled", result.reason)
        for value in ("08:00", "22:00", "23:00", ""):
            self.driver.execute_script("document.querySelector('.order-item .ticket-station-time').textContent=arguments[0]", value)
            self.assertEqual(self.page.reconcile(self.intent, known_id="E123456").status, "unknown")

    def test_later_hour_interval_expands_end_before_selecting_disabled_start(self):
        result = self.submit(replace(self.intent, new_train_windows=(NewTrainWindow(PRIMARY.date, 20, 23),)))
        self.assertEqual(result.status, "pending_payment", result.reason)
        self.assertEqual(self.js("return fixture.windows[0].start_hour"), 20)

    def test_dynamic_deadlines_read_beyond_old_presets_and_reject_disabled_and_custom_values(self):
        self.js("document.getElementById('candidate').click();document.getElementById('date_box').innerHTML="
                "'<li>开车前1小时</li><li>开车前3天</li><li class=disabled>开车前4天</li><li style=display:none>开车前5天</li><li>2026-10-10 18:00</li>'")
        self.assertEqual(self.page.alternate_options()["deadline_options"], ["开车前1小时", "开车前3天"])
        self.assertTrue(self.page.set_deadline("开车前60分钟", PRIMARY.date))
        self.assertFalse(self.page.set_deadline("开车前4天", PRIMARY.date))
        self.assertFalse(self.page.set_deadline("2026-10-10 18:00", PRIMARY.date))

    def test_unavailable_deadline_retains_actual_options_for_reselection(self):
        result = self.submit(replace(PRIMARY, deadline="开车前2小时"))
        self.assertEqual(result.status, "verification")
        self.assertTrue(result.review["deadline_reselection"])
        self.assertEqual(result.review["deadline_options"], ["开车前1小时"])
        self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_empty_official_deadline_label_uses_native_dropdown_header(self):
        # Live 2026-10-11: the blank inner DIV has zero height; its .sel-hd
        # parent owns the clickable area and opens the official options.
        self.js("""
          const label=document.getElementById('dafaultTime');
          const header=document.createElement('div');header.className='sel-hd';
          header.style.cssText='width:200px;height:30px;border:1px solid';
          label.before(header);header.append(label);label.textContent='';label.onclick=null;
          header.onclick=()=>document.getElementById('date_box').classList.remove('hidden');
          document.querySelector('#date_box li').onclick=e=>{
            label.textContent=e.target.textContent;
            document.getElementById('date_box').classList.add('hidden');
          };
        """)
        result = self.submit(PRIMARY)
        self.assertEqual(result.status, "pending_payment", result.reason)
        self.assertEqual(self.js("return fixture.submitClicks"), 1)
        self.assertIn("alternate_submit", [stage for stage, _ in self.stages])

    def test_pre_submit_control_error_reports_actionable_verification(self):
        from selenium.common.exceptions import ElementNotInteractableException
        self.page.set_deadline = Mock(side_effect=ElementNotInteractableException("private browser details"))
        result = self.submit(PRIMARY)
        self.assertEqual(result.status, "verification")
        self.assertIn("尚未点击提交订单", result.reason)
        self.assertIn("截止兑现时间", result.reason)
        self.assertNotIn("private browser details", result.reason)
        self.assertEqual(self.js("return fixture.submitClicks"), 0)
        self.assertNotIn("alternate_submit", [stage for stage, _ in self.stages])

    def test_rate_loading_missing_zero_and_out_of_range_are_distinguished(self):
        self.js("document.getElementById('candidate').click()")
        for label, expected, status in (("0%", 0, "available"), ("40.5%", 40.5, "available"),
                                         ("--", None, "unavailable"), ("101%", None, "unavailable")):
            self.driver.execute_script("document.getElementById('toPayBtn').innerHTML='提交订单<br>预估成功率('+arguments[0]+')'", label)
            data = self.page.alternate_options()
            self.assertEqual((data["success_rate"], data["success_rate_status"]), (expected, status))
        self.js("document.getElementById('toPayBtn').innerHTML='<img alt=loading>'")
        self.assertEqual(self.page.alternate_options()["success_rate_status"], "loading")

    def install_quiet_advisory(self):
        message = ('选择该车次二等座可能候补到“静音车厢”席位，是否继续选择？'
            '在静音车厢内须保持安静，动作轻柔避免产生噪声；将手机等电子设备调至静音或振动状态；'
            '在接打电话或相互交谈时离开静音车厢；在使用电子设备时佩戴耳机或关闭音源外放功能；'
            '携带儿童出行的旅客照看好孩子，避免喧哗、哭闹。')
        self.driver.execute_script("""
          document.body.insertAdjacentHTML('beforeend','<div class="up-box hidden" id="content_defaultwarningAlert_id">温馨提示<a>关闭</a><p></p>'+
            '<label><input type=checkbox id=remember>记住我的选择，不再提示</label><a id=qd_cancelDefaultWarningWindowDialog_id>取消选择</a>'+
            '<a id=qd_closeDefaultWarningWindowDialog_id>仍然选择</a></div>');
          const modal=document.getElementById('content_defaultwarningAlert_id');modal.querySelector('p').textContent=arguments[0];
          document.getElementById('candidate').onclick=()=>modal.classList.remove('hidden');
          document.getElementById('qd_closeDefaultWarningWindowDialog_id').onclick=()=>{
            fixture.quietClicks=(fixture.quietClicks||0)+1;modal.classList.add('hidden');document.getElementById('form').classList.remove('hidden');};
        """, message)

    def test_quiet_car_advisory_is_automatically_confirmed_without_remembering(self):
        self.install_quiet_advisory()
        result = self.submit(PRIMARY)
        self.assertEqual(result.status, "pending_payment", result.reason)
        self.assertEqual(self.js("return fixture.quietClicks"), 1)
        self.assertFalse(self.js("return document.getElementById('remember').checked"))

    def test_changed_quiet_car_terms_or_controls_require_review_without_submitting(self):
        cases = ["document.querySelector('#content_defaultwarningAlert_id p').textContent+='其他条件。'",
                 "document.getElementById('qd_closeDefaultWarningWindowDialog_id').setAttribute('aria-disabled','true')",
                 "document.body.insertAdjacentHTML('beforeend','<div class=modal>另一个提示</div>')"]
        for change in cases:
            with self.subTest(change=change):
                self.setUp()
                self.install_quiet_advisory()
                self.js(change)
                result = self.submit(PRIMARY)
                self.assertEqual(result.status, "verification", result.reason)
                self.assertEqual(self.js("return [fixture.quietClicks||0,fixture.submitClicks]"), [0, 0])
                self.assertFalse(self.js("return document.getElementById('remember').checked"))


if __name__ == "__main__":
    unittest.main(verbosity=2, defaultTest="AlternateOptionsBrowserTests")
