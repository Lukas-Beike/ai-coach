"""Boundary tests for pure local planned-unit mutation preparation."""

import copy
import unittest

from backend.errors import (
    CORRUPT_PLANNING_ERROR,
    INVALID_PLANNING_DATE_ERROR,
    INVALID_PLANNING_ID_ERROR,
    AppError,
)
from backend.planning.planned_units import (
    planned_conflict_payload,
    planned_conflict_resolution_request,
    prepare_planned_workout_date,
)

LOCAL_ID = "e8267245-0d20-456f-9c9b-b4bf3fc3c233"


class PreparePlannedWorkoutDateTests(unittest.TestCase):
    def test_strips_date_and_preserves_existing_time_suffix_on_change(self):
        candidate = {"date": " 2026-09-21 "}
        current = {
            "date": "2026-09-20",
            "start_date_local": "2026-09-20T06:45:00+02:00",
            "metadata": {"keep": True},
        }
        original_current = copy.deepcopy(current)

        changed = prepare_planned_workout_date(candidate, current)

        self.assertTrue(changed)
        self.assertEqual(
            candidate,
            {
                "date": "2026-09-21",
                "start_date_local": "2026-09-21T06:45:00+02:00",
            },
        )
        self.assertEqual(current, original_current)

    def test_changed_date_uses_midnight_without_t_suffix(self):
        candidate = {"date": "2026-09-21"}
        current = {"date": "2026-09-20", "start_date_local": "2026-09-20 06:45"}

        changed = prepare_planned_workout_date(candidate, current)

        self.assertTrue(changed)
        self.assertEqual(candidate["start_date_local"], "2026-09-21T00:00:00")

    def test_unchanged_date_does_not_touch_start_date_local(self):
        candidate = {"date": " 2026-09-20 ", "start_date_local": "candidate value"}
        current = {
            "date": "2026-09-20T00:00:00",
            "start_date_local": "2026-09-20T06:45:00+02:00",
        }
        original_current = copy.deepcopy(current)

        changed = prepare_planned_workout_date(candidate, current)

        self.assertFalse(changed)
        self.assertEqual(candidate["date"], "2026-09-20")
        self.assertEqual(candidate["start_date_local"], "candidate value")
        self.assertEqual(current, original_current)

    def test_invalid_full_date_string_keeps_validation_error_contract(self):
        candidate = {"date": " 2026-09-21T06:00:00 "}
        current = {"date": "2026-09-20"}

        with self.assertRaises(AppError) as raised:
            prepare_planned_workout_date(candidate, current)

        self.assertEqual(candidate["date"], "2026-09-21T06:00:00")
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, INVALID_PLANNING_DATE_ERROR)
        self.assertIsNone(raised.exception.reason)
        self.assertEqual(current, {"date": "2026-09-20"})


class PlannedConflictRequestTests(unittest.TestCase):
    def test_normalizes_uuid_and_strategy_without_mutating_inputs(self):
        local_id = LOCAL_ID.upper()
        strategy = "  ADOPT_REMOTE  "

        result = planned_conflict_resolution_request(local_id, strategy)

        self.assertEqual(result, (LOCAL_ID, "adopt_remote"))
        self.assertEqual(local_id, LOCAL_ID.upper())
        self.assertEqual(strategy, "  ADOPT_REMOTE  ")

    def test_invalid_uuid_keeps_application_error_contract(self):
        with self.assertRaises(AppError) as raised:
            planned_conflict_resolution_request("not-a-uuid", "keep_local")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, INVALID_PLANNING_ID_ERROR)
        self.assertIsNone(raised.exception.reason)

    def test_invalid_strategy_keeps_application_error_contract(self):
        with self.assertRaises(AppError) as raised:
            planned_conflict_resolution_request(LOCAL_ID, "merge")

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, "Ungültige Konfliktstrategie.")
        self.assertIsNone(raised.exception.reason)


class PlannedConflictPayloadTests(unittest.TestCase):
    def test_returns_valid_payload_without_mutating_row(self):
        row = {"payload": '{"name":"Easy run","nested":{"kept":true}}', "id": 3}
        original_row = copy.deepcopy(row)

        payload = planned_conflict_payload(row)
        payload["name"] = "Changed in caller"
        reloaded = planned_conflict_payload(row)

        self.assertEqual(row, original_row)
        self.assertEqual(
            reloaded,
            {"name": "Easy run", "nested": {"kept": True}},
        )
        self.assertIsNot(payload, reloaded)

    def test_corrupt_json_and_non_object_payloads_are_rejected(self):
        for row in (
            {"payload": "{"},
            {"payload": "[]"},
            {"payload": "null"},
        ):
            with self.subTest(row=row), self.assertRaises(AppError) as raised:
                planned_conflict_payload(row)

            self.assertEqual(raised.exception.status, 409)
            self.assertEqual(raised.exception.message, CORRUPT_PLANNING_ERROR)
            self.assertIsNone(raised.exception.reason)


if __name__ == "__main__":
    unittest.main()
