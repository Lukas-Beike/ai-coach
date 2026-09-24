"""Own one structured Coach turn from durable opening to final receipt."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.coach.conversation import CoachAttachmentContextService
from backend.coach.dialogue import CoachDialogueReadService
from backend.coach.final_receipt import CoachFinalReceiptService
from backend.coach.request_payload import CoachRequestPayloadService
from backend.coach.structured_response import CoachStructuredResponseService
from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundService,
    StructuredCoachRoundState,
)
from backend.coach.turn_failures import CoachTurnFailureService, coach_error_metadata
from backend.coach.turn_opening import CoachTurnOpeningService
from backend.coach.turn_outcome import CoachStructuredOutcomeService
from backend.errors import AppError


@dataclass(frozen=True)
class CoachStructuredTurnDependencies:
    opening: CoachTurnOpeningService
    attachments: CoachAttachmentContextService
    dialogue: CoachDialogueReadService
    payload: CoachRequestPayloadService
    response: CoachStructuredResponseService
    rounds: CoachStructuredToolRoundService
    outcome: CoachStructuredOutcomeService
    final_receipt: CoachFinalReceiptService
    failure: CoachTurnFailureService
    tools: list[dict[str, Any]]
    read_only_tools: frozenset[str]
    logger: logging.Logger
    root: Path


class CoachStructuredTurnService:
    """Coordinate the existing concrete owners without server callbacks."""

    def __init__(self, dependencies: CoachStructuredTurnDependencies) -> None:
        self._deps = dependencies

    @staticmethod
    def _resume_id(
        receipt: dict[str, Any], request_payload: dict[str, Any], *, ai_provider: str, background_owned: bool,
    ) -> str:
        resume_id = str(receipt.get("openai_response_id") or "") if background_owned and ai_provider == "openai" else ""
        if resume_id and receipt.get("response_input"):
            request_payload["input"] = receipt["response_input"]
            if receipt.get("previous_response_id") and not request_payload.get("conversation"):
                request_payload["previous_response_id"] = receipt["previous_response_id"]
        if background_owned and receipt.get("pending_tool_outputs"):
            request_payload["input"] = receipt["pending_tool_outputs"]
            if ai_provider == "openai" and resume_id and not request_payload.get("conversation"):
                request_payload["previous_response_id"] = resume_id
            resume_id = ""
        return resume_id

    def _open_and_request(
        self,
        message: str,
        *,
        intent: dict[str, Any],
        conversation_id: str,
        client_turn_id: str,
        session_csrf_hash: str,
        background_job: bool,
        ai_provider: str,
        model: str | None,
        thinking_level: str | None,
        on_text_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        receipt = self._deps.opening.open(
            message, intent=intent, conversation_id=conversation_id, client_turn_id=client_turn_id,
            session_csrf_hash=session_csrf_hash, ai_provider=ai_provider, model=model,
        )
        attachments, has_prior_openai_attachments = self._deps.attachments.load_for_receipt(receipt)
        retain_openai_attachment_context = ai_provider == "openai" and bool(attachments or has_prior_openai_attachments)
        background_owned = background_job and receipt.get("mode") == "background"
        context = self._deps.dialogue.context(client_turn_id)
        self._deps.attachments.add_evidence(context)
        allow_mutations = intent.get("allow_mutations", True)
        command_receipts = list(receipt.get("command_receipts") or [])
        sync_job_ids = list(receipt.get("sync_job_ids") or [])
        tools = self._deps.tools if allow_mutations else [
            tool for tool in self._deps.tools if tool["name"] in self._deps.read_only_tools
        ]
        model_instructions, request_payload = self._deps.payload.build(
            message=message, context=context, command_receipts=command_receipts, tools=tools,
            allow_mutations=allow_mutations, ai_provider=ai_provider, model=model,
            thinking_level=thinking_level, conversation_id=conversation_id, attachments=attachments,
            retain_openai_attachment_context=retain_openai_attachment_context,
            has_prior_openai_attachments=has_prior_openai_attachments,
        )
        recovery_state = {"conversation_recovered": False}
        resume_id = self._resume_id(
            receipt, request_payload, ai_provider=ai_provider, background_owned=background_owned,
        )
        response = self._deps.response.respond(
            request_payload, request_payload=request_payload, context=context, message=message,
            command_receipts=command_receipts, attachments=attachments, client_turn_id=client_turn_id,
            ai_provider=ai_provider, background_owned=background_owned, on_text_delta=on_text_delta,
            cancel_event=cancel_event, recovery_state=recovery_state, resume_id=resume_id,
        )
        return {
            "receipt": receipt, "context": context, "command_receipts": command_receipts,
            "sync_job_ids": sync_job_ids, "allow_mutations": allow_mutations, "tools": tools,
            "model_instructions": model_instructions, "request_payload": request_payload,
            "recovery_state": recovery_state, "attachments": attachments,
            "background_owned": background_owned, "response": response,
        }

    def _run_turn(
        self,
        message: str,
        *,
        intent: dict[str, Any],
        conversation_id: str,
        client_turn_id: str,
        on_text_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
        session_csrf_hash: str,
        background_job: bool,
        ai_provider: str,
        model: str | None,
        thinking_level: str | None,
    ) -> dict[str, Any]:
        state = self._open_and_request(
            message, intent=intent, conversation_id=conversation_id, client_turn_id=client_turn_id,
            session_csrf_hash=session_csrf_hash, background_job=background_job,
            ai_provider=ai_provider, model=model, thinking_level=thinking_level,
            on_text_delta=on_text_delta, cancel_event=cancel_event,
        )
        receipt = state["receipt"]
        context = state["context"]
        command_receipts = state["command_receipts"]
        sync_job_ids = state["sync_job_ids"]
        allow_mutations = state["allow_mutations"]
        round_state = StructuredCoachRoundState(
            tools=state["tools"], command_receipts=command_receipts, sync_job_ids=sync_job_ids,
            context=context, allow_mutations=allow_mutations, conversation_id=conversation_id,
            client_turn_id=client_turn_id, session_csrf_hash=session_csrf_hash,
            cancel_event=cancel_event, ai_provider=ai_provider, request_payload=state["request_payload"],
            model_instructions=state["model_instructions"], message=message, attachments=state["attachments"],
            background_owned=state["background_owned"], on_text_delta=on_text_delta,
            recovery_state=state["recovery_state"],
        )
        response, rounds, question, cancelled, _ = self._deps.rounds.run(
            state["response"], rounds=int(receipt.get("tool_rounds") or 0),
            question="", cancelled=False, state=round_state,
        )
        status, text, failures = self._deps.outcome.finalize(
            response, command_receipts, question=question, cancelled=cancelled,
            allow_mutations=allow_mutations, context=context, message=message,
        )
        final_receipt = self._deps.final_receipt.build(
            receipt, status=status, response=response, client_turn_id=client_turn_id,
            command_receipts=command_receipts, sync_job_ids=sync_job_ids, intent=intent,
            rounds=rounds, failures=failures, awaiting_clarification=bool(question),
        )
        final_receipt["text"] = text
        return self._deps.final_receipt.persist(
            final_receipt, client_turn_id=client_turn_id,
            command_receipts=command_receipts, ai_provider=ai_provider,
        )

    def run(
        self,
        message: str,
        *,
        intent: dict[str, Any],
        conversation_id: str,
        client_turn_id: str,
        on_text_delta: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        session_csrf_hash: str = "",
        background_job: bool = False,
        ai_provider: str,
        model: str | None = None,
        thinking_level: str | None = None,
    ) -> dict[str, Any]:
        """Persist a complete turn or the safe terminal failure receipt."""
        try:
            receipt = self._run_turn(
                message, intent=intent, conversation_id=conversation_id,
                client_turn_id=client_turn_id, on_text_delta=on_text_delta,
                cancel_event=cancel_event, session_csrf_hash=session_csrf_hash,
                background_job=background_job, ai_provider=ai_provider,
                model=model, thinking_level=thinking_level,
            )
        except Exception as exc:
            if isinstance(exc, AppError) and exc.reason in {"command_scope_denied", "client_turn_in_progress"}:
                raise
            self._deps.logger.warning(
                "Coach command failed",
                extra={"event": "coach_command_failed", "context": coach_error_metadata(exc, self._deps.root)},
            )
            receipt = self._deps.failure.persist(client_turn_id, intent, exc)
            if not receipt:
                raise
        return {key: value for key, value in receipt.items() if key != "session_key"}
