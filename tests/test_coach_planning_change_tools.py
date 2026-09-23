from __future__ import annotations

import unittest
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
            self.replacement_factory, self.changes_factory, "training_plan:"
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
            {"operation": "replace_training_plan", "authorization_scope": ["local_plan"]},
        )

        self.replacement.replace.assert_called_once_with(
            {"payload": {}, "period": None, "constraints": []}, selected_plan_id=None
        )

    def test_replace_rejects_unauthorized_operation_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "replace_training_plan", {}, {"operation": "other", "authorization_scope": ["local_plan"]}
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.replacement_factory.assert_not_called()

    def test_replace_rejects_multiple_plan_scopes(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "replace_training_plan",
                {},
                {
                    "operation": "replace_training_plan",
                    "authorization_scope": ["training_plan:plan-1", "training_plan:plan-2"],
                },
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (400, "intent_scope_denied"))
        self.replacement_factory.assert_not_called()

    def test_replace_requires_named_plan_or_local_plan_scope(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "replace_training_plan", {}, {"operation": "replace_training_plan", "authorization_scope": []}
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.replacement_factory.assert_not_called()

    def test_apply_passes_revision_and_authorized_plan_and_checks_create_and_update_scopes(self) -> None:
        arguments = {
            "changes": [
                {"action": "create", "plan_id": "plan-1"},
                {"action": "update", "local_id": "unit-1"},
            ]
        }
        intent = {
            "operation": "apply_training_changes",
            "authorization_scope": [
                "training_plan:plan-1", "local_plan_create", "planned_unit:unit-1"
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

    def test_apply_rejects_non_list_changes(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "apply_training_changes", {}, {"operation": "apply_training_changes"}
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (400, "invalid_change"))
        self.changes_factory.assert_not_called()

    def test_apply_rejects_unauthorized_operation_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "apply_training_changes", {"changes": []}, {"operation": "other"}
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.changes_factory.assert_not_called()

    def test_apply_rejects_multiple_plan_scopes(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "apply_training_changes",
                {"changes": []},
                {
                    "operation": "apply_training_changes",
                    "authorization_scope": ["training_plan:plan-1", "training_plan:plan-2"],
                },
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (400, "intent_scope_denied"))
        self.changes_factory.assert_not_called()

    def test_apply_rejects_unauthorized_create_or_requested_plan(self) -> None:
        denied_intents = (
            {"operation": "apply_training_changes", "authorization_scope": []},
            {
                "operation": "apply_training_changes",
                "authorization_scope": ["local_plan", "training_plan:plan-1"],
            },
        )
        for intent in denied_intents:
            with self.subTest(intent=intent), self.assertRaises(AppError) as raised:
                self.service.execute(
                    "apply_training_changes",
                    {"changes": [{"action": "create", "plan_id": "plan-2"}]},
                    intent,
                )
            self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.changes_factory.assert_not_called()

    def test_apply_rejects_update_outside_planned_unit_scope(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "apply_training_changes",
                {"changes": [{"action": "update", "local_id": "unit-1"}]},
                {"operation": "apply_training_changes", "authorization_scope": []},
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.changes_factory.assert_not_called()

    def test_unknown_tool_name_returns_none_without_constructing_planning_services(self) -> None:
        result = self.service.execute("read_training_state", {}, {})

        self.assertIsNone(result)
        self.replacement_factory.assert_not_called()
        self.changes_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
