from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.errors import AppError


class CoachPlanningActionToolServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preview = Mock()
        self.preview.preview.return_value = {"id": "adjustment-1", "status": "preview"}
        self.adaptive_apply = Mock()
        self.adaptive_apply.apply.return_value = {"ok": True, "updated": 1}
        self.plans = Mock()
        self.plans.update.return_value = {"status": "updated", "plan_id": "plan-1"}
        self.history = Mock()
        self.history.preview.return_value = {
            "status": "preview",
            "change": {"id": "change-1"},
            "proposal": {"action_type": "undo_change", "payload": {"change_id": "change-1"}},
        }
        self.proposals = Mock()
        self.proposals.create.return_value = {"proposed_action": {"id": "proposal-1"}}
        self.factories = {
            "preview": Mock(return_value=self.preview),
            "adaptive_apply": Mock(return_value=self.adaptive_apply),
            "plans": Mock(return_value=self.plans),
            "history": Mock(return_value=self.history),
            "proposals": Mock(return_value=self.proposals),
        }
        self.service = CoachPlanningActionToolService(
            self.factories["preview"],
            self.factories["adaptive_apply"],
            self.factories["plans"],
            self.factories["history"],
            self.factories["proposals"],
        )

    def test_preview_returns_local_preview_only_after_operation_and_scope_checks(self) -> None:
        result = self.service.execute(
            "preview_adaptive_replan",
            {},
            {"operation": "preview_adaptive_replan", "authorization_scope": ["adaptive_replan"]},
            "turn-1",
            "csrf-hash-1",
        )

        self.assertEqual(result, {"ok": True, "id": "adjustment-1", "status": "preview"})
        self.preview.preview.assert_called_once_with()
        self.adaptive_apply.apply.assert_not_called()

    def test_preview_rejects_missing_operation_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "preview_adaptive_replan", {}, {"operation": "other", "authorization_scope": ["adaptive_replan"]},
                "turn-1", "csrf-hash-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factories["preview"].assert_not_called()

    def test_preview_rejects_missing_scope_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "preview_adaptive_replan", {}, {"operation": "preview_adaptive_replan", "authorization_scope": []},
                "turn-1", "csrf-hash-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factories["preview"].assert_not_called()

    def test_apply_delegates_arguments_intent_and_later_client_turn(self) -> None:
        arguments = {"adjustment_id": "adjustment-1"}
        intent = {
            "operation": "apply_adaptive_replan",
            "authorization_scope": ["adaptive_replan:adjustment-1"],
        }

        result = self.service.execute(
            "apply_adaptive_replan", arguments, intent, "turn-2", "csrf-hash-1"
        )

        self.assertEqual(result, {"ok": True, "updated": 1})
        self.factories["adaptive_apply"].assert_called_once_with()
        self.adaptive_apply.apply.assert_called_once_with(arguments, intent, "turn-2")

    def test_apply_propagates_authorization_failure_from_adaptive_owner(self) -> None:
        denied = AppError(403, "denied", reason="intent_scope_denied")
        self.adaptive_apply.apply.side_effect = denied

        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "apply_adaptive_replan",
                {"adjustment_id": "adjustment-1"},
                {"operation": "other", "authorization_scope": []},
                "turn-2",
                "csrf-hash-1",
            )

        self.assertIs(raised.exception, denied)
        self.factories["adaptive_apply"].assert_called_once_with()

    def test_update_projects_structured_payload_and_accepts_plan_scope(self) -> None:
        arguments = {
            "payload": {"plan_id": "plan-1", "action": "update", "goal": "Base"}
        }
        intent = {
            "operation": "update_training_plan",
            "authorization_scope": ["training_plan:plan-1"],
        }

        result = self.service.execute(
            "update_training_plan", arguments, intent, "turn-1", "csrf-hash-1"
        )

        self.assertEqual(result, {"ok": True, "status": "updated", "plan_id": "plan-1"})
        self.plans.update.assert_called_once_with("plan-1", arguments["payload"])

    def test_update_accepts_local_plan_scope(self) -> None:
        arguments = {"payload": {"plan_id": "plan-1", "action": "delete"}}
        self.service.execute(
            "update_training_plan",
            arguments,
            {"operation": "update_training_plan", "authorization_scope": ["local_plan"]},
            "turn-1",
            "csrf-hash-1",
        )

        self.plans.update.assert_called_once_with("plan-1", arguments["payload"])

    def test_update_rejects_missing_operation_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "update_training_plan", {"payload": {"plan_id": "plan-1"}},
                {"operation": "other", "authorization_scope": ["training_plan:plan-1"]},
                "turn-1", "csrf-hash-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factories["plans"].assert_not_called()

    def test_update_rejects_scope_for_a_different_plan_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "update_training_plan", {"payload": {"plan_id": "plan-1"}},
                {"operation": "update_training_plan", "authorization_scope": ["training_plan:plan-2"]},
                "turn-1", "csrf-hash-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factories["plans"].assert_not_called()

    def test_update_rejects_missing_payload_with_existing_client_error(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "update_training_plan", {},
                {"operation": "update_training_plan", "authorization_scope": ["local_plan"]},
                "turn-1", "csrf-hash-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (400, "invalid_action"))
        self.factories["plans"].assert_not_called()

    def test_undo_creates_session_bound_proposal_and_excludes_raw_proposal(self) -> None:
        result = self.service.execute(
            "undo_training_change",
            {"change_id": "change-1"},
            {"operation": "undo_training_change", "authorization_scope": ["change:change-1"]},
            "turn-1",
            "csrf-hash-1",
        )

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "preview",
                "change": {"id": "change-1"},
                "proposed_action": {"id": "proposal-1"},
            },
        )
        self.history.preview.assert_called_once_with("change-1")
        self.proposals.create.assert_called_once_with(
            {"action_type": "undo_change", "payload": {"change_id": "change-1"}},
            "csrf-hash-1",
        )
        self.assertNotIn("proposal", result)

    def test_undo_rejects_missing_operation_before_history_or_proposal_factories(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "undo_training_change", {"change_id": "change-1"},
                {"operation": "other", "authorization_scope": ["change:change-1"]},
                "turn-1", "csrf-hash-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factories["history"].assert_not_called()
        self.factories["proposals"].assert_not_called()

    def test_undo_rejects_wrong_change_scope_before_factories(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "undo_training_change", {"change_id": "change-1"},
                {"operation": "undo_training_change", "authorization_scope": ["change:change-2"]},
                "turn-1", "csrf-hash-1",
            )

        self.assertEqual((raised.exception.status, raised.exception.reason), (403, "intent_scope_denied"))
        self.factories["history"].assert_not_called()
        self.factories["proposals"].assert_not_called()

    def test_unknown_name_returns_none_without_constructing_any_owner(self) -> None:
        result = self.service.execute("not_a_misc_tool", {}, {}, "turn-1", "csrf-hash-1")

        self.assertIsNone(result)
        for factory in self.factories.values():
            factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
