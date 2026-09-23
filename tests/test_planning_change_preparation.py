"""Tests for pure structured planning change preparation."""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from backend.errors import INVALID_PLANNING_DATE_ERROR, AppError
from backend.planning import changes
from backend.planning.workouts import normalize_workout


class PlanningChangePreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2031, 6, 1)
        self.create_change = {
            "action": " create ",
            "date": (self.today + timedelta(days=1)).isoformat(),
            "sport": "Run",
            "name": "  Easy run  ",
            "description": "- 30m 60% easy",
            "duration_minutes": "30",
            "target": "POWER",
            "rationale": "  Recovery  ",
        }

    def assert_app_error(
        self,
        call,
        *,
        message: str,
        reason: str,
        status: int = 400,
    ) -> None:
        with self.assertRaises(AppError) as raised:
            call()
        self.assertEqual(raised.exception.status, status)
        self.assertEqual(raised.exception.message, message)
        self.assertEqual(raised.exception.reason, reason)

    def test_validated_training_date_trims_and_rejects_invalid_dates(self) -> None:
        self.assertEqual(
            changes.validated_training_date(" 2031-06-02T12:00:00 "),
            "2031-06-02",
        )
        self.assert_app_error(
            lambda: changes.validated_training_date("not-a-date"),
            message=INVALID_PLANNING_DATE_ERROR,
            reason="invalid_change",
        )

    def test_create_uses_injected_today_and_normalizes_without_mutating_input(
        self,
    ) -> None:
        original = copy.deepcopy(self.create_change)
        with patch.object(
            changes, "normalize_workout", wraps=normalize_workout
        ) as normalize:
            prepared = changes.prepare_structured_training_change(
                self.create_change, today=self.today
            )

        normalize.assert_called_once_with(self.create_change, today=self.today)
        self.assertEqual(
            prepared,
            {
                "action": "create",
                "date": "2031-06-02",
                "sport": "Run",
                "name": "Easy run",
                "description": "- 30m 60% easy",
                "duration_minutes": 30,
                "target": "POWER",
                "rationale": "Recovery",
            },
        )
        self.assertEqual(self.create_change, original)

    def test_create_trims_optional_plan_id_and_discards_other_fields(self) -> None:
        change = {
            **self.create_change,
            "plan_id": "  plan-123  ",
            "extra": "ignored",
        }
        prepared = changes.prepare_structured_training_change(change, today=self.today)
        self.assertEqual(prepared["plan_id"], "plan-123")
        self.assertNotIn("extra", prepared)

    def test_create_without_plan_id_omits_it_and_empty_plan_id_is_trimmed(self) -> None:
        prepared = changes.prepare_structured_training_change(
            self.create_change, today=self.today
        )
        self.assertNotIn("plan_id", prepared)

        change = {**self.create_change, "plan_id": "   "}
        prepared = changes.prepare_structured_training_change(change, today=self.today)
        self.assertEqual(prepared["plan_id"], "")

    def test_non_create_change_is_returned_by_identity(self) -> None:
        change = {"action": " update ", "local_id": "local-1", "extra": object()}
        self.assertIs(
            changes.prepare_structured_training_change(change, today=self.today),
            change,
        )

    def test_create_rejects_local_id_and_each_missing_or_blank_workout_field(
        self,
    ) -> None:
        self.assert_app_error(
            lambda: changes.prepare_structured_training_change(
                {**self.create_change, "local_id": "local-1"}, today=self.today
            ),
            message="Eine neue geplante Einheit darf keine lokale ID vorgeben.",
            reason="invalid_change",
        )

        required_fields = (
            "date",
            "sport",
            "name",
            "description",
            "duration_minutes",
            "target",
            "rationale",
        )
        for field in required_fields:
            with self.subTest(field=field, state="missing"):
                missing = {**self.create_change}
                missing.pop(field)
                self.assert_app_error(
                    lambda missing=missing: changes.prepare_structured_training_change(
                        missing, today=self.today
                    ),
                    message="Eine neue geplante Einheit benötigt alle Workout-Felder.",
                    reason="invalid_change",
                )
            for value in (None, "   "):
                with self.subTest(field=field, value=value):
                    incomplete = {**self.create_change, field: value}
                    self.assert_app_error(
                        lambda incomplete=incomplete: (
                            changes.prepare_structured_training_change(
                                incomplete, today=self.today
                            )
                        ),
                        message="Eine neue geplante Einheit benötigt alle Workout-Felder.",
                        reason="invalid_change",
                    )

    def test_create_accepts_only_supported_targets(self) -> None:
        for target in ("AUTO", "POWER", "HR", "PACE"):
            with self.subTest(target=target):
                change = {**self.create_change, "target": target}
                normalized = {
                    key: change[key]
                    for key in (
                        "date",
                        "sport",
                        "name",
                        "description",
                        "duration_minutes",
                        "target",
                        "rationale",
                    )
                }
                with patch.object(
                    changes, "normalize_workout", return_value=normalized
                ):
                    prepared = changes.prepare_structured_training_change(
                        change, today=self.today
                    )
                self.assertEqual(prepared["target"], target)

        for target in ("CADENCE", "power"):
            with self.subTest(target=target):
                self.assert_app_error(
                    lambda target=target: changes.prepare_structured_training_change(
                        {**self.create_change, "target": target}, today=self.today
                    ),
                    message="Das Workout-Ziel muss AUTO, POWER, HR oder PACE sein.",
                    reason="invalid_change",
                )

        for target in ([], {}):
            with (
                self.subTest(target=type(target).__name__),
                self.assertRaises(TypeError),
            ):
                changes.prepare_structured_training_change(
                    {**self.create_change, "target": target}, today=self.today
                )

    def test_batch_preserves_order_identity_and_arguments(self) -> None:
        first = {"action": "update", "local_id": "local-1"}
        second = {"action": "archive", "local_id": "local-2"}
        arguments = {"changes": [first, second]}
        original = copy.deepcopy(arguments)

        prepared = changes.prepare_structured_training_changes(
            arguments, today=self.today, max_changes=2
        )

        self.assertEqual(prepared, [first, second])
        self.assertIs(prepared[0], first)
        self.assertIs(prepared[1], second)
        self.assertEqual(arguments, original)

    def test_batch_rejects_missing_empty_non_list_and_oversized_changes(self) -> None:
        message = "Ein Coach-Kommando darf höchstens 2 Änderungen enthalten."
        for arguments in ({}, {"changes": []}, {"changes": None}, {"changes": "x"}):
            with self.subTest(arguments=arguments):
                self.assert_app_error(
                    lambda arguments=arguments: (
                        changes.prepare_structured_training_changes(
                            arguments, today=self.today, max_changes=2
                        )
                    ),
                    message=message,
                    reason="change_limit",
                )

        self.assert_app_error(
            lambda: changes.prepare_structured_training_changes(
                {"changes": [{}, {}, {}]}, today=self.today, max_changes=2
            ),
            message=message,
            reason="change_limit",
        )

    def test_batch_rejects_non_object_members(self) -> None:
        self.assert_app_error(
            lambda: changes.prepare_structured_training_changes(
                {"changes": [{"action": "update"}, "invalid"]},
                today=self.today,
                max_changes=2,
            ),
            message="Jede Planänderung muss ein Objekt sein.",
            reason="invalid_change",
        )

    def test_batch_preparation_does_not_mutate_create_input(self) -> None:
        create = {**self.create_change, "plan_id": "  plan-123  "}
        arguments = {"changes": [create]}
        original = copy.deepcopy(arguments)

        changes.prepare_structured_training_changes(
            arguments, today=self.today, max_changes=1
        )

        self.assertEqual(arguments, original)


if __name__ == "__main__":
    unittest.main()
