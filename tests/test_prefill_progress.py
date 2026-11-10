"""Prefill progress must survive recovery and never invent ticket query evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from railwatch_bridge import RailWatchBridge, state_to_payload
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from railwatch_prefill_progress import read_prefill_progress


class PrefillProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = OrderJournal(Path(self.tmp.name) / 'orders.sqlite3')
        self.intent = OrderIntent('regular', 'G8843', '2026-11-22', '大兴机场', '天津西', '二等座', ('测试乘客',))
        self.journal.mark('original', 'prefill_armed', detail={'date': '2026-11-22', 'candidates': [
            {'train': 'G8843', 'from': '大兴机场', 'to': '天津西', 'seat': '二等座'}]})

    def submit(self):
        self.journal.begin('original', self.intent, {})
        for stage in ('prefill_submit', 'regular_submit', 'regular_confirm_attempt', 'regular_confirm_dispatched'):
            self.journal.mark('original', stage, self.intent.intent_id)

    def test_armed_is_zero_submissions_and_does_not_report_inventory(self):
        p = read_prefill_progress(self.journal, 'original')
        self.assertEqual(p['submissions'], 0)
        self.assertEqual(p['candidates'][0]['status'], 'armed')
        self.assertEqual(read_prefill_progress(self.journal, 'another-run'), {})

    def test_recovery_and_restart_restore_original_progress_without_private_data(self):
        self.submit()
        self.journal.mark('original', 'regular_auto_reconcile', self.intent.intent_id)
        p = read_prefill_progress(self.journal, 'original')
        self.assertEqual((p['submissions'], p['candidates'][0]['status']), (1, 'reconciling'))
        result = OrderResult('pending_payment', order_id='PRIVATE-ORDER', evidence={'matched': True})
        self.journal.record(self.intent, result)
        bridge = RailWatchBridge(self.tmp.name)
        self.addCleanup(bridge.notification_service.close)
        p = state_to_payload(bridge.state)['prefill']
        self.assertEqual(p['run_id'], 'original')
        self.assertEqual(p['submissions'], 1)
        self.assertEqual(p['candidates'][0]['status'], 'pending_payment')
        self.assertTrue(p['candidates'][0]['bound'])
        self.assertEqual(bridge.state.hits, ())
        self.assertEqual(bridge.query_results, [])
        encoded = json.dumps(p, ensure_ascii=False)
        self.assertNotIn('PRIVATE-ORDER', encoded)
        self.assertNotIn('测试乘客', encoded)

    def test_rejected_entry_and_fallback_keep_zero_confirmations(self):
        self.journal.begin('original', self.intent, {})
        self.journal.mark('original', 'prefill_submit', self.intent.intent_id)
        self.journal.mark('original', 'prefill_official_rejected', self.intent.intent_id)
        self.journal.record(self.intent, OrderResult('sold_out', no_order=True))
        self.journal.mark('original', 'prefill_fallback', detail={'stage': 'sold_out_all'})
        p = read_prefill_progress(self.journal, 'original')
        self.assertTrue(p['fallback'])
        self.assertEqual(p['submissions'], 0)
        self.assertEqual(p['candidates'][0]['status'], 'sold_out')

    def test_regular_order_after_fallback_is_not_counted_as_a_prefill_submission(self):
        self.journal.mark('original', 'prefill_fallback', detail={'stage': 'unlock_timeout'})
        regular = OrderIntent('regular', 'G8845', '2026-11-22', '大兴机场', '天津西', '一等座', ('测试乘客',))
        self.journal.begin('original', regular, {}, 'inventory_found')
        for stage in ('regular_submit', 'regular_confirm_attempt', 'regular_confirm_dispatched'):
            self.journal.mark('original', stage, regular.intent_id)
        p = read_prefill_progress(self.journal, 'original')
        self.assertTrue(p['fallback'])
        self.assertEqual(p['submissions'], 0)
        self.assertEqual(p['candidates'][0]['status'], 'armed')
