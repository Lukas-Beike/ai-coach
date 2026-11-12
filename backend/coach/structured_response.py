"""Run a bounded structured Coach provider response with durable checkpoints."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from typing import Any

from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.coach.job_store import CoachJobStore
from backend.coach.limits import COACH_LONG_PLAN_MAX_OUTPUT_TOKENS
from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.coach.response_transport import (
    CoachResponseTransport,
    ModelRequest,
    ModelTurn,
    raise_if_chat_cancelled,
)
from backend.errors import AppError


def _discard_delta(_delta: str) -> None:
    """Drop streamed text while no client stream is attached."""


@dataclass
class _ResponseState:
    request_delta_emitted: bool = False

    def emit_delta(
        self, delta: str, *, on_text_delta: Callable[[str], None] | None
    ) -> None:
        self.request_delta_emitted = True
        if on_text_delta is not None:
            on_text_delta(delta)


class CoachStructuredResponseService:
    """Own the streaming provider request, recovery and retry for one response."""

    def __init__(
        self,
        transport: CoachResponseTransport,
        recovery: CoachConversationRecoveryService,
        retry_policy: CoachResponseRetryPolicy,
        jobs: CoachJobStore,
        *,
        reasoning_retry_max_output_tokens: int = COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
    ) -> None:
        self._transport = transport
        self._recovery = recovery
        self._retry_policy = retry_policy
        self._jobs = jobs
        self._reasoning_retry_max_output_tokens = reasoning_retry_max_output_tokens

    def respond(
        self,
        request: ModelRequest,
        *,
        turn_request: ModelRequest,
        context: dict[str, Any],
        message: str,
        command_receipts: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        client_turn_id: str,
        background_owned: bool,
        on_text_delta: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
        recovery_state: dict[str, bool],
    ) -> ModelTurn:
        state = _ResponseState()

        on_delta = partial(state.emit_delta, on_text_delta=on_text_delta)

        def reached(_response_id: str) -> None:
            # The id itself is not kept: a turn is re-requested, never resumed.
            if background_owned:
                self._jobs.merge_receipt(
                    client_turn_id,
                    {
                        "status": "running",
                        "phase": "waiting_openai",
                        "openai_reached": True,
                    },
                )

        attempt = 0
        while attempt < 3:
            raise_if_chat_cancelled(cancel_event)
            try:
                turn = self._transport.stream_request(
                    request,
                    on_delta if on_text_delta is not None else _discard_delta,
                    cancel_event,
                    on_response_id=reached,
                )
            except AppError as exc:
                if not self._recovery.recover_if_invalid(
                    exc,
                    request,
                    turn_request,
                    context=context,
                    message=message,
                    command_receipts=command_receipts,
                    attachments=attachments,
                    recovery_state=recovery_state,
                    request_delta_emitted=state.request_delta_emitted,
                    attempt=attempt,
                ):
                    self._wait_before_retry(
                        exc,
                        state,
                        cancel_event,
                        attempt,
                        remote_conversation=bool(turn_request.conversation_id),
                    )
                attempt += 1
                continue
            if not self._spent_on_reasoning(turn, request, state):
                return turn
            # Reasoning used the whole budget before any text or tool call, so
            # nothing was streamed or executed and the request can be repeated.
            # The larger-budget request does not consume a transport retry, so
            # it is always sent even after earlier retryable failures.
            limit = self._reasoning_retry_max_output_tokens
            request = replace(request, max_output_tokens=limit)
            turn_request.max_output_tokens = limit
        raise AppError(
            502,
            "Der KI-Dienst konnte die Antwort nicht fertigstellen.",
            reason="response_failed",
        )

    def _wait_before_retry(
        self,
        exc: AppError,
        state: _ResponseState,
        cancel_event: threading.Event | None,
        attempt: int,
        *,
        remote_conversation: bool = False,
    ) -> None:
        delay = self._retry_policy.retry_delay(
            exc,
            attempt=attempt,
            request_delta_emitted=state.request_delta_emitted,
            remote_conversation=remote_conversation,
        )
        if delay is None:
            raise exc
        self._retry_policy.wait(delay, cancel_event, attempt, exc.reason)

    def _spent_on_reasoning(
        self, turn: ModelTurn, request: ModelRequest, state: _ResponseState
    ) -> bool:
        return (
            turn.stop_reason == "max_tokens"
            and not state.request_delta_emitted
            # A server-side conversation already stored this input and output.
            and not request.conversation_id
            and not turn.text
            and not turn.tool_calls
            and (request.max_output_tokens or 0)
            < self._reasoning_retry_max_output_tokens
        )
