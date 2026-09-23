"""Direct tests for structured Coach plan artifact limits."""

import copy
import unittest
from datetime import date, timedelta

from backend.errors import AppError
from backend.planning.artifacts import (
    structured_artifact_payload,
    validate_structured_plan_limits,
)


class PlanningArtifactTests(unittest.TestCase):
    def assert_app_error(self, payload, *, reason, message):
        with self.assertRaises(AppError) as raised:
            validate_structured_plan_limits(payload)
        error = raised.exception
        self.assertEqual(error.status, 400)
        self.assertEqual(error.reason, reason)
        self.assertEqual(str(error), message)

    def test_accepts_one_and_maximum_workout_counts(self):
        for count in (1, 366):
            with self.subTest(count=count):
                validate_structured_plan_limits(
                    {"workouts": [{"date": "2026-01-01"}] * count}
                )

    def test_accepts_date_span_of_exactly_730_days(self):
        start = date(2026, 1, 1)
        validate_structured_plan_limits(
            {
                "workouts": [
                    {"date": start.isoformat()},
                    {"date": (start + timedelta(days=730)).isoformat()},
                ]
            }
        )

    def test_rejects_more_than_366_workouts_before_item_validation(self):
        self.assert_app_error(
            {"workouts": [None] * 367},
            reason="plan_limit",
            message="Ein Planartefakt darf höchstens 366 Einheiten enthalten.",
        )

    def test_rejects_date_span_of_731_days(self):
        start = date(2026, 1, 1)
        self.assert_app_error(
            {
                "workouts": [
                    {"date": start.isoformat()},
                    {"date": (start + timedelta(days=731)).isoformat()},
                ]
            },
            reason="plan_limit",
            message="Ein Planartefakt darf höchstens 730 Tage umfassen.",
        )

    def test_rejects_missing_empty_and_non_list_workouts(self):
        for payload in ({}, {"workouts": []}, {"workouts": ()}):
            with self.subTest(payload=payload):
                self.assert_app_error(
                    payload,
                    reason="plan_limit",
                    message="Ein Planartefakt benötigt mindestens eine Einheit.",
                )

    def test_rejects_non_object_workouts(self):
        self.assert_app_error(
            {"workouts": ["2026-01-01"]},
            reason="invalid_plan",
            message="Jede Planeinheit muss ein Objekt sein.",
        )

    def test_rejects_invalid_and_missing_dates(self):
        for workout in ({"date": "20.09.2026"}, {}):
            with self.subTest(workout=workout):
                self.assert_app_error(
                    {"workouts": [workout]},
                    reason="invalid_plan",
                    message="Jede Planeinheit benötigt ein gültiges Datum.",
                )

    def test_uses_first_ten_date_characters_and_does_not_mutate_input(self):
        payload = {
            "workouts": [
                {"date": "2026-01-01T12:30:00Z", "details": {"sport": "Ride"}},
                {"date": "2026-01-02", "details": ["unchanged"]},
            ]
        }
        original = copy.deepcopy(payload)

        validate_structured_plan_limits(payload)

        self.assertEqual(payload, original)

    def test_structured_artifact_payload_returns_the_original_dict(self):
        payload = {"workouts": [{"date": "2026-01-01"}]}

        self.assertIs(structured_artifact_payload({"payload": payload}), payload)

    def test_structured_artifact_payload_rejects_missing_or_non_dict_payload(self):
        for arguments in ({}, {"payload": None}, {"payload": []}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(AppError) as raised:
                    structured_artifact_payload(arguments)
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.reason, "invalid_plan")
                self.assertEqual(
                    str(raised.exception), "Ein Planartefakt benoetigt payload."
                )


if __name__ == "__main__":
    unittest.main()
