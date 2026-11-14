from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock

from backend.coach.planning_change_tools import CoachPlanningChangeToolService
from backend.errors import AppError


class CoachPlanningChangeToolServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.replacement = Mock()
        self.replacement.replace.return_value = {"ok": True, "replaced": 1}
        self.changes = Mock()
        self.changes.apply.return_value = {"ok": True, "updated": 1}
        self.replacement_factory = Mock(return_value=self.replacement)
        self.changes_factory = Mock(return_value=self.changes)
        self.service = CoachPlanningChangeToolService(
            self.replacement_factory, self.changes_factory
        )

    def test_replace_projects_period_constraints_and_selected_plan(self) -> None:
        arguments = {"payload": {"workouts": []}}
        intent = {
            "operation": "replace_training_plan",
            "authorization_scope": ["training_plan:plan-1"],
            "period": {"start": "2099-01-01", "end": "2099-01-07"},
            "request": {"constraints": ["easy week"]},
        }

        result = self.service.execute("replace_training_plan", arguments, intent)

        self.assertEqual(result, {"ok": True, "replaced": 1})
        self.replacement_factory.assert_called_once_with()
        self.replacement.replace.assert_called_once_with(
            {
                **arguments,
                "period": intent["period"],
                "constraints": ["easy week"],
            },
            selected_plan_id="plan-1",
        )
        self.changes_factory.assert_not_called()

    def test_replace_allows_local_plan_scope_without_selected_plan(self) -> None:
        self.service.execute(
            "replace_training_plan",
            {"payload": {}},
            {
                "operation": "replace_training_plan",
                "authorization_scope": ["local_plan"],
            },
        )

        self.replacement.replace.assert_called_once_with(
            {"payload": {}, "period": None, "constraints": []}, selected_plan_id=None
        )

    def test_a_wrong_operation_scope_or_changes_are_rejected_before_any_factory(
        self,
    ) -> None:
        replace, apply = "replace_training_plan", "apply_training_changes"
        denied = (403, "intent_scope_denied")
        two_plans = ["training_plan:plan-1", "training_plan:plan-2"]
        create = {"changes": [{"action": "create", "plan_id": "plan-2"}]}
        # (tool, arguments, intent, (status, reason), factory that stays unused)
        cases: tuple[tuple[Any, ...], ...] = (
            (
                replace,
                {},
                {"operation": "other", "authorization_scope": ["local_plan"]},
                denied,
                self.replacement_factory,
            ),
            (
                replace,
                {},
                {"operation": replace, "authorization_scope": two_plans},
                (400, "intent_scope_denied"),
                self.replacement_factory,
            ),
            (
                replace,
                {},
                {"operation": replace, "authorization_scope": []},
                denied,
                self.replacement_factory,
            ),
            (
                apply,
                {},
                {"operation": apply},
                (400, "invalid_change"),
                self.changes_factory,
            ),
            (
                apply,
                {"changes": []},
                {"operation": "other"},
                denied,
                self.changes_factory,
            ),
            (
                apply,
                {"changes": []},
                {"operation": apply, "authorization_scope": two_plans},
                (400, "intent_scope_denied"),
                self.changes_factory,
            ),
            (
                apply,
                create,
                {"operation": apply, "authorization_scope": []},
                denied,
                self.changes_factory,
            ),
            (
                apply,
                create,
                {
                    "operation": apply,
                    "authorization_scope": ["local_plan", "training_plan:plan-1"],
                },
                denied,
                self.changes_factory,
            ),
            (
                apply,
                {"changes": [{"action": "update", "local_id": "unit-1"}]},
                {"operation": apply, "authorization_scope": []},
                denied,
                self.changes_factory,
            ),
        )
        for tool, arguments, intent, expected, factory in cases:
            with self.subTest(tool=tool, intent=intent):
                with self.assertRaises(AppError) as raised:
                    self.service.execute(tool, arguments, intent)

                self.assertEqual(
                    (raised.exception.status, raised.exception.reason), expected
                )
                factory.assert_not_called()

    def test_apply_passes_revision_and_authorized_plan_and_checks_create_and_update_scopes(
        self,
    ) -> None:
        arguments = {
            "changes": [
                {"action": "create", "plan_id": "plan-1"},
                {"action": "update", "local_id": "unit-1"},
            ]
        }
        intent = {
            "operation": "apply_training_changes",
            "authorization_scope": [
                "training_plan:plan-1",
                "local_plan_create",
                "planned_unit:unit-1",
            ],
            "bulk_change": True,
        }

        result = self.service.execute("apply_training_changes", arguments, intent)

        self.assertEqual(result, {"ok": True, "updated": 1})
        self.changes_factory.assert_called_once_with()
        self.changes.apply.assert_called_once_with(
            arguments, require_revision=True, authorized_plan_id="plan-1"
        )
        self.replacement_factory.assert_not_called()

    def test_apply_uses_local_plan_scope_for_create_and_update_fallback(self) -> None:
        arguments = {
            "changes": [
                {"action": "create"},
                {"action": "update", "local_id": "unit-1"},
            ]
        }
        intent = {
            "operation": "apply_training_changes",
            "authorization_scope": ["local_plan", "training_plan:plan-1"],
        }

        self.service.execute("apply_training_changes", arguments, intent)

        self.changes.apply.assert_called_once_with(
            arguments, require_revision=False, authorized_plan_id="plan-1"
        )

    def test_unknown_tool_name_returns_none_without_constructing_planning_services(
        self,
    ) -> None:
        result = self.service.execute("read_training_state", {}, {})

        self.assertIsNone(result)
        self.replacement_factory.assert_not_called()
        self.changes_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
