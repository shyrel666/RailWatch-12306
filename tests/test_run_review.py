import json
import tempfile
import unittest
from railwatch_orders import OrderJournal
from railwatch_run_review import build_run_review, build_prediction, duration


def event(sequence, stage, at, detail=None):
    return {"sequence": sequence, "run_id": "test-run", "stage": stage, "at": 1000 + at,
            "monotonic": 500 + at, "detail": detail or {}}


class RunReviewTests(unittest.TestCase):
    def test_order_breakdown_is_separate_from_totals_and_legacy_records_stay_empty(self):
        before = [event(1, "inventory_found", 0), event(2, "regular_submit", 7)]
        legacy = build_run_review(before)
        steps = [{"id": "page_load", "start_ms": 0, "duration_ms": 6000},
                 {"id": "passengers", "start_ms": 6000, "duration_ms": 1000}]
        review = build_run_review(before + [event(3, "order_timing", 8, {"kind": "regular", "steps": steps})])
        self.assertEqual(review["segments"], legacy["segments"])
        self.assertEqual(review["conclusion"], legacy["conclusion"])
        self.assertEqual(legacy["order_timings"], [])
        self.assertEqual(review["order_timings"][0]["segments"][0]["label"], "打开并等待下单页")
        self.assertEqual(sum(s["duration_ms"] for s in review["order_timings"][0]["segments"]), 7000)

    def test_separate_attempts_and_invalid_order_timing_values(self):
        valid = {"id": "page_load", "start_ms": 0, "duration_ms": 1000}
        invalid = [None, {}, {**valid, "id": "private"}, {**valid, "duration_ms": float("nan")},
                   {**valid, "start_ms": -1}, {**valid, "duration_ms": True}]
        events = [event(1, "order_timing", 1, {"kind": "regular", "steps": invalid + [valid]}),
                  event(2, "order_timing", 2, {"kind": "alternate", "steps": [valid]})]
        groups = build_run_review(events)["order_timings"]
        self.assertEqual([group["kind"] for group in groups], ["regular", "alternate"])
        self.assertEqual([len(group["segments"]) for group in groups], [1, 1])

    def test_regular_segments_and_missing_evidence(self):
        events = [event(1, "target_sale", 0, {"target_at": 1020}), event(2, "prepared", 1),
                  event(3, "scheduler_wake", 20.01, {"late_ms": 10}), event(4, "query_click", 20.02),
                  event(5, "query_result", 21), event(6, "inventory_found", 21.1), event(7, "regular_submit", 22),
                  event(8, "regular_confirm_dispatched", 23), event(9, "order_result", 25, {"official": True, "status": "pending_payment"})]
        review = build_run_review(events)
        values = {s["id"]: s["duration_ms"] for s in review["segments"]}
        self.assertEqual(values["query"], 980)
        self.assertEqual(values["decision"], 100)
        self.assertEqual(review["preparation_margin_ms"], 19000)
        self.assertEqual(review["slowest"], "官方处理")
        self.assertEqual(review["conclusion"], "待支付")
        self.assertFalse(build_run_review(events[:3])["history_complete"])
        self.assertIsNone(duration(events[0], {**events[1], "monotonic": 1}))

    def test_alternate_and_prediction_sources(self):
        review = build_run_review([event(1, "target_sale", 0), event(2, "no_inventory", 1),
                                  event(3, "alternate_first_action", 2), event(4, "alternate_submit", 3),
                                  event(5, "order_result", 4, {"official": True, "status": "active"})])
        self.assertEqual(review["conclusion"], "候补已生效")
        self.assertEqual(next(s for s in review["segments"] if s["id"] == "alternate_submit")["duration_ms"], 1000)
        history = [{"segments": [{"id": "confirm", "duration_ms": 10}]}, {"segments": [{"id": "confirm", "duration_ms": 30}]}]
        segments = {s["id"]: s for s in build_prediction({"measurements": {"query_round_trip_ms": 100, "drill_ms": {"readback": 30}}}, history)}
        self.assertEqual(segments["query"]["source"], "本机实测")
        self.assertEqual(segments["confirm"]["duration_ms"], 20)
        self.assertIn("不含官方", segments["readback"]["source"])
        self.assertIsNone(segments["official"]["duration_ms"])

    def test_bounded_query_readout_and_run_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/db.sqlite3", telemetry_batch_size=1000)
            journal.mark("test-run", "target_sale", detail={"target_at": 0})
            journal.mark("test-run", "scheduler_wake")
            for _ in range(50):
                journal.record_telemetry("test-run", "query_click")
                journal.record_telemetry("test-run", "query_result")
            journal.mark("test-run", "inventory_found")
            events = journal.run_events("test-run")
            self.assertEqual(sum(e["stage"] == "query_click" for e in events), 10)
            self.assertEqual(sum(e["stage"] == "query_result" for e in events), 10)
            journal.mark("new-run", "target_sale")
            first = journal.recent_runs(1)
            self.assertEqual(first["items"][0]["run_id"], "new-run")
            self.assertEqual(journal.recent_runs(1, first["next_cursor"])["items"][0]["run_id"], "test-run")
            with self.assertRaises(ValueError):
                journal.run_events("invalid/'id")

    def test_prediction_uses_only_regular_drill_readback(self):
        measurements = {"drill_ms": {"regular_readback": 40, "alternate_readback": 900}}
        segments = {s["id"]: s for s in build_prediction({"measurements": measurements}, [])}
        self.assertEqual(segments["readback"]["duration_ms"], 40)

    def test_list_conclusions_match_full_reviews(self):
        from railwatch_run_review import run_conclusion
        from railwatch_bridge import RailWatchBridge
        cases = {"placed": [("inventory_found", None), ("order_result", {"official": True, "status": "pending_payment"}), ("pending_payment", None)],
                 "queued": [("no_inventory", None), ("alternate_first_action", None),
                            ("order_result", {"official": True, "status": "pending_payment"})],
                 "stopped": [("inventory_found", None), ("order_result", {"official": False, "status": "pending_payment"})],
                 "missed": [],
                 "verification": [("inventory_found", None), ("verification", None), ("dismissed", None)],
                 "unknown": [("regular_confirm_dispatched", None), ("unknown", None), ("dismissed", None)],
                 "stopped_task": [("task_finished", {"status": "stopped"})],
                 "error_task": [("task_finished", {"status": "error"})],
                 "hit_task": [("task_finished", {"status": "hit"})]}
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            journal = bridge.order_journal
            for run_id, stages in cases.items():
                journal.mark(run_id, "target_sale", detail={"target_at": None})
                journal.record_telemetry(run_id, "query_click")
                for stage, detail in stages:
                    journal.mark(run_id, stage, detail=detail)
            listed = {item["run_id"]: item["conclusion"] for item in bridge.run_reviews(10)["items"]}
            self.assertEqual(listed, {run_id: bridge.run_review(run_id)["conclusion"] for run_id in cases})
            self.assertEqual(listed, {"placed": "待支付", "queued": "候补待支付", "stopped": "结果待核对", "missed": "记录不完整",
                                      "verification": "需要核验", "unknown": "结果待核对", "stopped_task": "已停止",
                                      "error_task": "运行异常", "hit_task": "已命中"})
            self.assertEqual(run_conclusion([]), "记录不完整")
            with journal.connection() as db:
                plan = " ".join(row[3] for row in db.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM order_events WHERE run_id=? AND stage NOT IN ('query_click','query_result') ORDER BY sequence", ("placed",)))
            self.assertIn("order_events_run_markers", plan)
            bridge.notification_service.close()

    def test_latest_evidence_wins_without_guessing_success_or_failure(self):
        from railwatch_run_review import run_conclusion
        cases = [
            ([("order_result", {"status": "verification"}), ("dismissed", {})], "需要核验"),
            ([("order_result", {"status": "unknown"}), ("task_finished", {"status": "stopped"})], "结果待核对"),
            ([("order_result", {"status": "pending_payment", "official": True}),
              ("order_result", {"status": "cancelled", "official": True})], "订单已取消"),
            ([("verification", {}), ("order_result", {"status": "fulfilled", "official": True})], "购票成功"),
            ([("confirmed_failure", {}), ("alternate_submit", {})], "结果待核对"),
            ([("inventory_found", {})], "记录不完整"),
            ([("query_result", {})], "记录不完整"),
            ([("order_result", {"status": "sold_out"})], "已确认售罄"),
        ]
        for stages, expected in cases:
            with self.subTest(stages=stages):
                self.assertEqual(run_conclusion([event(i, stage, i, detail) for i, (stage, detail) in enumerate(stages, 1)]), expected)

    def test_finished_task_records_the_reason_for_list_and_detail(self):
        from railwatch_bridge import RailWatchBridge
        from railwatch_task import MonitorTask
        with tempfile.TemporaryDirectory() as directory:
            bridge = RailWatchBridge(directory)
            try:
                for terminal, expected in (("stopping", "已停止"), ("error", "运行异常"), ("hit", "已命中")):
                    task = MonitorTask({}, status=terminal)
                    bridge._task = task
                    bridge.order_journal.mark(task.run_id, "target_sale", detail={"target_at": None})
                    bridge._finish_task(task)
                    self.assertEqual(bridge.run_review(task.run_id)["conclusion"], expected)
                    self.assertEqual(bridge.run_reviews(1)["items"][0]["conclusion"], expected)
            finally:
                bridge.notification_service.close()

    def test_query_pair_does_not_cross_a_new_click(self):
        review = build_run_review([event(1, "target_sale", 0), event(2, "query_click", 1),
                                  event(3, "query_click", 10), event(4, "query_result", 11)])
        self.assertEqual(next(s for s in review["segments"] if s["id"] == "query")["duration_ms"], 1000)

    def test_pruned_first_round_is_unknown_and_later_hit_keeps_its_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = OrderJournal(directory + "/db.sqlite3")
            journal.mark("test-run", "target_sale", detail={"target_at": 1})
            journal.mark("test-run", "scheduler_wake", detail={"late_ms": 1})
            for _ in range(3):
                journal.record_telemetry("test-run", "query_click")
                journal.record_telemetry("test-run", "query_result")
            journal.flush_telemetry()
            with journal.connection() as db:
                db.execute("DELETE FROM order_events WHERE sequence IN (3,4)")
            review = build_run_review(journal.run_events("test-run"))
            stages = {s["id"]: s for s in review["segments"]}
            self.assertIsNone(stages["first_query"]["duration_ms"])
            self.assertIsNone(review["query_median_ms"])
            self.assertGreater(stages["query"]["start_ms"], 0)
