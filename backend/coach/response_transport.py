"""Cancellation and the Coach's one transport to the model provider."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from backend.errors import COACH_ABORTED_ERROR, AppError
from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.usage import openai_cached_input_tokens

TURN_USAGE_FIELDS = ("requests", "input_tokens", "cached_input_tokens", "output_tokens")
# The usage of the Coach turn running in this thread; None outside a turn.
_TURN_USAGE: ContextVar[dict[str, int] | None] = ContextVar(
    "coach_turn_usage", default=None
)


def _count(value: Any) -> int:
    return value if type(value) is int and value > 0 else 0


@contextmanager
def metered_turn(stored: Any = None) -> Iterator[None]:
    """Sum every model call of a turn; a resumed turn continues its stored usage."""
    seed = stored if isinstance(stored, dict) else {}
    token = _TURN_USAGE.set({key: _count(seed.get(key)) for key in TURN_USAGE_FIELDS})
    try:
        yield
    finally:
        _TURN_USAGE.reset(token)


def turn_usage() -> dict[str, int] | None:
    """The running turn's usage so far, or None outside a metered turn."""
    usage = _TURN_USAGE.get()
    return dict(usage) if usage is not None else None


def _metered(turn: ModelTurn) -> ModelTurn:
    usage = _TURN_USAGE.get()
    if usage is not None:
        raw = turn.usage if isinstance(turn.usage, dict) else {}
        usage["requests"] += 1
        usage["input_tokens"] += _count(raw.get("input_tokens"))
        usage["cached_input_tokens"] += openai_cached_input_tokens({"usage": raw})
        usage["output_tokens"] += _count(raw.get("output_tokens"))
    return turn


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
        return _metered(self._complete(request))

    def stream_request(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
        cancel_event: threading.Event | None = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> ModelTurn:
        return _metered(
            self._stream(
                request,
                on_text_delta,
                cancel_event=cancel_event,
                on_response_id=on_response_id,
            )
        )
