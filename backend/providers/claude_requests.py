"""Anthropic Messages API transport: one bounded, cancellable SSE request path.

Every Claude request streams, also a one-shot answer whose text deltas nobody
reads: one path owns the byte bound, cancellation, error classification and
usage. Provider error text never leaves this module; only safe reasons do.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.request import Request

from backend.errors import (
    COACH_ABORTED_ERROR,
    AppError,
    ProviderErrorClassifier,
)
from backend.providers import http as provider_http
from backend.providers.claude_messages_adapter import (
    REFUSED_MESSAGE,
    StreamAssembler,
    error_message,
    error_reason,
    model_turn,
    neutral_usage,
    request_betas,
    request_payload,
)
from backend.providers.http import endpoint, urlopen
from backend.providers.model_seam import ModelRequest, ModelTurn

if TYPE_CHECKING:
    from backend.providers.state import ProviderStateService

# The API version every Claude request sends.
ANTHROPIC_VERSION = "2026-10-21"
CLAUDE_MODELS_PATH = "/v1/models"
CLAUDE_MESSAGES_PATH = "/v1/messages"
ANTHROPIC_API_KEY_ERROR = (
    "Kein Anthropic-API-Schlüssel konfiguriert. Hinterlege ihn in der Karte "
    "Claude (Anthropic) unter Mehr › Anbindungen."
)
# The model listing is a small read before a request: it must not hold one up.
MODELS_TIMEOUT_SECONDS = 15
# A server-side search loop may pause; resend it a bounded number of times.
MAX_PAUSE_CONTINUATIONS = 3
_INVALID_EVENT = "Claude hat ein ungültiges Streaming-Ereignis zurückgegeben."


def claude_headers(api_key: str) -> dict[str, str]:
    """The authentication and version headers of one Claude request."""
    return {"x-api-key": api_key.strip(), "anthropic-version": ANTHROPIC_VERSION}


def _dispatch_event(
    data: list[str], on_event: Callable[[dict[str, Any]], None]
) -> None:
    """Decode one event's data lines and apply it; malformed is invalid."""
    try:
        event = json.loads("\n".join(data))
        if not isinstance(event, dict):
            raise TypeError("event")
        on_event(event)
    except (KeyError, TypeError, ValueError) as exc:
        # Not JSON, not an object, or an event for a block that never started.
        raise AppError(502, _INVALID_EVENT, reason="invalid_response") from exc


def _raise_if_cancelled(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise provider_http.ProviderRequestCancelled


def read_sse_events(
    response: Any,
    *,
    max_bytes: int,
    cancel_event: Any,
    on_event: Callable[[dict[str, Any]], None],
) -> int:
    """Read Server-Sent Events within the byte bound; return the bytes read."""
    size = 0
    data: list[str] = []
    while True:
        _raise_if_cancelled(cancel_event)
        # One byte over the remaining budget detects an overlong line.
        line = response.readline(max(1, max_bytes - size + 1))
        # A cancel closes the response, which ends the read: that is no truncation.
        _raise_if_cancelled(cancel_event)
        size += len(line)
        if size > max_bytes:
            raise provider_http.ProviderResponseTooLarge(
                "provider response exceeds configured size limit"
            )
        if not line:
            break
        try:
            text = line.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise AppError(502, _INVALID_EVENT, reason="invalid_response") from exc
        if text.startswith("data:"):
            data.append(text[5:].lstrip())
        elif not text and data:
            _dispatch_event(data, on_event)
            data = []
    if data:
        _dispatch_event(data, on_event)
    return size


@dataclass(frozen=True)
class ClaudeTransportConfig:
    api_key: str
    base_url: str
    default_base_url: str
    # Longest silence while waiting for the next part of a response.
    timeout_seconds: int
    max_response_bytes: int
    app_version: str


class ClaudeMessagesClient:
    """Send ModelRequests to the Anthropic Messages API and return ModelTurns."""

    def __init__(
        self,
        config: ClaudeTransportConfig,
        *,
        provider_state: ProviderStateService,
        logger: Any,
        opener: Any = urlopen,
        clock: Callable[[], float] = time.perf_counter,
        diagnostic_capture: Any = None,
    ) -> None:
        self.config = config
        self.provider_state = provider_state
        self.logger = logger
        self.opener = opener
        self.clock = clock
        self.diagnostic_capture = diagnostic_capture

    def list_models(self) -> Any:
        """One page of the Models API: the newest models are on it."""
        config = self.config
        if not config.api_key.strip():
            raise AppError(
                503, ANTHROPIC_API_KEY_ERROR, reason="anthropic_not_configured"
            )
        request = Request(
            endpoint(
                config.base_url,
                CLAUDE_MODELS_PATH + "?limit=100",
                default_base_url=config.default_base_url,
            ),
            headers=claude_headers(config.api_key),
            method="GET",
        )
        started = self.clock()
        context = {"service": "anthropic", "operation": "models"}
        try:
            return provider_http.request_json(
                request,
                timeout=MODELS_TIMEOUT_SECONDS,
                max_bytes=self.config.max_response_bytes,
                opener=self.opener,
            ).payload
        except HTTPError as exc:
            raise self._http_error(exc, context, started) from exc
        except (OSError, ValueError, provider_http.ProviderInvalidResponse) as exc:
            raise AppError(
                503,
                error_message("provider_unavailable"),
                reason="provider_unavailable",
            ) from exc

    def complete(self, request: ModelRequest) -> ModelTurn:
        """A one-shot answer; its text deltas are dropped."""
        return self.stream(request, lambda _text: None)

    def stream(
        self,
        request: ModelRequest,
        on_text_delta: Callable[[str], None],
        cancel_event: Any = None,
        on_response_id: Callable[[str], None] | None = None,
    ) -> ModelTurn:
        """Stream one request, resuming a paused server-side search loop."""
        if not self.config.api_key.strip():
            raise AppError(
                503, ANTHROPIC_API_KEY_ERROR, reason="anthropic_not_configured"
            )
        payload = request_payload(request, stream=True)
        json_answer = request.json_output or request.output_schema is not None
        paused: list[Any] = []
        message = self._send(payload, on_text_delta, cancel_event, on_response_id)
        for _ in range(MAX_PAUSE_CONTINUATIONS):
            if message.get("stop_reason") != "pause_turn":
                break
            # Resend the paused content as is; the API continues the search.
            paused += message.get("content") or []
            payload = {
                **payload,
                "messages": [
                    *payload["messages"],
                    {"role": "assistant", "content": message.get("content") or []},
                ],
            }
            message = self._send(payload, on_text_delta, cancel_event, on_response_id)
        if message.get("stop_reason") == "refusal":
            raise AppError(502, REFUSED_MESSAGE, reason="refused")
        # One turn: the content before each pause belongs to the answer.
        message = {**message, "content": [*paused, *(message.get("content") or [])]}
        return model_turn(message, json_answer=json_answer)

    def _request(self, payload: dict[str, Any]) -> Request:
        config = self.config
        headers = {
            **claude_headers(config.api_key),
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": f"Pacecraft/{config.app_version}",
        }
        betas = request_betas(payload)
        if betas:
            headers["anthropic-beta"] = ",".join(betas)
        return Request(
            endpoint(
                config.base_url,
                CLAUDE_MESSAGES_PATH,
                default_base_url=config.default_base_url,
            ),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _send(
        self,
        payload: dict[str, Any],
        on_text_delta: Callable[[str], None],
        cancel_event: Any,
        on_response_id: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        assembler = StreamAssembler()
        started = self.clock()
        context = {"service": "anthropic", "model": str(payload.get("model") or "")}

        def on_event(event: dict[str, Any]) -> None:
            text = assembler.feed(event)
            if text:
                on_text_delta(text)
            # The provider has the request: a retry must not repeat its deltas.
            if event.get("type") == "message_start" and on_response_id is not None:
                on_response_id(str((assembler.message or {}).get("id") or ""))

        response: Any = None
        try:
            response = provider_http.open_interruptibly(
                self._request(payload),
                self.config.timeout_seconds,
                cancel_event,
                opener=self.opener,
            )
            with response:
                if cancel_event is not None:
                    cancel_event._provider_response = response
                read_sse_events(
                    response,
                    max_bytes=self.config.max_response_bytes,
                    cancel_event=cancel_event,
                    on_event=on_event,
                )
            message = assembler.result()
        except provider_http.ProviderRequestCancelled as exc:
            self._record("messages_stream_cancelled", assembler, context, started)
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled") from exc
        except HTTPError as exc:
            error = self._http_error(exc, context, started)
            self._record_status(error)
            raise error from exc
        except AppError as exc:
            self._record("messages_stream_failed", assembler, context, started, exc)
            self._record_status(exc)
            raise
        except provider_http.ProviderResponseTooLarge as exc:
            error = AppError(
                502,
                "Die Streaming-Antwort von Claude ist zu groß.",
                reason="response_too_large",
            )
            self._record("messages_stream_failed", assembler, context, started, error)
            self._record_status(error)
            raise error from exc
        except TimeoutError as exc:
            error = AppError(
                504,
                "Claude hat nicht rechtzeitig geantwortet.",
                reason="provider_timeout",
            )
            self._record("messages_stream_failed", assembler, context, started, error)
            self._record_status(error)
            raise error from exc
        except OSError as exc:
            error = AppError(
                503,
                error_message("provider_unavailable"),
                reason="provider_unavailable",
            )
            self._record("messages_stream_failed", assembler, context, started, error)
            self._record_status(error)
            raise error from exc
        finally:
            # Release only the handle this request set.
            if (
                cancel_event is not None
                and response is not None
                and getattr(cancel_event, "_provider_response", None) is response
            ):
                delattr(cancel_event, "_provider_response")
        self._record("messages_stream", assembler, context, started)
        self.provider_state.record_success("anthropic")
        return message

    def _record_status(self, error: AppError) -> None:
        """Keep Claude's last failure, as the OpenAI path does, without its text."""
        self.provider_state.record_status(
            "anthropic",
            state="error",
            reason=error.reason or "request_failed",
            message=error.message,
            http_status=error.upstream_status,
            provider_error_code=None,
        )

    def _record(
        self,
        operation: str,
        assembler: StreamAssembler,
        context: dict[str, Any],
        started: float,
        error: AppError | None = None,
    ) -> None:
        """Bill the usage the stream reported (none when it never started)."""
        message = assembler.message or {}
        usage = neutral_usage(message.get("usage"))
        self.provider_state.record_usage("anthropic", {"usage": usage}, operation)
        details = {
            **context,
            "operation": operation,
            "served_model": str(message.get("model") or ""),
            "stop_reason": str(message.get("stop_reason") or ""),
            "reason": error.reason if error is not None else "ok",
            "duration_ms": round((self.clock() - started) * 1000, 1),
        }
        self.logger.info(
            "Claude request finished",
            extra={"event": "anthropic_request", "context": details},
        )
        if self.diagnostic_capture is not None:
            # Metadata and counters only: no request or response text.
            self.diagnostic_capture.capture(
                "anthropic_stream", {**details, "usage": usage}
            )

    def _http_error(
        self, exc: HTTPError, context: dict[str, Any], started: float
    ) -> AppError:
        raw = provider_http.read_error_body(exc, self.config.max_response_bytes)
        status = int(getattr(exc, "code", 502) or 502)
        try:
            decoded = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
        except json.JSONDecodeError:
            decoded = {}
        error = decoded.get("error") if isinstance(decoded, dict) else None
        reason = error_reason(
            error.get("type") if isinstance(error, dict) else None, status
        )
        retry_after = provider_http.parse_retry_after(
            (getattr(exc, "headers", None) or {}).get("retry-after")
        )
        app_error = ProviderErrorClassifier.classify_upstream(
            error_message(reason),
            reason=reason,
            upstream_status=status,
            retry_after_seconds=int(retry_after) if retry_after is not None else None,
        )
        self.logger.warning(
            "Claude request rejected",
            extra={
                "event": "anthropic_request",
                "context": {
                    **context,
                    "status": status,
                    "reason": reason,
                    "duration_ms": round((self.clock() - started) * 1000, 1),
                },
            },
        )
        return app_error
