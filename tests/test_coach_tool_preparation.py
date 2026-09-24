"""Direct contracts for structured Coach action preparation."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock

from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.errors import AppError
from backend.sync.authority import PlanningAuthorityService
from backend.sync.state import SyncStateRepository


class StructuredToolPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dialogue_action = Mock(spec=CoachDialogueActionService)
        self.sync_state = Mock(spec=SyncStateRepository)
        self.planning_authority = Mock(spec=PlanningAuthorityService)
        self.defaults = {"intervals": 90, "garmin": 30}
        self.all_sync_days = -1
        self.read_only_tools = frozenset({"get_profile", "get_sync_job"})
        self.service = CoachStructuredToolPreparationService(
            self.dialogue_action,
            self.sync_state,
            self.planning_authority,
            self.read_only_tools,
            self.defaults,
            self.all_sync_days,
        )

    @staticmethod
    def metadata(
        name: str,
        arguments: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "arguments": arguments if arguments is not None else {},
            "action": action if action is not None else {"authorization_scope": []},
        }

    @staticmethod
    def assert_app_error(test: unittest.TestCase, expected_status: int, expected_reason: str, call) -> None:
        with test.assertRaises(AppError) as raised:
            call()
        test.assertEqual(raised.exception.status, expected_status)
        test.assertEqual(raised.exception.reason, expected_reason)

    def test_paused_or_cancelled_turn_blocks_mutating_tools(self) -> None:
        for question, cancelled in (("Which plan?", False), ("", True)):
            with self.subTest(question=bool(question), cancelled=cancelled):
                self.assert_app_error(
                    self,
                    409,
                    "request_paused",
                    lambda question=question, cancelled=cancelled: self.service.prepare(
                        self.metadata("update_training_plan"), [],
                        question=question, cancelled=cancelled,
                        context={}, allow_mutations=True,
                    ),
                )
        self.dialogue_action.classify.assert_not_called()

    def test_readonly_and_clarification_control_tools_skip_classifier(self) -> None:
        metadata = self.metadata("get_profile")
        result = self.service.prepare(
            metadata, [], question="pending", cancelled=False,
            context={}, allow_mutations=False,
        )
        self.assertIs(result, metadata["action"])
        for name in ("clarify_coach_request", "cancel_coach_request"):
            with self.subTest(name=name):
                metadata = self.metadata(name)
                result = self.service.prepare(
                    metadata, [], question="", cancelled=False,
                    context={}, allow_mutations=False,
                )
                self.assertIs(result, metadata["action"])
        self.dialogue_action.classify.assert_not_called()

    def test_allow_mutations_is_forwarded_to_dialogue_authorization(self) -> None:
        self.dialogue_action.classify.side_effect = AppError(
            403, "denied", reason="intent_scope_denied"
        )
        self.assert_app_error(
            self,
            403,
            "intent_scope_denied",
            lambda: self.service.prepare(
                self.metadata("update_training_plan"), [], question="", cancelled=False,
                context={"current_user_message_id": "synthetic"}, allow_mutations=False,
            ),
        )
        self.dialogue_action.classify.assert_called_once_with(
            "update_training_plan", {}, {"current_user_message_id": "synthetic"},
            allow_mutations=False,
        )

    def test_remote_write_is_blocked_by_unresolved_local_failure(self) -> None:
        action = {"request": {"remote_write": True}}
        self.dialogue_action.classify.return_value = action
        receipts = [{
            "tool": "update_training_plan",
            "step_key": "local-step",
            "result": {"ok": False, "reason": "tool_failed"},
        }]
        self.assert_app_error(
            self,
            409,
            "request_dependency",
            lambda: self.service.prepare(
                self.metadata("start_intervals_plan_sync"), receipts,
                question="", cancelled=False, context={}, allow_mutations=True,
            ),
        )
        self.sync_state.sync_period.assert_not_called()
        self.planning_authority.pending_plan_push_entries.assert_not_called()

    def test_intervals_refresh_gets_wait_flag_and_default_period(self) -> None:
        self.dialogue_action.classify.return_value = {"target_system": "intervals"}
        self.sync_state.sync_period.return_value = 75
        arguments: dict[str, Any] = {}
        result = self.service.prepare(
            self.metadata("start_provider_refresh", arguments), [],
            question="", cancelled=False, context={}, allow_mutations=True,
        )
        self.assertEqual(arguments, {"_wait_for_completion": True, "days": 75})
        self.assertEqual(result["target_system"], "intervals")
        self.sync_state.sync_period.assert_called_once_with(
            "intervals", self.defaults, self.all_sync_days
        )

    def test_intervals_refresh_preserves_selected_period_but_still_reads_default(self) -> None:
        self.dialogue_action.classify.return_value = {"target_system": "intervals"}
        arguments = {"days": 12}
        self.service.prepare(
            self.metadata("start_provider_refresh", arguments), [],
            question="", cancelled=False, context={}, allow_mutations=True,
        )
        self.assertEqual(arguments, {"days": 12, "_wait_for_completion": True})
        self.sync_state.sync_period.assert_called_once_with(
            "intervals", self.defaults, self.all_sync_days
        )

    def test_get_sync_job_receives_object_scope_without_reclassification(self) -> None:
        action = {"authorization_scope": ["old"]}
        metadata = self.metadata("get_sync_job", {"job_id": "job-123"}, action)
        result = self.service.prepare(
            metadata, [], question="", cancelled=False, context={}, allow_mutations=True,
        )
        self.assertIs(result, action)
        self.assertEqual(action["authorization_scope"], ["sync_job:job-123"])
        self.dialogue_action.classify.assert_not_called()

    def test_created_plan_sync_projects_exact_ids_and_scopes(self) -> None:
        action = {"authorization_scope": ["intervals_sync"], "request": {"sync_scope": "created"}}
        entries = [
            {"library_workout_id": "unit-b", "expected_payload_hash": "hash-b"},
            {"library_workout_id": "unit-a", "expected_payload_hash": "hash-a"},
            {"library_workout_id": "unrelated", "expected_payload_hash": "hash-x"},
        ]
        self.dialogue_action.classify.return_value = action
        self.planning_authority.pending_plan_push_entries.return_value = entries
        arguments: dict[str, Any] = {}
        receipts = [{"tool": "stage_training_plan", "result": {
            "ok": True, "library_entry_ids": ["unit-b", "unit-a"],
        }}]
        result = self.service.prepare(
            self.metadata("start_intervals_plan_sync", arguments), receipts,
            question="", cancelled=False, context={}, allow_mutations=True,
        )
        self.assertIs(result, action)
        self.assertEqual(arguments["entries"], entries[:2])
        self.assertEqual(action["_created_sync_entry_ids"], ["unit-a", "unit-b"])
        self.assertEqual(action["authorization_scope"][0], "intervals_sync")
        self.assertEqual(set(action["authorization_scope"][1:]), {
            "library_workout:unit-a", "library_workout:unit-b",
        })

    def test_created_sync_requires_successful_created_ids(self) -> None:
        action = {"authorization_scope": [], "request": {"sync_scope": "created"}}
        self.dialogue_action.classify.return_value = action
        self.assert_app_error(
            self,
            409,
            "plan_commit_required",
            lambda: self.service.prepare(
                self.metadata("start_intervals_plan_sync"), [], question="", cancelled=False,
                context={}, allow_mutations=True,
            ),
        )
        self.planning_authority.pending_plan_push_entries.assert_not_called()

    def test_created_sync_rejects_authority_manifest_revision_drift(self) -> None:
        action = {"authorization_scope": [], "request": {"sync_scope": "created"}}
        self.dialogue_action.classify.return_value = action
        self.planning_authority.pending_plan_push_entries.return_value = [
            {"library_workout_id": "unit-a", "expected_payload_hash": "current-hash"}
        ]
        receipts = [{"tool": "stage_training_plan", "result": {
            "ok": True, "library_entry_ids": ["unit-a", "unit-b"],
        }}]
        self.assert_app_error(
            self,
            409,
            "planning_revision_conflict",
            lambda: self.service.prepare(
                self.metadata("start_intervals_plan_sync"), receipts, question="", cancelled=False,
                context={}, allow_mutations=True,
            ),
        )

    def test_all_pending_discards_explicit_entries_without_reading_manifest(self) -> None:
        action = {"authorization_scope": [], "request": {"sync_scope": "all_pending"}}
        self.dialogue_action.classify.return_value = action
        arguments = {"entries": [{"library_workout_id": "stale"}]}
        self.service.prepare(
            self.metadata("start_intervals_plan_sync", arguments), [],
            question="", cancelled=False, context={}, allow_mutations=True,
        )
        self.assertNotIn("entries", arguments)
        self.planning_authority.pending_plan_push_entries.assert_not_called()

    def test_selected_sync_requires_entries_unless_repairing(self) -> None:
        action = {"authorization_scope": [], "request": {"sync_scope": "selected"}}
        self.dialogue_action.classify.return_value = action
        self.assert_app_error(
            self,
            400,
            "request_sync",
            lambda: self.service.prepare(
                self.metadata("start_intervals_plan_sync"), [], question="", cancelled=False,
                context={}, allow_mutations=True,
            ),
        )
        repair_arguments = {"repair": True}
        self.service.prepare(
            self.metadata("start_intervals_plan_sync", repair_arguments), [],
            question="", cancelled=False, context={}, allow_mutations=True,
        )
        self.assertEqual(repair_arguments, {"repair": True})

    def test_selected_sync_preserves_explicit_selection(self) -> None:
        action = {"authorization_scope": [], "request": {"sync_scope": "selected"}}
        self.dialogue_action.classify.return_value = action
        selected = [{"library_workout_id": "unit-a", "expected_payload_hash": "hash-a"}]
        arguments = {"entries": selected}
        self.service.prepare(
            self.metadata("start_intervals_plan_sync", arguments), [],
            question="", cancelled=False, context={}, allow_mutations=True,
        )
        self.assertIs(arguments["entries"], selected)
        self.planning_authority.pending_plan_push_entries.assert_not_called()


if __name__ == "__main__":
    unittest.main()
