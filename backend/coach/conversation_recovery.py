"""Recover a structured Coach turn when its remote conversation disappears."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.coach.context_selection import compact_coach_dialogue, select_coach_context
from backend.coach.request_payload import model_confirmed_steps
from backend.coach.response_transport import ModelRequest
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError


class CoachConversationRecoveryService:
    """Own the one-time recovery from the local context."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: Any,
        key_values: KeyValueRepository,
        logger: logging.Logger,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._logger = logger

    def recover_if_invalid(
        self,
        exc: AppError,
        request: ModelRequest,
        turn_request: ModelRequest,
        *,
        context: dict[str, Any],
        message: str,
        command_receipts: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        recovery_state: dict[str, bool],
        request_delta_emitted: bool,
        attempt: int,
    ) -> bool:
        if (
            exc.reason != "conversation_state_invalid"
            or recovery_state["conversation_recovered"]
            or request_delta_emitted
            or attempt >= 2
        ):
            return False

        recovery_state["conversation_recovered"] = True
        if request.conversation_id:
            with self._database_lock, self._database_manager.unit_of_work() as db:
                self._key_values.set(db, "openai_conversation_id", "")
        for candidate in (turn_request, request):
            candidate.conversation_id = None
        # The rebuilt dialogue carries the confirmed steps: no tool results to resend.
        request.steps = []
        request.input = json.dumps(
            {
                "dialogue": compact_coach_dialogue(
                    context,
                    select_coach_context(
                        message,
                        context,
                        attachments=bool(attachments),
                        has_receipts=bool(command_receipts),
                    ),
                ),
                "current_message": message,
                "confirmed_steps": model_confirmed_steps(command_receipts),
            },
            ensure_ascii=False,
        )
        # Later stateless rounds chain from the request's input, so they must
        # start from the rebuilt local dialogue and not the original input.
        turn_request.input = request.input
        request.instructions += (
            "\nThe remote conversation was unavailable. Continue only unfinished work "
            "using local dialogue and confirmed_steps. Earlier image pixels may be "
            "unavailable; ask for missing evidence only if essential. Never invent "
            "attachment details."
        )
        self._logger.warning(
            "Coach conversation recovered from local context",
            extra={"event": "coach_conversation_recovered"},
        )
        return True
