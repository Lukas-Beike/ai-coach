"""Execute the specialized branches of structured Coach tool calls."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from backend.coach.clarification import CoachClarificationService
from backend.coach.proposal_creation import (
    CoachProposalCreationService,
    remote_removal_lines,
)
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.tool_specs import (
    EXTERNAL_FOOD_LOOKUP_TOOLS,
    PLAN_CHECKED_TOOLS,
    PROFILE_MUTATING_TOOLS,
    SELF_GUARDED_TOOLS,
)
from backend.coach.training_patch import CoachTrainingPatchService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.planning.plan_guard_service import (
    PLAN_FINDINGS_ARGUMENT,
    PlanGuardService,
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
        self._proposal_creation = proposal_creation
        self._tool_dispatch = tool_dispatch

    def execute(self, metadata: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Run one tool; plan writes are checked, blocked on illness, else noted."""
        name = metadata["name"]
        if (
            name not in PLAN_CHECKED_TOOLS
            or name in SELF_GUARDED_TOOLS
            or self._plan_guard is None
        ):
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
            *EXTERNAL_FOOD_LOOKUP_TOOLS,
        }
        lock = self._database_lock if local_transaction else nullcontext()
        transaction = (
            self._database_manager.unit_of_work()
            if local_transaction
            else nullcontext()
        )
        coordinator = (
            self._profile_mutation_coordinator
            if name in PROFILE_MUTATING_TOOLS
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
            removals: list[str] = []
            if (
                action.get("intent") == "remote_sync"
                and (action.get("request") or {}).get("remote_write") is True
            ):
                binding = {
                    "conversation_id": conversation_id,
                    "client_turn_id": client_turn_id,
                    "session_csrf_hash": session_csrf_hash,
                }
                # The athlete's named sync is the approval (#2342); only an
                # explicit Garmin removal still asks on a card.
                if _removes_garmin_workouts(name, arguments):
                    proposal = self._proposal_creation.create_remote_write(
                        name, arguments, action, **binding
                    )
                    return {**proposal, "ok": True, "status": "approval_required"}
                prepared = self._proposal_creation.prepare_remote_write(
                    name, arguments, action, **binding
                )
                arguments = prepared["payload"]["arguments"]
                action = prepared["payload"]["intent"]
                removals = remote_removal_lines(prepared["details"])
            result = self._tool_dispatch.execute(
                name,
                arguments,
                intent=action,
                conversation_id=conversation_id,
                client_turn_id=client_turn_id,
                session_csrf_hash=session_csrf_hash,
                sync_job_ids=sync_job_ids,
                cancel_event=cancel_event,
            )
            return {**result, "remote_removals": removals} if removals else result


def _removes_garmin_workouts(name: str, arguments: dict[str, Any]) -> bool:
    entries = arguments.get("entries") if name == "push_strength_to_garmin" else None
    return isinstance(entries, list) and any(
        isinstance(entry, dict) and entry.get("remove") is True for entry in entries
    )
