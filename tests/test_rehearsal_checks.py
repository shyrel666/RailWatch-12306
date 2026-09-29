import datetime as dt
import json
from pathlib import Path
import unittest
from railwatch_config_contract import automation_config_issue
from railwatch_sale_times import official_sale_at
from railwatch_rehearsal_checks import check_passengers, check_train_seat, check_clock, check_scheduler, check_sale_time, check_alerts


class RehearsalChecksTests(unittest.TestCase):
    def test_shared_automation_cases(self):
        cases = json.loads((Path(__file__).parent / "fixtures/automation-readiness-cases.json").read_text(encoding="utf-8"))
        for patch in cases["valid"]:
            self.assertIsNone(automation_config_issue({**cases["base"], **patch}))
        for case in cases["invalid"]:
            self.assertIn(case["expected"], automation_config_issue({**cases["base"], **case["patch"]}))

    def test_shared_sale_cases(self):
        cases = json.loads((Path(__file__).parent / "fixtures/sale-time-cases.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                value = official_sale_at(case["station"], case["date"], dt.datetime.fromisoformat(case["now"]),
                                         case["window_days"], info=case["info"])
                self.assertEqual(value.isoformat() if value else None, case["expected"])

    def test_passenger_evidence_and_privacy(self):
        config = {"passengers": "测试甲", "auto_submit": True}
        person = {"name": "测试甲", "ticket_type": "adult", "verification": "passed"}
        for patch, expected in [({}, "pass"), ({"ticket_type": "student"}, "fail"),
                                 ({"ticket_type": "child"}, "fail"), ({"verification": "failed"}, "fail"),
                                 ({"verification": "prepassed"}, "warn"), ({"verification": "pending"}, "warn"),
                                 ({"ticket_type": "unknown"}, "warn"), ({"unsupported_ticket_type": True}, "fail")]:
            value = check_passengers(config, {"complete": True, "items": [{**person, **patch}]})
            self.assertEqual(value["status"], expected)
            self.assertNotIn("测试甲", json.dumps(value, ensure_ascii=False))
        self.assertEqual(check_passengers(config, {"complete": False, "items": []})["status"], "unknown")
        self.assertEqual(check_passengers(config, {"complete": True, "items": []})["status"], "fail")
        self.assertEqual(check_passengers(config, {"complete": True, "items": [person, person]})["status"], "fail")
        self.assertEqual(check_passengers({**config, "auto_alternate": True}, {"complete": True, "items": [{**person, "ticket_type": "unknown"}]})["status"], "fail")

    def test_account_holder_type_gap_and_missing_identity_hint_are_not_failures(self):
        config = {"passengers": "测试甲", "auto_alternate": True,
                  "passenger_selections": [{"name": "测试甲", "ticket_type": "adult", "identity_hint": "11***99"}]}
        holder = {"name": "测试甲", "ticket_type": "unknown", "type_source": "unavailable",
                  "verification": "passed", "identity_hint": "11***99"}
        # A missing type is a warning, never affirmative adult evidence.
        verdict = check_passengers(config, {"complete": True, "items": [holder]})
        self.assertEqual(verdict["status"], "warn")
        self.assertIn("未提供票种证据", verdict["details"][0])
        self.assertEqual(check_passengers(config, {"complete": True, "items": [{**holder, "verification": "pending"}]})["status"], "warn")
        contact = {**holder, "type_source": "profile_metadata"}
        self.assertEqual(check_passengers(config, {"complete": True, "items": [contact]})["status"], "fail")
        adult = {**holder, "ticket_type": "adult", "type_source": "profile_metadata"}
        self.assertEqual(check_passengers(config, {"complete": True, "items": [{**adult, "identity_hint": ""}]})["status"], "pass")
        self.assertEqual(check_passengers(config, {"complete": True, "items": [{**adult, "identity_hint": "12***99"}]})["status"], "warn")

    def test_train_separators_match_monitor(self):
        from railwatch_rehearsal import public_trip
        rows = [{"train": "G1", "seats": {"二等座": {"raw": "有"}}}, {"train": "G3", "seats": {"二等座": {"raw": "有"}}}]
        self.assertEqual(check_train_seat({"train_code": "g1；G3;G1", "seat_keyword": "二等座"}, rows, {"status": "ok"})["status"], "pass")
        self.assertEqual(public_trip({"train_code": "g1；G3;G1"})["train_codes"], ["G1", "G3"])

    def test_probe_date_never_uses_an_unreleased_day(self):
        from railwatch_rehearsal_checks import probe_date
        today = dt.date(2026, 9, 28)
        self.assertEqual(probe_date(dt.date(2026, 10, 20), today, True), dt.date(2026, 10, 12))
        self.assertEqual(probe_date(dt.date(2026, 10, 20), today, False), dt.date(2026, 10, 11))
        self.assertEqual(probe_date(dt.date(2026, 10, 12), today, False), dt.date(2026, 10, 11))
        self.assertEqual(probe_date(dt.date(2026, 10, 1), today, False), dt.date(2026, 10, 1))
        self.assertEqual(probe_date(today, today, False), today)

    def test_released_trip_does_not_block_on_timer(self):
        official = dt.datetime.fromisoformat("2026-09-28T15:00:00+08:00")
        now = official.timestamp() + 3600
        later = {"timer_enabled": True, "sale_at": "2026-09-28T18:00:00+08:00"}
        value = check_sale_time(later, official, now)
        self.assertEqual(value["status"], "warn")
        self.assertNotIn("sale_at", value["fix"])
        self.assertEqual(check_sale_time({"timer_enabled": True, "sale_at": "2026-09-28T15:30:00+08:00"}, official, now)["status"], "pass")
        early = check_sale_time({"timer_enabled": True, "sale_at": "2026-09-28T14:00:00+08:00"}, official, 0, checked_at=12.0)
        self.assertEqual((early["status"], early["fix"]["sale_at"], early["fix"]["checked_at"]), ("fail", official.isoformat(), 12.0))

    def test_query_limits_and_missing_cells(self):
        config = {"train_code": "G9", "seat_keyword": "二等座"}
        for value, expected in [("--", "fail"), (None, "warn"), ("无", "pass"), ("候补", "pass")]:
            self.assertEqual(check_train_seat(config, [{"train": "G9", "seats": {"二等座": {"raw": value}}}], {"status": "ok"})["status"], expected)
        self.assertEqual(check_train_seat(config, [], {"status": "empty"})["status"], "fail")
        self.assertEqual(check_train_seat(config, [], {"status": "rate_limited", "retry_after_seconds": 30})["status"], "warn")

    def test_local_thresholds(self):
        for value, expected in [(.5, "pass"), (1, "unknown"), (1.6, "warn"),
                                (3.1, "warn"), (3.6, "fail"), (-3.6, "fail")]:
            self.assertEqual(check_clock(value, .5)["status"], expected)
        self.assertEqual(check_clock(0, None)["status"], "unknown")
        for value, expected in [(100, "pass"), (250, "warn"), (251, "fail")]:
            self.assertEqual(check_scheduler({"p95": value})["status"], expected)
        self.assertEqual(check_alerts({}, {})["status"], "pass")
        self.assertEqual(check_alerts({"email_enabled": True}, {})["status"], "warn")
        official = dt.datetime.fromisoformat("2026-09-28T15:00:00+08:00")
        self.assertEqual(check_sale_time({"timer_enabled": True, "sale_at": official.isoformat()}, official, 0)["status"], "pass")

    def test_clock_uncertainty_cannot_report_slow_network_as_clock_failure_or_success(self):
        for offset, uncertainty in [(5.2, 6), (0, 6), (10, 6), (0, None), (None, .5),
                                    (float("nan"), .5), (0, float("inf")), (0, -1), (True, .5)]:
            with self.subTest(offset=offset, uncertainty=uncertainty):
                self.assertEqual(check_clock(offset, uncertainty)["status"], "unknown")
        self.assertEqual(check_clock(0, .5, "request failed")["status"], "unknown")
        self.assertIn("不用于提前查询", " ".join(check_clock(5.2, 6)["details"]))
