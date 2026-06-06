import unittest

from railwatch_state import (
    APP_DISPLAY_NAME,
    APP_SLUG,
    APP_PAGES,
    AppPhase,
    RailWatchState,
    TicketHit,
)


class RailWatchStateTests(unittest.TestCase):
    def test_brand_and_information_architecture_are_productized(self):
        self.assertEqual(APP_DISPLAY_NAME, "RailWatch 12306")
        self.assertEqual(APP_SLUG, "railwatch-12306")
        self.assertEqual(APP_PAGES, ("Dashboard", "Trip Setup", "Monitor", "Settings"))

    def test_default_state_is_safe_and_idle(self):
        state = RailWatchState.initial()

        self.assertEqual(state.phase, AppPhase.IDLE)
        self.assertFalse(state.environment_ready)
        self.assertFalse(state.login_ready)
        self.assertFalse(state.monitoring)
        self.assertFalse(state.auto_submit_enabled)
        self.assertFalse(state.auto_alternate_enabled)
        self.assertEqual(state.risk_level, "notice")

    def test_state_transitions_cover_environment_login_monitor_and_hits(self):
        hit = TicketHit(train_code="G101", seat_type="First", status="available", source="regular")

        state = (
            RailWatchState.initial()
            .with_environment(True, "ChromeDriver OK")
            .with_login(True)
            .with_query_ready(True)
            .with_monitoring(True)
            .with_hit(hit)
        )

        self.assertEqual(state.phase, AppPhase.HIT)
        self.assertTrue(state.environment_ready)
        self.assertTrue(state.login_ready)
        self.assertTrue(state.query_ready)
        self.assertTrue(state.monitoring)
        self.assertEqual(state.hits, (hit,))
        self.assertIn("G101", state.summary())

    def test_errors_stop_monitoring_and_surface_risk(self):
        state = RailWatchState.initial().with_monitoring(True).with_error("Driver lost")

        self.assertEqual(state.phase, AppPhase.ERROR)
        self.assertFalse(state.monitoring)
        self.assertEqual(state.risk_level, "critical")
        self.assertEqual(state.error_message, "Driver lost")

    def test_hit_phase_survives_monitor_stop(self):
        hit = TicketHit(train_code="G101", seat_type="First", status="available")

        state = RailWatchState.initial().with_hit(hit).with_monitoring(False)

        self.assertEqual(state.phase, AppPhase.HIT)
        self.assertFalse(state.monitoring)
        self.assertEqual(state.hits, (hit,))


if __name__ == "__main__":
    unittest.main()
