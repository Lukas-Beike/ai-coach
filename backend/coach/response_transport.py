"""The model seam: neutral request and turn types, cancellation and one transport."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers.openai_requests import OpenAIResponsesClient
from backend.providers.openai_stream import OpenAIStreamClient


def raise_if_chat_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


@dataclass
class ModelStep:
    """A finished tool round: the model's replayable state and its tool results."""

    opaque_state: list[dict[str, Any]]
    tool_results: list[dict[str, str]]


@dataclass
class ModelRequest:
    """What the Coach asks of a model, independent of the provider's wire format."""

    model: str
    instructions: str
    input: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: str = "auto"
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    # The provider keeps this conversation's items; None resends them every time.
    conversation_id: str | None = None
    stateless: bool = True
    # Earlier tool rounds of this turn, resent when nothing is stored remotely.
    steps: list[ModelStep] = field(default_factory=list)
    # One-shot structured answer, {"name": ..., "schema": ...}: no tools, no steps.
    output_schema: dict[str, Any] | None = None


@dataclass
class ModelTurn:
    """One model answer: its text, requested tool calls and what to replay next."""

    text: str = ""
    # Each call is {"call_id", "name", "arguments" (JSON text)}.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    opaque_state: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    # completed, max_tokens, incomplete, failed, cancelled; "" when not reported.
    stop_reason: str = ""

    @property
    def incomplete(self) -> bool:
        return self.stop_reason in {"max_tokens", "incomplete"}


class CoachResponseTransport:
    """Send a ModelRequest through OpenAI and return its ModelTurn."""

    def __init__(
        self,
        openai_responses: Callable[[], OpenAIResponsesClient],
        openai_stream: Callable[[], OpenAIStreamClient],
        dialect: ModuleType,
    ) -> None:
        self._openai_responses = openai_responses
        self._openai_stream = openai_stream
        # The OpenAI adapter: the one place that knows the Responses wire format.
        self._dialect = dialect

    def request(self, request: ModelRequest) -> ModelTurn:
        response = self._openai_responses().responses(
            self._dialect.request_payload(request)
        )
        return self._dialect.model_turn(response)

    def stream_request(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
        cancel_event: threading.Event | None = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> ModelTurn:
        response = self._openai_stream().stream(
            self._dialect.request_payload(request),
            on_text_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )
        return self._dialect.model_turn(response)
