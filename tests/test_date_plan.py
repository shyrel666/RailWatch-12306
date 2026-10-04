"""Multi-date decisions use fresh queries and preserve transaction boundaries."""
import tempfile
import unittest
from unittest.mock import Mock, patch

from gui_12306_0 import QueryConfig, TicketMonitor
from railwatch_config_contract import validate_config
from railwatch_date_plan import DatePlan
from railwatch_bridge import RailWatchBridge


DATES = ["2026-10-09", "2026-10-10", "2026-10-11"]
CONFIG = {"date": DATES[1], "date_range": "±1天", "date_strategy": "inventory_first",
          "date_scan_budget_seconds": 30, "from_station_cn": "北京", "to_station_cn": "上海",
          "train_code": "G101", "seat_keyword": "二等座", "passengers": "测试乘客",
          "auto_submit": True, "auto_alternate": True}


class DatePlanTests(unittest.TestCase):
    def test_legacy_order_and_selected_date_order(self):
        for strategy, expected in (("round_robin", DATES),
                                   ("preferred_date", [DATES[1], DATES[0], DATES[2]])):
            plan = DatePlan(DATES[1], strategy)
            plan.sync(DATES)
            self.assertEqual([plan.select(i, i) for i in range(1, 7)], expected * 2)
            self.assertTrue(plan.allow_alternate(expected[0], True, 6))

    def test_preferred_date_starts_first_even_after_a_sale_window(self):
        plan = DatePlan(DATES[1], "preferred_date")
        plan.sync(DATES)
        self.assertEqual(plan.select(20, 50), DATES[1])

    def test_budget_selects_a_date_but_does_not_keep_a_browser_candidate(self):
        plan = DatePlan(DATES[1], "inventory_first", 10)
        plan.sync(DATES)
        self.assertEqual(plan.select(1, 0), DATES[1])
        self.assertFalse(plan.allow_alternate(DATES[1], True, 1))
        self.assertEqual(plan.select(2, 11), DATES[1])
        self.assertFalse(plan.allow_alternate(DATES[1], False, 12))
        self.assertFalse(plan.offers)
        self.assertIsNone(plan.recheck)

    def test_changed_date_window_clears_old_waitlist_evidence(self):
        plan = DatePlan(DATES[1], "inventory_first", 10)
        plan.sync(DATES)
        plan.select(1, 0)
        plan.allow_alternate(DATES[1], True, 1)
        plan.sync([DATES[2]])
        self.assertEqual(plan.select(8, 15), DATES[2])
        self.assertFalse(plan.offers)

    def test_complete_scan_can_use_the_current_fresh_candidate(self):
        plan = DatePlan(DATES[1], "inventory_first")
        plan.sync(DATES)
        for loop, candidate in enumerate((False, False, True), 1):
            travel_date = plan.select(loop, loop)
            self.assertEqual(plan.allow_alternate(travel_date, candidate, loop), loop == 3)

    def test_policy_and_budget_survive_bridge_and_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            try:
                bridge.save_config(CONFIG)
                restored = bridge.load_config()
                self.assertEqual(restored["date_strategy"], "inventory_first")
                self.assertEqual(restored["date_scan_budget_seconds"], 30)
                self.assertEqual(restored["query_jobs"][0]["date_strategy"], "inventory_first")
                core = QueryConfig.from_dict(restored).to_dict()
                self.assertEqual(core["date_strategy"], "inventory_first")
                self.assertEqual(core["date_scan_budget_seconds"], 30)
            finally:
                bridge.notification_service.close()

    def test_old_configs_keep_existing_order_and_bad_policies_are_rejected(self):
        self.assertEqual(validate_config({})["date_strategy"], "round_robin")
        for patch_config in ({"date_strategy": "unknown"}, {"date_scan_budget_seconds": float("nan")},
                             {"date_scan_budget_seconds": 0}, {"date_scan_budget_seconds": 121}):
            with self.subTest(config=patch_config), self.assertRaises(ValueError):
                validate_config(patch_config)


class MonitorDateDecisionTests(unittest.TestCase):
    def setUp(self):
        self.clock = 100.0
        clock = patch("gui_12306_0.time.monotonic", lambda: self.clock)
        clock.start()
        self.addCleanup(clock.stop)
        self.monitor = TicketMonitor(Mock(), CONFIG, log_callback=lambda _: None)
        self.monitor.query_executor = Mock()
        self.monitor.query_executor.current.return_value = True
        self.monitor.query_executor.execute.return_value = {"status": "ok"}
        self.monitor._fill_query_params = Mock(return_value=True)
        self.monitor.row_parser.snapshot_rows = Mock(return_value=[])
        self.monitor._execute_order = Mock(return_value=True)
        self.monitor._sleep = Mock()
        self.actions = {}
        self.monitor._scan_current_rows = self.hit

    def hit(self):
        action = self.actions.get(self.monitor.cfg["date"])
        return ("G101", "二等座", "候补" if action == "alternate" else "有", Mock(), Mock(), action) if action else None

    def loop(self, number):
        self.clock += 3
        return self.monitor._run_single_loop(number, 3)

    def test_later_date_cash_inventory_wins_over_first_date_waitlist(self):
        self.actions = {DATES[1]: "alternate", DATES[0]: "book"}
        self.assertFalse(self.loop(1))
        self.monitor._execute_order.assert_not_called()
        self.assertTrue(self.loop(2))
        self.assertEqual(self.monitor.cfg["date"], DATES[0])
        self.assertEqual(self.monitor._execute_order.call_args.args[0][-1], "book")

    def test_waitlist_is_requeried_after_all_dates_and_disappearance_is_respected(self):
        self.actions = {DATES[1]: "alternate"}
        for number in range(1, 4):
            self.assertFalse(self.loop(number))
        self.actions.clear()
        self.assertFalse(self.loop(4))
        self.assertEqual(self.monitor.cfg["date"], DATES[1])
        self.monitor._execute_order.assert_not_called()

    def test_new_cash_on_recheck_still_wins(self):
        self.actions = {DATES[1]: "alternate"}
        for number in range(1, 4):
            self.loop(number)
        self.actions[DATES[1]] = "book"
        self.assertTrue(self.loop(4))
        self.assertEqual(self.monitor._execute_order.call_args.args[0][-1], "book")

    def test_failed_query_does_not_count_as_no_inventory(self):
        self.actions = {DATES[1]: "alternate"}
        self.loop(1)
        self.monitor.query_executor.execute.return_value = {"status": "timeout"}
        self.loop(2)
        self.assertNotIn(DATES[0], self.monitor.date_plan.checked)
        self.monitor.query_executor.execute.return_value = {"status": "ok"}
        self.loop(3)
        self.monitor._execute_order.assert_not_called()
        self.assertIsNone(self.monitor.date_plan.recheck)

    def test_server_wait_is_preserved_even_after_scan_budget(self):
        self.actions = {DATES[1]: "alternate"}
        self.loop(1)
        self.clock += 31
        self.monitor.query_executor.execute.return_value = {"status": "server_backoff", "retry_after_seconds": 120}
        self.assertFalse(self.loop(2))
        self.monitor._sleep.assert_called_with(120)
        self.monitor._execute_order.assert_not_called()

    def test_timed_focus_and_proven_sold_out_fallback_keep_original_date(self):
        self.monitor.cfg.update(timer_enabled=True, _target_timestamp=1000)
        self.monitor.server_time_sync = Mock()
        self.monitor.server_time_sync.server_timestamp.return_value = 1000
        self.actions = {DATES[1]: "alternate"}
        self.assertTrue(self.loop(1))
        self.assertEqual(self.monitor.cfg["date"], DATES[1])
        self.monitor.cfg["timer_enabled"] = False
        self.monitor._prefer_alternate, self.monitor._fallback_date = True, DATES[2]
        self.actions = {DATES[2]: "alternate"}
        self.assertTrue(self.loop(2))
        self.assertEqual(self.monitor.cfg["date"], DATES[2])
