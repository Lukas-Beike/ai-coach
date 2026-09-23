"""Direct regression tests for full structured plan replacement preparation."""

import copy
import unittest
from datetime import date
from unittest.mock import patch

from backend.errors import AppError
from backend.planning.replacement import (
    prepare_structured_plan_replacement,
    validate_replacement_workouts,
)
from backend.planning.workouts import normalize_workout


class PlanningReplacementTests(unittest.TestCase):
    today = date(2026, 9, 20)

    @staticmethod
    def workout(workout_date="2026-09-22", **overrides):
        return {
            "date": workout_date,
            "sport": "Ride",
            "name": "Endurance",
            "description": "- 45m Z2",
            "duration_minutes": 45,
            "target": "AUTO",
            "rationale": "Build endurance",
            **overrides,
        }

    def arguments(self, **overrides):
        arguments = {
            "expected_revision": "7",
            "payload": {
                "plan_name": "  Base plan  ",
                "workouts": [self.workout()],
            },
        }
        arguments.update(overrides)
        return arguments

    def assert_app_error(self, arguments, *, status, reason, message):
        with self.assertRaises(AppError) as raised:
            prepare_structured_plan_replacement(arguments, today=self.today)
        error = raised.exception
        self.assertEqual(error.status, status)
        self.assertEqual(error.reason, reason)
        self.assertEqual(str(error), message)

    def test_prepares_happy_path_and_returns_original_payload(self):
        arguments = self.arguments()
        payload = arguments["payload"]

        result = prepare_structured_plan_replacement(arguments, today=self.today)

        self.assertIs(result[0], payload)
        self.assertEqual(result[1], 7)
        self.assertEqual(result[2][0]["date"], "2026-09-22")
        self.assertEqual(result[3], "Base plan")
        self.assertEqual(result[4], "2026-09-20")
        self.assertEqual(result[5], {"start": "2026-09-20", "end": "9999-12-31"})

    def test_rejects_missing_or_invalid_payload_before_other_validation(self):
        for arguments in ({}, {"payload": []}):
            with self.subTest(arguments=arguments):
                self.assert_app_error(
                    arguments,
                    status=400,
                    reason="invalid_plan",
                    message="Ein Planartefakt benoetigt payload.",
                )

    def test_enforces_plan_limits_before_revision_parsing(self):
        arguments = {
            "payload": {
                "plan_name": "Plan",
                "workouts": [self.workout()] * 367,
            }
        }

        self.assert_app_error(
            arguments,
            status=400,
            reason="plan_limit",
            message="Ein Planartefakt darf höchstens 366 Einheiten enthalten.",
        )

    def test_requires_an_integer_expected_revision(self):
        for revision in (None, "not-an-integer"):
            with self.subTest(revision=revision):
                self.assert_app_error(
                    self.arguments(expected_revision=revision),
                    status=400,
                    reason="planning_revision_required",
                    message="Ein vollständiger Planersatz benötigt die gelesene Planrevision.",
                )

    def test_trims_and_caps_plan_name_at_200_characters(self):
        arguments = self.arguments()
        arguments["payload"]["plan_name"] = "  " + ("P" * 205) + "  "

        result = prepare_structured_plan_replacement(arguments, today=self.today)

        self.assertEqual(result[3], "P" * 200)
        self.assertEqual(len(arguments["payload"]["plan_name"].strip()), 205)

    def test_rejects_blank_plan_name_after_workout_normalization(self):
        arguments = self.arguments()
        arguments["payload"]["plan_name"] = "  "

        self.assert_app_error(
            arguments,
            status=400,
            reason="invalid_plan",
            message="Ein vollständiger Planersatz benötigt einen Namen.",
        )

    def test_rejects_past_and_out_of_period_workouts(self):
        for workout_date, period in (
            ("2026-09-19", None),
            ("2026-09-22", {"start": "2026-09-23", "end": "2026-09-30"}),
            ("2026-10-01", {"start": "2026-09-21", "end": "2026-09-30"}),
        ):
            with self.subTest(workout_date=workout_date, period=period):
                arguments = self.arguments()
                arguments["payload"]["workouts"] = [self.workout(workout_date)]
                if period is not None:
                    arguments["period"] = period
                self.assert_app_error(
                    arguments,
                    status=400,
                    reason="invalid_plan",
                    message="Ein vollständiger Planersatz darf keine vergangenen Einheiten enthalten.",
                )

    def test_rejects_duplicate_workout_dates(self):
        arguments = self.arguments()
        arguments["payload"]["workouts"] = [
            self.workout("2026-09-22"),
            self.workout("2026-09-22", name="Second workout"),
        ]

        self.assert_app_error(
            arguments,
            status=409,
            reason="plan_date_conflict",
            message="Der Plan enthält mehrere Einheiten für den 2026-09-22; pro Tag ist eine Einheit möglich.",
        )

    def test_passes_injected_today_to_workout_normalization(self):
        injected_today = date(2040, 1, 1)
        arguments = self.arguments()
        arguments["payload"]["workouts"] = [self.workout("2040-01-01")]

        with patch(
            "backend.planning.replacement.normalize_workout",
            wraps=normalize_workout,
        ) as normalize:
            prepare_structured_plan_replacement(arguments, today=injected_today)

        normalize.assert_called_once()
        self.assertEqual(normalize.call_args.kwargs["today"], injected_today)

    def test_does_not_mutate_arguments_or_nested_workout_payload(self):
        arguments = self.arguments()
        arguments["period"] = {"start": "2026-09-21", "end": "2026-09-30"}
        arguments["payload"]["workouts"][0]["metadata"] = {"source": ["coach"]}
        original = copy.deepcopy(arguments)

        prepare_structured_plan_replacement(arguments, today=self.today)

        self.assertEqual(arguments, original)

    def test_direct_workout_validation_rejects_past_before_duplicate(self):
        workouts = [
            {"date": "2026-09-19"},
            {"date": "2026-09-19"},
        ]

        with self.assertRaises(AppError) as raised:
            validate_replacement_workouts(
                workouts,
                "2026-09-20",
                {"start": "2026-09-20", "end": "9999-12-31"},
            )

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.reason, "invalid_plan")
