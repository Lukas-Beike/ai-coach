"""OpenAI Responses provider internals."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.errors import AppError
from backend.providers import http as provider_http
from backend.providers.http import urlopen

__all__ = [
    "StreamReadResult",
    "StreamReadState",
    "consume_sse_event",
    "read_stream_response",
    "request_stream_response",
]


def _terminal_sse_response(
    kind: str, event: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    return event if kind == "error" else candidate


def consume_sse_event(
    data_lines: list[str],
    event_name: str,
    on_text_delta: Callable[[str], None],
    on_response_id: Callable[[str], None] | None = None,
    state: StreamReadState | None = None,
) -> dict[str, Any] | None:
    """Interpret one OpenAI Responses API SSE event without side effects."""
    if not data_lines:
        return None
    try:
        event = _decode_sse_event(data_lines)
    except AppError:
        if state is not None:
            state.invalid_events += 1
        raise
    if event is None:
        return None
    kind = event_name or str(event.get("type") or "")
    _record_sse_event(state, kind)
    response_candidate = event.get("response")
    candidate = response_candidate if isinstance(response_candidate, dict) else event
    if state is not None and isinstance(candidate.get("id"), str):
        state.response_id = candidate["id"]
    if kind in {"response.created", "response.in_progress"}:
        _handle_sse_response_id(candidate, state, on_response_id)
    elif kind == "response.output_text.delta":
        _handle_sse_delta(event, state, on_text_delta)
    elif kind in {
        "error",
        "response.completed",
        "response.incomplete",
        "response.failed",
    }:
        return _terminal_sse_response(kind, event, candidate)
    return None


def _record_sse_event(state: StreamReadState | None, kind: str) -> None:
    if state is None:
        return
    marker = kind if re.fullmatch(r"[a-z_.]{1,100}", kind) else "unknown"
    state.event_counts[marker] = state.event_counts.get(marker, 0) + 1


def _handle_sse_response_id(
    candidate: dict[str, Any],
    state: StreamReadState | None,
    callback: Callable[[str], None] | None,
) -> None:
    response_id = str(candidate.get("id") or "").strip()
    if state is not None:
        state.response_id = response_id
    if response_id and callback is not None:
        callback(response_id)


def _handle_sse_delta(
    event: dict[str, Any],
    state: StreamReadState | None,
    callback: Callable[[str], None],
) -> None:
    delta = event.get("delta")
    if not isinstance(delta, str) or not delta:
        return
    if state is not None:
        state.text_delta_chars += len(delta)
    callback(delta)


@dataclass(frozen=True)
class StreamReadResult:
    """The terminal response and wire bytes consumed by an SSE stream reader."""

    response: dict[str, Any] | None
    response_bytes: int


@dataclass
class StreamReadState:
    """Open response metadata and observable stream progress."""

    response_bytes: int = 0
    status: int | None = None
    headers: Any = None
    terminal_event_type: str | None = None
    response_id: str = ""
    event_counts: dict[str, int] = field(default_factory=dict)
    invalid_events: int = 0
    text_delta_chars: int = 0


def _consume_sse_line(
    line: str,
    event_name: str,
    data_lines: list[str],
    on_text_delta: Callable[[str], None],
    on_response_id: Callable[[str], None] | None,
    state: StreamReadState | None = None,
) -> tuple[str, list[str], dict[str, Any] | None, str | None]:
    if not line:
        event_response = consume_sse_event(
            data_lines, event_name, on_text_delta, on_response_id, state
        )
        terminal_type = event_name
        if event_response is not None and not terminal_type:
            event = _decode_sse_event(data_lines)
            terminal_type = str(event.get("type") or "") if event else ""
        return (
            "",
            [],
            event_response,
            terminal_type,
        )
    if line.startswith("event:"):
        return line[6:].strip(), data_lines, None, None
    if line.startswith("data:"):
        data_lines.append(line[5:].lstrip())
        return event_name, data_lines, None, None
    return event_name, data_lines, None, None


def read_stream_response(
    response: Any,
    *,
    max_bytes: int,
    cancel_event: Any = None,
    on_text_delta: Callable[[str], None],
    on_response_id: Callable[[str], None] | None = None,
    state: StreamReadState | None = None,
) -> StreamReadResult:
    """Read and parse an OpenAI SSE response without owning its lifecycle."""

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise provider_http.ProviderRequestCancelled

    final_response: dict[str, Any] | None = None
    event_name = ""
    data_lines: list[str] = []
    read_state = state or StreamReadState()
    check_cancelled()
    for raw_line in response:
        check_cancelled()
        read_state.response_bytes += len(raw_line)
        if read_state.response_bytes > max_bytes:
            raise provider_http.ProviderResponseTooLarge(
                "provider response exceeds configured size limit"
            )
        line = raw_line.decode("utf-8").rstrip("\r\n")
        event_name, data_lines, event_response, terminal_event_type = _consume_sse_line(
            line, event_name, data_lines, on_text_delta, on_response_id, read_state
        )
        check_cancelled()
        if event_response is not None:
            final_response = event_response
            read_state.terminal_event_type = terminal_event_type or str(
                event_response.get("type") or ""
            )
    check_cancelled()
    _, _, event_response, terminal_event_type = _consume_sse_line(
        "", event_name, data_lines, on_text_delta, on_response_id, read_state
    )
    check_cancelled()
    if event_response is not None:
        final_response = event_response
        read_state.terminal_event_type = terminal_event_type or str(
            event_response.get("type") or ""
        )
    return StreamReadResult(final_response, read_state.response_bytes)


def request_stream_response(
    request: Any,
    *,
    timeout: int,
    max_bytes: int,
    cancel_event: Any = None,
    on_text_delta: Callable[[str], None],
    on_response_id: Callable[[str], None] | None = None,
    opener: Any = urlopen,
    state: StreamReadState | None = None,
) -> StreamReadResult:
    """Open, read, and close an OpenAI SSE response."""
    transport_state = state or StreamReadState()
    response = provider_http.open_interruptibly(
        request, timeout, cancel_event, opener=opener
    )
    transport_state.status = (
        getattr(response, "status", None) or getattr(response, "code", None) or 200
    )
    transport_state.headers = getattr(response, "headers", None)
    with response:
        if cancel_event is not None:
            cancel_event._provider_response = response
        try:
            return read_stream_response(
                response,
                max_bytes=max_bytes,
                cancel_event=cancel_event,
                on_text_delta=on_text_delta,
                on_response_id=on_response_id,
                state=transport_state,
            )
        finally:
            missing = object()
            if (
                cancel_event is not None
                and getattr(cancel_event, "_provider_response", missing) is response
            ):
                delattr(cancel_event, "_provider_response")



def _decode_sse_event(data_lines: list[str]) -> dict[str, Any] | None:
    raw_event = "\n".join(data_lines)
    if raw_event.strip() == "[DONE]":
        return None
    try:
        event = json.loads(raw_event)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AppError(
            502,
            "OpenAI hat ein ungültiges Streaming-Ereignis zurückgegeben.",
            reason="invalid_response",
        ) from exc
    if not isinstance(event, dict):
        raise AppError(
            502,
            "OpenAI hat ein ungültiges Streaming-Ereignis zurückgegeben.",
            reason="invalid_response",
        )
    return event
