import unittest

from backend.coach.authorization import coach_execution_scope, require_coach_scope
from backend.errors import AppError


class CoachScopeBoundaryTests(unittest.TestCase):
    def test_require_coach_scope_allows_matching_scope(self):
        require_coach_scope({"authorization_scope": ["local_plan", "plan:42"]}, "plan:41", "plan:42")

    def test_require_coach_scope_denies_missing_scope(self):
        with self.assertRaises(AppError) as raised:
            require_coach_scope({"authorization_scope": ["local_plan"]}, "intervals_sync")

        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(raised.exception.reason, "intent_scope_denied")
        self.assertEqual(raised.exception.message, "Die strukturierte Coach-Autorisierung umfasst dieses Objekt nicht.")

    def test_period_horizon_is_inclusive_and_bulk_starts_above_limit(self):
        at_limit = coach_execution_scope(
            {"period": {"start": "2026-01-01", "end": "2026-01-07"}},
            background_horizon_days=7,
        )
        over_limit = coach_execution_scope(
            {"period": {"start": "2026-01-01", "end": "2026-01-08"}},
            background_horizon_days=7,
        )

        self.assertEqual(at_limit["horizon_days"], 7)
        self.assertFalse(at_limit["bulk_change"])
        self.assertEqual(over_limit["horizon_days"], 8)
        self.assertTrue(over_limit["bulk_change"])
        self.assertTrue(over_limit["background"])

    def test_empty_action_keeps_default_scope(self):
        self.assertEqual(
            coach_execution_scope(None, background_horizon_days=7),
            {"planning": False, "horizon_days": None, "planned_units": None,
             "bulk_change": False, "background": True},
        )
        self.assertEqual(
            coach_execution_scope({}, background_horizon_days=7),
            {"planning": False, "horizon_days": None, "planned_units": None,
             "bulk_change": False, "background": True},
        )


if __name__ == "__main__":
    unittest.main()
