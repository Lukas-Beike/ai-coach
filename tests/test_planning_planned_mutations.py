"""Boundary tests for pure local planned-unit mutation preparation."""

import copy
import unittest
from datetime import date

from backend.errors import (
    INVALID_PLANNING_DATE_ERROR,
    AppError,
)
from backend.planning.planned_units import (
    prepare_planned_workout_date,
)

LOCAL_ID = "e8267245-0d20-456f-9c9b-b4bf3fc3c233"
TODAY = date(2026, 9, 1)


class PreparePlannedWorkoutDateTests(unittest.TestCase):
    def test_strips_date_and_preserves_existing_time_suffix_on_change(self):
        candidate = {"date": " 2026-09-21 "}
        current = {
            "date": "2026-09-20",
            "starts_at_local": "2026-09-20T06:45:00+02:00",
            "metadata": {"keep": True},
        }
        original_current = copy.deepcopy(current)

        changed = prepare_planned_workout_date(candidate, current, today=TODAY)

        self.assertTrue(changed)
        self.assertEqual(
            candidate,
            {
                "date": "2026-09-21",
                "starts_at_local": "2026-09-21T06:45:00+02:00",
            },
        )
        self.assertEqual(current, original_current)

    def test_changed_date_uses_midnight_without_t_suffix(self):
        candidate = {"date": "2026-09-21"}
        current = {"date": "2026-09-20", "starts_at_local": "2026-09-20 06:45"}

        changed = prepare_planned_workout_date(candidate, current, today=TODAY)

        self.assertTrue(changed)
        self.assertEqual(candidate["starts_at_local"], "2026-09-21T00:00:00")

    def test_unchanged_date_does_not_touch_starts_at_local(self):
        candidate = {"date": " 2026-09-20 ", "starts_at_local": "candidate value"}
        current = {
            "date": "2026-09-20T00:00:00",
            "starts_at_local": "2026-09-20T06:45:00+02:00",
        }
        original_current = copy.deepcopy(current)

        changed = prepare_planned_workout_date(candidate, current, today=TODAY)

        self.assertFalse(changed)
        self.assertEqual(candidate["date"], "2026-09-20")
        self.assertEqual(candidate["starts_at_local"], "candidate value")
        self.assertEqual(current, original_current)

    def test_invalid_full_date_string_keeps_validation_error_contract(self):
        candidate = {"date": " 2026-09-21T06:00:00 "}
        current = {"date": "2026-09-20"}

        with self.assertRaises(AppError) as raised:
            prepare_planned_workout_date(candidate, current, today=TODAY)

        self.assertEqual(candidate["date"], "2026-09-21T06:00:00")
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, INVALID_PLANNING_DATE_ERROR)
        self.assertIsNone(raised.exception.reason)
        self.assertEqual(current, {"date": "2026-09-20"})


if __name__ == "__main__":
    unittest.main()
