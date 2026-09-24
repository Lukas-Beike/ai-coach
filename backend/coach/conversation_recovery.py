"""Recover a structured Coach turn when its remote conversation disappears."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.coach.attachments import model_input
from backend.coach.job_store import CoachJobStore
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError


class CoachConversationRecoveryService:
    """Own the one-time local-context recovery and its durable checkpoint."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        database_lock: Any,
        key_values: KeyValueRepository,
        jobs: CoachJobStore,
        logger: logging.Logger,
    ) -> None:
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._key_values = key_values
        self._jobs = jobs
        self._logger = logger

    def recover_if_invalid(
        self,
        exc: AppError,
        payload: dict[str, Any],
        request_payload: dict[str, Any],
        *,
        context: dict[str, Any],
        message: str,
        command_receipts: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        client_turn_id: str,
        ai_provider: str,
        recovery_state: dict[str, bool],
        request_delta_emitted: bool,
        attempt: int,
    ) -> bool:
        if (
            ai_provider != "openai"
            or exc.reason != "conversation_state_invalid"
            or recovery_state["conversation_recovered"]
            or request_delta_emitted
            or attempt >= 2
        ):
            return False

        recovery_state["conversation_recovered"] = True
        if payload.get("conversation"):
            with self._database_lock, self._database_manager.unit_of_work() as db:
                self._key_values.set(db, "openai_conversation_id", "")
        for candidate in (request_payload, payload):
            candidate.pop("conversation", None)
            candidate.pop("previous_response_id", None)
        payload["input"] = model_input(
            json.dumps(
                {
                    "dialogue": context,
                    "current_message": message,
                    "confirmed_steps": command_receipts,
                },
                ensure_ascii=False,
            ),
            attachments,
        )
        payload["instructions"] += (
            "\nThe remote conversation was unavailable. Continue only unfinished work "
            "using local dialogue and confirmed_steps. Earlier image pixels may be "
            "unavailable; ask for missing evidence only if essential. Never invent "
            "attachment details."
        )
        self._jobs.merge_receipt(
            client_turn_id,
            {
                "openai_response_id": None,
                "previous_response_id": None,
                "pending_tool_outputs": [],
                "response_input": payload["input"],
            },
        )
        self._logger.warning(
            "Coach conversation recovered from local context",
            extra={"event": "coach_conversation_recovered"},
        )
        return True
