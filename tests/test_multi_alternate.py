"""Persisted, bounded waitlist sets and exact official record matching."""
from dataclasses import asdict, replace
import tempfile
import unittest
from unittest.mock import Mock

from railwatch_alternate_plan import AlternateChoice, AlternatePlan
from railwatch_config_contract import validate_config
from railwatch_order_page import OrderPage, record_matches
from railwatch_orders import OrderIntent, OrderJournal, OrderResult


PRIMARY = OrderIntent("alternate", "G101", "2026-10-10", "北京", "上海", "二等座", ("张三",), "18:00")
CONFIG = {"date": "2026-10-10", "date_range": "±1天", "train_code": "G101,G102", "seat_keyword": "二等座",
          "alternate_mode": "multiple", "alternate_max_combinations": 3,
          "order_watch_enabled": True, "order_watch_interval_seconds": 60}
CHOICES = (AlternateChoice.from_intent(PRIMARY), AlternateChoice("G102", "2026-10-10", "北京", "上海", "二等座"),
           AlternateChoice("G101", "2026-10-09", "北京", "上海", "二等座"))


def record(choices=CHOICES, state="待兑现", order="E1"):
    return {"kind": "alternate", "order_id": order, "state": state, "passengers": ["张三"],
            "choices": [{"train": c.train_code, "date": c.date, "from": c.from_station, "to": c.to_station, "seat": c.seat} for c in choices]}


class MultiAlternateTests(unittest.TestCase):
    def test_editor_respects_query_mode_floor_and_saved_interval(self):
        from railwatch_alternate_editor import AlternateEditor
        self.assertEqual(AlternateEditor(Mock(), {"request_mode": "conservative", "interval": 1}).interval, 5)
        self.assertEqual(AlternateEditor(Mock(), {"request_mode": "fast", "interval": 10}).interval, 10)

    def test_monitor_freezes_original_dates_and_uses_bound_intent_for_result(self):
        from gui_12306_0 import TicketMonitor
        for focus, fallback in ((False, False), (True, False), (False, True)):
            with self.subTest(focus=focus, fallback=fallback), tempfile.TemporaryDirectory() as directory:
                journal = OrderJournal(directory + "/orders.sqlite3")
                events = []
                monitor = TicketMonitor(Mock(), {**CONFIG, "from_station_cn": "北京", "to_station_cn": "上海",
                    "passengers": "张三", "auto_alternate": True}, order_journal=journal, run_id="multi",
                    on_order=lambda intent, result: events.append((intent, result)), log_callback=lambda _: None)
                monitor.cfg["date"] = "2026-10-09"  # Simulate the current query, keeping the original date window.
                monitor._sale_focus_active = lambda: focus
                monitor._prefer_alternate = fallback
                monitor.row_parser.selected_route = Mock(return_value=("北京", "上海"))
                def submit(row, train, seat, *, intent):
                    saved = journal.pending()["config"]
                    expected = [intent.date] if focus or fallback else ["2026-10-09", "2026-10-10", "2026-10-11"]
                    self.assertEqual(saved["_alternate_dates"], expected)
                    first = AlternateChoice.from_intent(intent)
                    monitor.order_page.bind_intent(replace(intent, choices=(first, replace(first, train_code="G102"))))
                    monitor._mark("alternate_submit")
                    return OrderResult("pending_payment", order_id="E1", evidence={"matched": True})
                monitor.alternate_flow.try_alternate_order = submit
                self.assertTrue(monitor._execute_order(("G101", "二等座", "候补", Mock(), Mock(), "alternate")))
                stored = OrderIntent.from_dict(journal.pending()["intent"])
                self.assertEqual(len(stored.choices), 2)
                self.assertEqual(events[-1][0], stored)
                self.assertEqual(events[-1][1].status, "pending_payment")

    def test_plan_bounds_and_authorized_scope(self):
        plan = AlternatePlan(PRIMARY, CONFIG)
        self.assertTrue(plan.validate(CHOICES))
        for changed in (replace(CHOICES[1], train_code="G999"), replace(CHOICES[1], seat="一等座"),
                        replace(CHOICES[1], date="2026-10-12"), replace(CHOICES[1], from_station="北京南")):
            self.assertFalse(plan.validate((CHOICES[0], changed)))
        self.assertFalse(plan.validate((CHOICES[0], CHOICES[0])))
        self.assertEqual(AlternatePlan(PRIMARY, {**CONFIG, "_alternate_dates": [PRIMARY.date]}).dates, [PRIMARY.date])

    def test_config_defaults_validation_and_roundtrip(self):
        from gui_12306_0 import QueryConfig
        from railwatch_bridge import RailWatchBridge
        self.assertEqual(validate_config({})["alternate_mode"], "single")
        for value in ({"alternate_mode": "all"}, {"alternate_max_combinations": 61},
                      {"alternate_max_combinations": True}, {"order_watch_interval_seconds": 29},
                      {"order_watch_interval_seconds": float("inf")}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config(value)
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            try:
                bridge.save_config(CONFIG)
                restored = bridge.load_config()
                core = QueryConfig.from_dict(restored).to_dict()
                for key in ("alternate_mode", "alternate_max_combinations", "order_watch_enabled", "order_watch_interval_seconds"):
                    self.assertEqual(core[key], CONFIG[key])
                    self.assertEqual(restored["query_jobs"][0][key], CONFIG[key])
            finally:
                bridge.notification_service.close()

    def test_binding_survives_restart_and_cannot_change_after_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            journal.begin("run", PRIMARY, CONFIG)
            intent = replace(PRIMARY, choices=CHOICES)
            journal.bind_alternatives(intent)
            restored = OrderJournal(journal.filename)
            self.assertEqual(OrderIntent.from_dict(restored.pending()["intent"]), intent)
            journal.mark("run", "alternate_submit", PRIMARY.intent_id)
            with self.assertRaises(RuntimeError):
                restored.bind_alternatives(replace(intent, choices=CHOICES[:2]))
            with self.assertRaises(ValueError):
                journal.record(PRIMARY, OrderResult("pending_payment", order_id="E1", evidence={"matched": True}))
            journal.record(intent, OrderResult("pending_payment", order_id="E1", evidence={"matched": True}))
            self.assertEqual(len(journal.history_detail(intent.intent_id)["summary"]["choices"]), 3)

    def test_binding_rejects_unconfigured_or_repeated_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/orders.sqlite3")
            journal.begin("run", PRIMARY, CONFIG)
            with self.assertRaises(ValueError):
                journal.bind_alternatives(replace(PRIMARY, choices=(CHOICES[0], replace(CHOICES[1], seat="一等座"))))
            with self.assertRaises(ValueError):
                replace(PRIMARY, choices=(CHOICES[0], CHOICES[0]))
            self.assertFalse(journal.pending()["intent"]["choices"])

    def test_exact_pair_matching_not_independent_train_date_sets(self):
        intent = replace(PRIMARY, choices=CHOICES)
        self.assertTrue(record_matches(record(), intent))
        wrong = (CHOICES[0], replace(CHOICES[1], date="2026-10-09"), replace(CHOICES[2], date="2026-10-10"))
        self.assertFalse(record_matches(record(wrong), intent))
        for values in (CHOICES[:2], (*CHOICES, replace(CHOICES[2], train_code="G999")), (*CHOICES, CHOICES[0])):
            self.assertFalse(record_matches(record(values), intent))
        self.assertFalse(record_matches({**record(), "passengers": ["张三", "李四"]}, intent))

    def test_fulfilled_subset_requires_bound_id_and_exact_winner(self):
        intent = replace(PRIMARY, choices=CHOICES)
        self.assertTrue(record_matches(record(CHOICES[1:2], "已兑现"), intent, known_id="E1"))
        self.assertFalse(record_matches(record(CHOICES[1:2], "已兑现"), intent))
        self.assertFalse(record_matches(record(CHOICES[1:2], "待兑现"), intent, known_id="E1"))
        self.assertFalse(record_matches(record(CHOICES[1:2], "已兑现", "E2"), intent, known_id="E1"))
        self.assertFalse(record_matches(record((replace(CHOICES[1], seat="一等座"),), "已兑现"), intent, known_id="E1"))

    def test_legacy_single_intent_loads_without_choices(self):
        value = asdict(PRIMARY)
        value.pop("choices")
        self.assertEqual(OrderIntent.from_dict(value).combinations, CHOICES[:1])


if __name__ == "__main__":
    unittest.main()
