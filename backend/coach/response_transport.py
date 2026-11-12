"""Cancellation and the Coach's one transport to the model provider."""

from __future__ import annotations

import threading
from collections.abc import Callable

from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers.model_seam import ModelRequest, ModelTurn


def raise_if_chat_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


class CoachResponseTransport:
    """Send a ModelRequest to the selected model's provider; return its ModelTurn."""

    def __init__(
        self,
        complete: Callable[[ModelRequest], ModelTurn],
        stream: Callable[..., ModelTurn],
    ) -> None:
        self._complete = complete
        self._stream = stream

    def request(self, request: ModelRequest) -> ModelTurn:
        return self._complete(request)

    def stream_request(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
        cancel_event: threading.Event | None = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> ModelTurn:
        return self._stream(
            request,
            on_text_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )
