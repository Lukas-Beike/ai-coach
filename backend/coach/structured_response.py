"""Run a bounded structured Coach provider response with durable checkpoints."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.coach.job_store import CoachJobStore
from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.coach.response_transport import (
    CoachResponseTransport,
    raise_if_chat_cancelled,
)
from backend.errors import AppError


@dataclass
class _ResponseState:
    resume_id: str
    request_delta_emitted: bool = False

    def emit_delta(self, delta: str, *, on_text_delta: Callable[[str], None] | None) -> None:
        self.request_delta_emitted = True
        if on_text_delta is not None:
            on_text_delta(delta)


class CoachStructuredResponseService:
    """Own provider dispatch, resume, recovery and retry for one response."""

    def __init__(
        self,
        transport: CoachResponseTransport,
        recovery: CoachConversationRecoveryService,
        retry_policy: CoachResponseRetryPolicy,
        jobs: CoachJobStore,
    ) -> None:
        self._transport = transport
        self._recovery = recovery
        self._retry_policy = retry_policy
        self._jobs = jobs

    def respond(
        self,
        payload: dict[str, Any],
        *,
        request_payload: dict[str, Any],
        context: dict[str, Any],
        message: str,
        command_receipts: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        client_turn_id: str,
        ai_provider: str,
        background_owned: bool,
        on_text_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
        recovery_state: dict[str, bool],
        resume_id: str = "",
    ) -> dict[str, Any]:
        state = _ResponseState(resume_id)

        on_delta = partial(state.emit_delta, on_text_delta=on_text_delta)

        def checkpoint(response_id: str) -> None:
            state.resume_id = response_id
            self._jobs.merge_receipt(client_turn_id, {
                "status": "running",
                "phase": "waiting_openai",
                "openai_response_id": response_id,
                "pending_tool_outputs": [],
                "response_input": payload["input"] if isinstance(payload["input"], list) else None,
                "previous_response_id": payload.get("previous_response_id"),
            })

        for attempt in range(3):
            raise_if_chat_cancelled(cancel_event)
            try:
                return self._send(
                    payload, resume_id=state.resume_id, checkpoint=checkpoint,
                    on_delta=on_delta, on_text_delta=on_text_delta,
                    cancel_event=cancel_event, background_owned=background_owned,
                    ai_provider=ai_provider,
                )
            except AppError as exc:
                resumed = self._resume_if_possible(
                    exc, payload, state.resume_id, checkpoint, cancel_event,
                    background_owned=background_owned, ai_provider=ai_provider,
                )
                if resumed is not None:
                    return resumed
                if self._recovery.recover_if_invalid(
                    exc, payload, request_payload, context=context, message=message,
                    command_receipts=command_receipts, attachments=attachments,
                    client_turn_id=client_turn_id, ai_provider=ai_provider,
                    recovery_state=recovery_state,
                    request_delta_emitted=state.request_delta_emitted, attempt=attempt,
                ):
                    state.resume_id = ""
                    continue
                delay = self._retry_policy.retry_delay(
                    exc, ai_provider=ai_provider, attempt=attempt,
                    request_delta_emitted=state.request_delta_emitted,
                )
                if delay is None:
                    raise
                state.resume_id = ""
                self._retry_policy.wait(delay, cancel_event, attempt)
        raise AppError(502, "Der KI-Dienst konnte die Antwort nicht fertigstellen.", reason="response_failed")

    def _send(
        self,
        payload: dict[str, Any],
        *,
        resume_id: str,
        checkpoint: Callable[[str], None],
        on_delta: Callable[[str], None],
        on_text_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
        background_owned: bool,
        ai_provider: str,
    ) -> dict[str, Any]:
        if background_owned and on_text_delta is None:
            return self._transport.background_request(
                payload, response_id=resume_id or None,
                on_response_id=checkpoint, cancel_event=cancel_event,
            )
        if on_text_delta is None:
            return self._transport.request(payload)
        return self._transport.stream_request(
            payload, on_delta, cancel_event,
            on_response_id=checkpoint if background_owned and ai_provider == "openai" else None,
        )

    def _resume_if_possible(
        self,
        exc: AppError,
        payload: dict[str, Any],
        resume_id: str,
        checkpoint: Callable[[str], None],
        cancel_event: threading.Event | None,
        *,
        background_owned: bool,
        ai_provider: str,
    ) -> dict[str, Any] | None:
        resumable = (
            background_owned and ai_provider == "openai" and resume_id
            and exc.reason in {"provider_unavailable", "provider_timeout", "invalid_response"}
            and (cancel_event is None or not cancel_event.is_set())
        )
        if not resumable:
            return None
        return self._transport.background_request(
            payload, response_id=resume_id, on_response_id=checkpoint,
            cancel_event=cancel_event,
        )
