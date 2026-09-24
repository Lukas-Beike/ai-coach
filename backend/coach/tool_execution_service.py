"""Execute the specialized branches of structured Coach tool calls."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from typing import Any

from backend.activities.duplicates import (
    duplicate_delete_action,
    latest_wahoo_garmin_duplicate,
)
from backend.coach.clarification import CoachClarificationService
from backend.coach.proposals import CoachProposalCreationService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.training_patch import CoachTrainingPatchService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.sync.state import SyncStateRepository


class CoachStructuredToolExecutionService:
    """Own tool-specific execution while reusing existing durable state owners."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: Any,
        key_values: KeyValueRepository,
        clarification: CoachClarificationService,
        training_patch: CoachTrainingPatchService,
        sync_state: SyncStateRepository,
        proposal_creation: CoachProposalCreationService,
        tool_dispatch: CoachToolDispatchService,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._clarification = clarification
        self._training_patch = training_patch
        self._sync_state = sync_state
        self._proposal_creation = proposal_creation
        self._tool_dispatch = tool_dispatch

    def execute(
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
        local_transaction = name not in {"start_provider_refresh", "apply_adaptive_replan"}
        lock = self._database_lock if local_transaction else nullcontext()
        transaction = self._database_manager.unit_of_work() if local_transaction else nullcontext()
        with lock, transaction as db:
            if name == "clarify_coach_request":
                return self._clarification.save_question(arguments, context)
            if name == "cancel_coach_request":
                self._key_values.set(db, "coach_pending_request", "null")
                return {"ok": True, "status": "cancelled"}
            if name == "apply_training_patch":
                return self._training_patch.apply(arguments, action)
            if name == "inspect_activity_duplicates":
                duplicate = latest_wahoo_garmin_duplicate(
                    self._sync_state.latest_snapshot() or {}
                )
                result = {"ok": True, "duplicate": duplicate}
                if duplicate and session_csrf_hash:
                    result.update(
                        self._proposal_creation.create(
                            duplicate_delete_action(duplicate), session_csrf_hash
                        )
                    )
                return result
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
