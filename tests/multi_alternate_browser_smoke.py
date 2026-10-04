"""Offline Chrome checks for waitlist composition and isolated order observation."""
from dataclasses import replace
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from order_browser_smoke import OrderBrowserTests
from railwatch_order_page import OrderPage
from railwatch_orders import OrderResult
from railwatch_task import MonitorTask, TaskCancelled, guard_browser
from test_multi_alternate import PRIMARY, CONFIG, CHOICES


class MultiAlternateBrowserTests(unittest.TestCase):
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
        self.page = OrderPage(self.driver, allow_fixture=True, poll_interval=.01, wait=lambda _: None)
        self.bound = []
        self.page.bind_intent = self.bound.append

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def submit(self, config=None):
        return self.page.alternate(self.driver.find_element("id", "candidate"), PRIMARY, plan_config=config or CONFIG)

    def test_multi_date_set_is_read_back_persisted_then_submitted_once(self):
        stages = []
        self.page.mark = lambda stage, detail=None: stages.append(stage)
        def bound(intent):
            self.assertEqual(self.js("return fixture.submitClicks"), 0)
            self.bound.append(intent)
        self.page.bind_intent = bound
        result = self.submit()
        self.assertEqual(result.status, "pending_payment", result.reason)
        self.assertEqual(self.bound[0].choices, CHOICES)
        self.assertEqual(self.js("return fixture.submitClicks"), 1)
        self.assertEqual(stages.count("alternate_submit"), 1)
        self.assertEqual({c["train"] for c in self.js("return fixture.adds")}, {"G101", "G102"})
        self.assertEqual(self.js("return document.getElementById('contact_train').checked"), False)

    def test_single_mode_never_opens_editor(self):
        result = self.page.alternate(self.driver.find_element("id", "candidate"), PRIMARY)
        self.assertEqual(result.status, "pending_payment")
        self.assertEqual(self.js("return fixture.adds.length"), 0)
        self.assertFalse(self.bound)

    def test_collapsed_official_order_reads_full_detail_before_binding(self):
        self.js("fixture.collapsed=true")
        result = self.submit()
        self.assertEqual(result.status, "pending_payment", result.reason)
        self.assertEqual(result.order_id, "E123456")
        self.assertEqual(self.js("return fixture.detailClicks"), 1)
        self.assertEqual(self.js("return fixture.submitClicks"), 1)
        self.assertFalse(self.page.snapshot()["dialogs"])
        self.js("fixture.record('待兑现')")
        self.assertEqual(self.page.result(self.bound[0], known_id="E123456").status, "unknown")
        result = self.page.reconcile(self.bound[0], known_id="E123456")
        self.assertEqual(result.status, "active", result.reason)
        self.assertEqual(self.js("return fixture.detailClicks"), 2)

    def test_extra_official_detail_choice_is_not_accepted(self):
        self.js("fixture.collapsed=true;fixture.detailTransform=choices=>[...choices,{...choices[0],train:'G999'}]")
        result = self.submit()
        self.assertEqual(result.status, "verification", result.reason)
        self.assertEqual(self.js("return fixture.submitClicks"), 1)
        self.assertEqual(self.js("return fixture.detailClicks"), 1)
        self.assertFalse(self.page.snapshot()["dialogs"])

    def test_detail_is_scoped_to_bound_order_and_rechecks_passengers_after_closing(self):
        self.js("fixture.collapsed=true")
        self.assertEqual(self.submit().status, "pending_payment")
        self.assertEqual(self.page.reconcile(self.bound[0], known_id="OTHER").status, "unknown")
        self.assertEqual(self.js("return fixture.detailClicks"), 1)
        self.js("fixture.onDetailsClose=()=>document.querySelector('.passenger-name strong').setAttribute('title','其他乘客')")
        result = self.page.reconcile(self.bound[0], known_id="E123456")
        self.assertEqual(result.status, "verification", result.reason)

    def test_existing_unrelated_dialog_is_never_replaced_by_order_detail(self):
        self.js("fixture.collapsed=true")
        self.assertEqual(self.submit().status, "pending_payment")
        self.js("document.body.insertAdjacentHTML('beforeend','<div class=modal>请人工核验</div>')")
        result = self.page.reconcile(self.bound[0], known_id="E123456")
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.detailClicks"), 1)

    def test_extra_choice_injected_during_selection_prevents_final_submit(self):
        self.js("fixture.onAdd=()=>{fixture.onAdd=null;fixture.draft.push({...primary,train:'G999'});}")
        result = self.submit()
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.submitClicks"), 0)
        self.assertFalse(self.bound)

    def test_changed_pair_before_final_readback_is_rejected(self):
        original = self.page.prepare_people
        def people(intent):
            result = original(intent)
            self.js("fixture.selected[1].seat='一等座'")
            return result
        self.page.prepare_people = people
        result = self.submit()
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_persistence_failure_never_reaches_submit(self):
        self.page.bind_intent = Mock(side_effect=OSError("disk unavailable"))
        result = self.submit()
        self.assertIn(result.status, ("verification", "unknown"))
        self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_unknown_or_wrong_date_evidence_cannot_be_selected(self):
        self.js("const old=render;render=()=>{old();document.querySelectorAll('.hbbtn').forEach(e=>e.dataset.info=e.dataset.info.replace('fixture-flags','2026-10-12#fixture-flags'));};")
        result = self.submit()
        self.assertEqual(result.status, "verification")
        self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_three_dates_can_be_verified_when_add_more_control_disappears(self):
        result = self.submit({**CONFIG, "alternate_max_combinations": 6})
        self.assertEqual(result.status, "pending_payment", result.reason)
        self.assertEqual(len(self.bound[0].choices), 6)
        self.assertEqual(len({choice.date for choice in self.bound[0].choices}), 3)
        self.assertEqual(self.js("return fixture.submitClicks"), 1)

    def test_changed_date_without_fresh_rows_is_not_accepted(self):
        from railwatch_alternate_editor import AlternateEditor
        self.driver.find_element("id", "candidate").click()
        editor = AlternateEditor(self.page, CONFIG)
        editor.open()
        self.js("document.querySelectorAll('.date-item').forEach(e=>e.onclick=()=>{document.querySelector('.date-item.is-active').classList.remove('is-active');e.classList.add('is-active');});")
        original_poll = self.page.poll
        self.page.poll = lambda predicate, *args: original_poll(predicate, .05)
        with self.assertRaisesRegex(ValueError, "日期切换"):
            editor.select_date("2026-10-09")
        self.assertEqual(self.js("return fixture.adds.length"), 0)

    def test_preexisting_alternatives_are_not_adopted(self):
        self.js("document.getElementById('planList').innerHTML='<div class=\"list-item\">未核对组合</div>'")
        result = self.submit()
        self.assertEqual(result.status, "verification")
        self.assertFalse(self.bound)

    def test_cancel_during_composition_keeps_submit_untouched(self):
        self.page.stop = lambda: bool(self.js("return fixture.adds.length"))
        result = self.submit()
        self.assertEqual(result.status, "not_submitted")
        self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_matching_order_and_fulfilled_winner_keep_original_identity(self):
        self.assertEqual(self.submit().status, "pending_payment")
        intent = self.bound[0]
        self.js("fixture.record('已兑现',[fixture.selected[1]])")
        result = self.page.result(intent, submitted=True, known_id="E123456")
        self.assertEqual(result.status, "fulfilled")
        self.assertEqual(len(result.evidence["fulfilled_choices"]), 1)
        self.assertEqual(self.page.result(intent, known_id="OTHER").status, "unknown")

    def test_probe_preserves_payment_page_and_never_clicks_submit(self):
        original_handle, original_url = self.driver.current_window_handle, self.driver.current_url
        def reconcile(intent, **kwargs):
            self.assertNotEqual(self.driver.current_window_handle, original_handle)
            self.assertEqual(kwargs, {"known_id": "E123456", "navigate": True})
            return OrderResult("active", order_id="E123456", evidence={"matched": True})
        self.page.reconcile = reconcile
        self.assertEqual(self.page.probe_known_order(PRIMARY, "E123456").status, "active")
        self.assertEqual(self.driver.window_handles, [original_handle])
        self.assertEqual(self.driver.current_url, original_url)
        self.assertEqual(self.js("return fixture.submitClicks"), 0)

    def test_cancelled_probe_closes_only_its_own_tab_under_browser_guard(self):
        task = MonitorTask(CONFIG)
        self.page.stop = task.cancel.is_set
        original_handle = self.driver.current_window_handle
        def cancel(*args, **kwargs):
            task.cancel.set()
            self.driver.title  # Guard unwinds the in-flight read.
        self.page.reconcile = cancel
        with guard_browser(self.driver, task, lambda: None):
            with self.assertRaises(TaskCancelled):
                self.page.probe_known_order(PRIMARY, "E123456")
        self.assertEqual(self.driver.window_handles, [original_handle])
        self.assertEqual(self.driver.current_window_handle, original_handle)


if __name__ == "__main__":
    unittest.main(verbosity=2, defaultTest="MultiAlternateBrowserTests")
