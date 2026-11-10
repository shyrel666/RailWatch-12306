"""Public progress reconstructed from the original run, including order recovery."""
import json


def read_prefill_progress(journal, run_id):
    with journal.connection() as db:
        armed = db.execute("SELECT detail FROM order_events WHERE run_id=? AND stage='prefill_armed' ORDER BY sequence DESC LIMIT 1",
                           (run_id,)).fetchone()
        if not armed:
            return {}
        plan = json.loads(armed[0])
        events = list(db.execute(
            "SELECT stage,intent_id FROM order_events WHERE run_id=? AND stage IN "
            "('regular_confirm_dispatched','regular_auto_reconcile','prefill_fallback') ORDER BY sequence", (run_id,)))
        orders = list(db.execute(
            "SELECT intent,result FROM orders o WHERE o.run_id=? AND EXISTS "
            "(SELECT 1 FROM order_events e WHERE e.intent_id=o.intent_id AND e.stage='prefill_submit') ORDER BY updated_at",
            (run_id,)))
    # After a fallback the same run also confirms orders found by the regular
    # query; only intents entered through the pre-fill count as its submissions.
    prefill_ids = {json.loads(raw_intent)['intent_id'] for raw_intent, _ in orders}
    dispatched = {iid for stage, iid in events if stage == 'regular_confirm_dispatched' and iid in prefill_ids}
    recovering = {iid for stage, iid in events if stage == 'regular_auto_reconcile' and iid in prefill_ids}
    rows = [{**{key: item.get(key, '') for key in ('train', 'seat', 'from', 'to')},
             'date': plan.get('date', ''), 'status': 'armed', 'confirmed': False, 'bound': False}
            for item in plan.get('candidates', [])]
    for raw_intent, raw_result in orders:
        intent, result = json.loads(raw_intent), json.loads(raw_result)
        for item in rows:
            if (item['train'], item['seat'], item['from'], item['to'], item['date']) != (
                    intent['train_code'], intent['seat'], intent['from_station'], intent['to_station'], intent['date']):
                continue
            iid = intent['intent_id']
            status = result['status']
            if status == 'submitting' and iid in recovering:
                status = 'reconciling'
            item.update(status=status, confirmed=iid in dispatched, bound=bool(result.get('order_id')))
    return {'run_id': run_id, 'fallback': any(stage == 'prefill_fallback' for stage, _ in events),
            'submissions': len(dispatched), 'candidates': rows}
