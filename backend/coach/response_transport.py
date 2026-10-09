"""Cancellation and transport for structured Coach responses."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers.openai import OpenAIResponsesClient, OpenAIStreamClient


def raise_if_chat_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


class CoachResponseTransport:
    """Send one response through OpenAI without server callbacks."""

    def __init__(
        self,
        openai_responses: Callable[[], OpenAIResponsesClient],
        openai_stream: Callable[[], OpenAIStreamClient],
    ) -> None:
        self._openai_responses = openai_responses
        self._openai_stream = openai_stream

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._openai_responses().responses(payload)

    def background_request(
        self,
        payload: dict[str, Any],
        *,
        response_id: str | None = None,
        on_response_id: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        return self._openai_responses().background(
            payload,
            response_id=response_id,
            on_response_id=on_response_id,
            cancel_event=cancel_event,
        )

    def stream_request(
        self,
        payload: dict[str, Any],
        on_text_delta: Callable[[str], None],
        cancel_event: threading.Event | None = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        return self._openai_stream().stream(
            payload,
            on_text_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )
