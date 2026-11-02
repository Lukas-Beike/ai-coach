"""Execute the specialized branches of structured Coach tool calls."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from backend.activities.duplicate_inspection import DuplicateInspector
from backend.coach.clarification import CoachClarificationService
from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.training_patch import CoachTrainingPatchService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.planning.plan_guard_service import PlanGuardService

PROFILE_MUTATING_COACH_TOOLS = frozenset({"update_profile", "undo_training_change"})

# Coach tools that create or move future planned units; the server checks the
# resulting plan, rolls the write back on a blocking finding and returns the
# other findings as notes.
PLAN_CHECKED_TOOLS = frozenset(
    {
        "apply_training_patch",
        "apply_training_changes",
        "replace_training_plan",
        "apply_workout_library_plan",
        "commit_training_plan",
    }
)
PLAN_FINDINGS_ARGUMENT = "accept_plan_findings"

COACH_EXTERNAL_FOOD_LOOKUP_TOOLS = frozenset(
    {
        "lookup_food",
        "calculate_food_nutrition",
        "save_nutrition_template",
        "save_nutrition_product",
    }
)


class CoachStructuredToolExecutionService:
    """Own tool-specific execution while reusing existing durable state owners."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: Any,
        key_values: KeyValueRepository,
        clarification: CoachClarificationService,
        training_patch: CoachTrainingPatchService,
        duplicate_inspector: DuplicateInspector,
        proposal_creation: CoachProposalCreationService,
        tool_dispatch: CoachToolDispatchService,
        profile_mutation_coordinator: Any,
        plan_guard: Callable[[], PlanGuardService] | None = None,
    ) -> None:
        self._plan_guard = plan_guard
        self._profile_mutation_coordinator = profile_mutation_coordinator
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._clarification = clarification
        self._training_patch = training_patch
        self._duplicate_inspector = duplicate_inspector
        self._proposal_creation = proposal_creation
        self._tool_dispatch = tool_dispatch

    def execute(self, metadata: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Run one tool; plan writes are checked, blocked on illness, else noted."""
        if metadata["name"] not in PLAN_CHECKED_TOOLS or self._plan_guard is None:
            return self._execute_tool(metadata, **kwargs)
        guard = self._plan_guard()
        arguments = dict(metadata["arguments"])
        accepted = arguments.pop(PLAN_FINDINGS_ARGUMENT, None)
        accepted = accepted if isinstance(accepted, list) else []
        with self._database_lock, self._database_manager.unit_of_work():
            before = guard.findings()
            result = self._execute_tool({**metadata, "arguments": arguments}, **kwargs)
            notes = guard.verify(before, accepted)
        return {**result, "plan_check_notes": notes} if notes else result

    def _execute_tool(
        self,
        metadata: dict[str, Any],
        *,
        action: dict[str, Any],
        context: dict[str, Any],
        conversation_id: str,
        client_turn_id: str,
        session_csrf_hash: str,
        sync_job_ids: list[str],
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        name = metadata["name"]
        arguments = metadata["arguments"]
        local_transaction = name not in {
            "start_provider_refresh",
            "apply_adaptive_replan",
            "delete_duplicate_intervals_activity",
            *COACH_EXTERNAL_FOOD_LOOKUP_TOOLS,
        }
        lock = self._database_lock if local_transaction else nullcontext()
        transaction = (
            self._database_manager.unit_of_work()
            if local_transaction
            else nullcontext()
        )
        coordinator = (
            self._profile_mutation_coordinator
            if name in PROFILE_MUTATING_COACH_TOOLS
            else nullcontext()
        )
        with coordinator, lock, transaction as db:
            if name == "clarify_coach_request":
                return self._clarification.save_question(arguments, context)
            if name == "cancel_coach_request":
                self._key_values.set(db, "coach_pending_request", "null")
                return {"ok": True, "status": "cancelled"}
            if name == "apply_training_patch":
                return self._training_patch.apply(arguments, action)
            if name in {"save_nutrition_template", "save_nutrition_product"}:
                proposal = self._proposal_creation.create_local_write(
                    name,
                    arguments,
                    action,
                    conversation_id=conversation_id,
                    client_turn_id=client_turn_id,
                    session_csrf_hash=session_csrf_hash,
                )
                return {**proposal, "ok": True, "status": "approval_required"}
            if name == "inspect_activity_duplicates":
                duplicate = self._duplicate_inspector.latest()
                return {"ok": True, "duplicate": duplicate}
            if (
                action.get("intent") == "remote_sync"
                and (action.get("request") or {}).get("remote_write") is True
            ):
                proposal = self._proposal_creation.create_remote_write(
                    name,
                    arguments,
                    action,
                    conversation_id=conversation_id,
                    client_turn_id=client_turn_id,
                    session_csrf_hash=session_csrf_hash,
                )
                return {**proposal, "ok": True, "status": "approval_required"}
            return self._tool_dispatch.execute(
                name,
                arguments,
                intent=action,
                conversation_id=conversation_id,
                client_turn_id=client_turn_id,
                session_csrf_hash=session_csrf_hash,
                sync_job_ids=sync_job_ids,
                cancel_event=cancel_event,
            )
