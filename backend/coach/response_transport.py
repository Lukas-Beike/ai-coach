"""Provider selection, cancellation and transport for structured Coach responses."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from backend.coach.conversation import GeminiConversationResponseService
from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers.openai import OpenAIResponsesClient, OpenAIStreamClient
from backend.settings import SettingsService


def raise_if_chat_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


class CoachResponseTransport:
    """Route one response to the configured provider without server callbacks."""

    def __init__(
        self,
        settings: SettingsService,
        openai_responses: Callable[[], OpenAIResponsesClient],
        openai_stream: Callable[[], OpenAIStreamClient],
        gemini_responses: Callable[[], GeminiConversationResponseService],
    ) -> None:
        self._settings = settings
        self._openai_responses = openai_responses
        self._openai_stream = openai_stream
        self._gemini_responses = gemini_responses

    def provider(self, payload: dict[str, Any]) -> str:
        provider = str(payload.get("_ai_provider") or "").casefold()
        return provider if provider in {"openai", "gemini"} else self._settings.selected_ai_provider()

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.provider(payload) == "gemini":
            return self._gemini_responses().request(payload)
        return self._openai_responses().responses(payload)

    def background_request(
        self,
        payload: dict[str, Any],
        *,
        response_id: str | None = None,
        on_response_id: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if self.provider(payload) == "gemini":
            raise_if_chat_cancelled(cancel_event)
            result = self._gemini_responses().request(payload, cancel_event=cancel_event)
            raise_if_chat_cancelled(cancel_event)
            return result
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
        if self.provider(payload) == "gemini":
            raise_if_chat_cancelled(cancel_event)
            result = self._gemini_responses().stream(payload, on_text_delta, cancel_event)
            raise_if_chat_cancelled(cancel_event)
            return result
        return self._openai_stream().stream(
            payload,
            on_text_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )
