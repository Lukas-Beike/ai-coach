"""Cancellation and the Coach's one transport to the model provider."""

from __future__ import annotations

import threading
from collections.abc import Callable

from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers import openai_responses_adapter as adapter
from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.openai_requests import OpenAIResponsesClient
from backend.providers.openai_stream import OpenAIStreamClient


def raise_if_chat_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


class CoachResponseTransport:
    """Send a ModelRequest through OpenAI and return its ModelTurn."""

    def __init__(
        self,
        openai_responses: Callable[[], OpenAIResponsesClient],
        openai_stream: Callable[[], OpenAIStreamClient],
    ) -> None:
        self._openai_responses = openai_responses
        self._openai_stream = openai_stream

    def request(self, request: ModelRequest) -> ModelTurn:
        return self._openai_responses().complete(request)

    def stream_request(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
        cancel_event: threading.Event | None = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> ModelTurn:
        return adapter.model_turn(
            self._openai_stream().stream(
                adapter.request_payload(request),
                on_text_delta,
                cancel_event=cancel_event,
                on_response_id=on_response_id,
            )
        )
