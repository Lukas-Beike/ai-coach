"""Pure OpenAI Responses API wire adapters."""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.error import HTTPError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen

from backend import observability
from backend.errors import (
    COACH_ABORTED_ERROR,
    OPENAI_API_KEY_ERROR,
    AppError,
    ClientDisconnected,
)
from backend.providers import http as provider_http

if TYPE_CHECKING:
    from backend.providers.state import ProviderStateService

OPENAI_UNEXPECTED_RESPONSE_MESSAGE = "OpenAI hat eine unerwartete Antwort zurückgegeben."

OPENAI_RATE_LIMIT_HEADERS = {
    "retry-after": "retry_after",
    "x-ratelimit-limit-requests": "limit_requests",
    "x-ratelimit-remaining-requests": "remaining_requests",
    "x-ratelimit-reset-requests": "reset_requests",
    "x-ratelimit-limit-tokens": "limit_tokens",
    "x-ratelimit-remaining-tokens": "remaining_tokens",
    "x-ratelimit-reset-tokens": "reset_tokens",
}

_SAFE_LOG_REASONS = {
    "chat_cancelled": "chat_cancelled",
    "client_disconnected": "client_disconnected",
    "conversation_locked": "conversation_locked",
    "conversation_state_invalid": "conversation_state_invalid",
    "credit_balance_exhausted": "credit_balance_exhausted",
    "invalid_response": "invalid_response",
    "provider_timeout": "provider_timeout",
    "request_failed": "request_failed",
    "response_error": "response_error",
    "response_failed": "response_failed",
    "response_too_large": "response_too_large",
    "organization_spend_limit_exceeded": "usage_limit_exceeded",
    "project_spend_limit_exceeded": "usage_limit_exceeded",
    "organization_usage_limit_exceeded": "usage_limit_exceeded",
    "insufficient_quota": "insufficient_quota",
    "rate_limit_exceeded": "rate_limit_exceeded",
    "authentication_or_permission": "authentication_or_permission",
    "not_found": "not_found",
    "provider_unavailable": "provider_unavailable",
    "usage_limit_exceeded": "usage_limit_exceeded",
}


def response_id(value: Any) -> str:
    """Normalize and validate an OpenAI Responses API response identifier."""
    normalized = str(value or "").strip()
    if not re.fullmatch(r"(?a:resp_[\w-]{1,200})", normalized):
        raise AppError(502, "OpenAI hat keine gültige Response-ID zurückgegeben.", reason="invalid_response")
    return normalized


_validate_response_id = response_id


def poll_background_response(
    initial_response: dict[str, Any],
    *,
    retrieve: Callable[[str], dict[str, Any]],
    cancel: Callable[[str], Any],
    cancel_event: Any = None,
    poll_seconds: float,
    max_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    wait: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """Poll one OpenAI background response until it reaches a terminal status."""
    started = monotonic()
    wait = time.sleep if wait is None else wait
    active_response_id = response_id(initial_response.get("id"))
    current = initial_response

    def abort(error: AppError) -> None:
        try:
            cancel(active_response_id)
        except Exception:  # noqa: BLE001, S110 - remote cancellation is best effort
            pass
        raise error

    while str(current.get("status") or "").casefold() in {"queued", "in_progress"}:
        if cancel_event is not None:
            if cancel_event.wait(poll_seconds) or getattr(cancel_event, "is_set", lambda: False)():
                abort(AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled"))
        else:
            wait(poll_seconds)
        if monotonic() - started >= max_seconds:
            abort(AppError(504, "Die Hintergrundplanung hat das Zeitlimit überschritten.", reason="provider_timeout"))
        current = retrieve(active_response_id)
    return current


def _conversation_retry_cancelled(cancel_event: Any) -> bool:
    return cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)()


def _raise_if_conversation_retry_cancelled(cancel_event: Any, cause: BaseException) -> None:
    if _conversation_retry_cancelled(cancel_event):
        raise provider_http.ProviderRequestCancelled from cause


def _wait_for_conversation_retry(
    delay: int,
    cancel_event: Any,
    wait: Callable[[float], Any],
    cause: BaseException,
) -> None:
    if cancel_event is None:
        wait(delay)
    elif cancel_event.wait(delay) or _conversation_retry_cancelled(cancel_event):
        raise provider_http.ProviderRequestCancelled from cause


def request_with_conversation_retry(
    request: Callable[[], Any],
    *,
    cancel_event: Any = None,
    on_retry: Callable[[int, int], None] | None = None,
    wait: Callable[[float], Any] = time.sleep,
    max_attempts: int = 3,
) -> Any:
    """Run a request, retrying only while its conversation is locked."""
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts <= 0:
        raise ValueError("max_attempts must be positive")

    for attempt in range(max_attempts):
        try:
            return request()
        except Exception as exc:
            if getattr(exc, "reason", None) != "conversation_locked" or attempt + 1 >= max_attempts:
                raise
            delay = 2**attempt
            _raise_if_conversation_retry_cancelled(cancel_event, exc)
            if on_retry is not None:
                on_retry(attempt + 1, delay)
            _wait_for_conversation_retry(delay, cancel_event, wait, exc)

    raise AssertionError("unreachable")


class OpenAIResponsesClient:
    """Orchestrate OpenAI Responses calls over the injected provider owners."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        default_base_url: str,
        responses_path: str,
        response_timeout_seconds: int,
        background_poll_seconds: float,
        background_max_seconds: float,
        thinking_level: Callable[[], str],
        http_client: provider_http.JsonHttpClient,
        provider_state: ProviderStateService,
        logger: Any,
        monotonic: Callable[[], float] = time.monotonic,
        wait: Callable[[float], Any] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_base_url = default_base_url
        self.responses_path = responses_path
        self.response_timeout_seconds = response_timeout_seconds
        self.background_poll_seconds = background_poll_seconds
        self.background_max_seconds = background_max_seconds
        self.thinking_level = thinking_level
        self.http_client = http_client
        self.provider_state = provider_state
        self.logger = logger
        self.monotonic = monotonic
        self.wait = wait

    def _require_api_key(self) -> None:
        if not self.api_key:
            raise AppError(503, OPENAI_API_KEY_ERROR)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _send(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: Any = None,
        prepared: bool = False,
    ) -> dict[str, Any]:
        self._require_api_key()
        if prepared:
            request_payload = dict(payload)
        elif path == self.responses_path:
            request_payload = responses_payload(payload, thinking_level=self.thinking_level())
        else:
            request_payload = dict(payload)
        request_kwargs = {
            "headers": self._headers(),
            "timeout": self.response_timeout_seconds,
            "service": "openai",
        }
        if cancel_event is not None:
            request_kwargs["cancel_event"] = cancel_event
        result = self.http_client.request(
            "POST",
            endpoint(self.base_url, path, default_base_url=self.default_base_url),
            request_payload,
            **request_kwargs,
        )
        result = self.provider_state.validate_openai_response(path, result)
        if not isinstance(result, dict):
            raise AppError(502, OPENAI_UNEXPECTED_RESPONSE_MESSAGE)
        if not (path == self.responses_path and request_payload.get("background") is True):
            self.provider_state.record_usage("openai", result, path.strip("/") or "request")
        return result

    def request(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send one OpenAI JSON request and observe its response."""
        return self._send(path, payload)

    def responses(self, payload: Mapping[str, Any], *, cancel_event: Any = None) -> dict[str, Any]:
        """Send a Responses request, retrying only transient conversation locks."""
        request_payload = responses_payload(payload, thinking_level=self.thinking_level())
        return self._responses_prepared(request_payload, cancel_event=cancel_event)

    def retrieve(self, response_id: str) -> dict[str, Any]:
        """Retrieve one background response without exposing its identifier."""
        self._require_api_key()
        normalized_id = _validate_response_id(response_id)
        result = self.http_client.request(
            "GET",
            endpoint(
                self.base_url,
                f"{self.responses_path}/{quote(normalized_id, safe='')}",
                default_base_url=self.default_base_url,
            ),
            headers=self._headers(),
            timeout=self.response_timeout_seconds,
            service="openai",
        )
        result = self.provider_state.validate_openai_response(self.responses_path, result)
        if not isinstance(result, dict):
            raise AppError(502, OPENAI_UNEXPECTED_RESPONSE_MESSAGE)
        return result

    def cancel(self, response_id: str) -> None:
        """Best-effort cancellation for an active background response."""
        if not self.api_key:
            return
        normalized_id = _validate_response_id(response_id)
        try:
            self.http_client.request(
                "POST",
                endpoint(
                    self.base_url,
                    f"{self.responses_path}/{quote(normalized_id, safe='')}/cancel",
                    default_base_url=self.default_base_url,
                ),
                {},
                headers=self._headers(),
                timeout=self.response_timeout_seconds,
                service="openai",
            )
        except Exception:  # noqa: BLE001 - remote cancellation is best effort
            self.logger.warning(
                "OpenAI background response cancellation failed",
                extra={"event": "openai_background_cancel_failed"},
            )

    def background(
        self,
        payload: Mapping[str, Any],
        *,
        response_id: str | None = None,
        on_response_id: Callable[[str], Any] | None = None,
        cancel_event: Any = None,
    ) -> dict[str, Any]:
        """Create or resume a bounded background response and poll it."""
        started = self.monotonic()
        if response_id is not None:
            current = self.retrieve(response_id)
            active_response_id = _validate_response_id(current.get("id") or response_id)
        else:
            request_payload = responses_payload(
                payload,
                thinking_level=self.thinking_level(),
                background=True,
            )
            current = self._responses_prepared(request_payload, cancel_event=cancel_event)
            active_response_id = _validate_response_id(current.get("id"))
            if on_response_id is not None:
                on_response_id(active_response_id)
        remaining_seconds = max(0.0, self.background_max_seconds - (self.monotonic() - started))
        current = poll_background_response(
            {**current, "id": active_response_id},
            retrieve=self.retrieve,
            cancel=self.cancel,
            cancel_event=cancel_event,
            poll_seconds=self.background_poll_seconds,
            max_seconds=remaining_seconds,
            monotonic=self.monotonic,
            wait=self.wait,
        )
        current = self.provider_state.validate_openai_response(self.responses_path, current)
        if not isinstance(current, dict):
            raise AppError(502, OPENAI_UNEXPECTED_RESPONSE_MESSAGE)
        self.provider_state.record_usage("openai", current, "responses_background")
        return current

    def _responses_prepared(self, payload: Mapping[str, Any], *, cancel_event: Any = None) -> dict[str, Any]:
        try:
            return request_with_conversation_retry(
                lambda: self._send(
                    self.responses_path,
                    payload,
                    cancel_event=cancel_event,
                    prepared=True,
                ),
                cancel_event=cancel_event,
                on_retry=lambda attempt, delay: self.logger.warning(
                    "OpenAI conversation is temporarily locked; retrying",
                    extra={
                        "event": "openai_conversation_locked",
                        "context": {"attempt": attempt, "retry_in_seconds": delay},
                    },
                ),
                wait=self.wait,
            )
        except provider_http.ProviderRequestCancelled as exc:
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled") from exc


def responses_payload(
    payload: Mapping[str, Any], *, thinking_level: str, stream: bool = False, background: bool = False
) -> dict[str, Any]:
    """Build an OpenAI Responses API payload without mutating caller state."""
    request_payload = dict(payload)
    request_payload.pop("_ai_provider", None)
    request_payload.setdefault("reasoning", {"effort": thinking_level})
    if stream:
        request_payload["stream"] = True
    if background:
        request_payload["background"] = True
        request_payload["store"] = True
    return request_payload


def endpoint(base_url: Any, path: str, *, default_base_url: str) -> str:
    """Resolve an OpenAI-compatible API path against a configured base URL."""
    base = str(base_url or default_base_url).strip() or default_base_url
    parsed = urlparse(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AppError(500, "OPENAI_BASE_URL muss eine gültige HTTP(S)-Basis-URL ohne Zugangsdaten oder Query-Parameter sein.")
    normalized_path = "/" + str(path or "").lstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + normalized_path, "", "", ""))


def response_failure_reason(path: str, result: Any, responses_path: str = "/responses") -> str | None:
    """Return the normalized wire-level failure, without application side effects."""
    if not isinstance(result, dict):
        return "invalid_response"
    if result.get("error"):
        return "response_error"
    if path != responses_path:
        return None
    status = str(result.get("status") or "").casefold()
    if status in {"failed", "cancelled"}:
        return "response_failed"
    if status and status not in {"completed", "incomplete", "in_progress", "queued"}:
        return "invalid_response_status"
    return None


_RESPONSE_FAILURE_MESSAGES = MappingProxyType(
    {
        "invalid_response": "OpenAI response is not a JSON object.",
        "response_error": "OpenAI returned an error response.",
        "response_failed": "OpenAI did not complete the coach response.",
        "invalid_response_status": "OpenAI returned an unknown response status.",
    }
)


class OpenAIResponseFailure(Exception):
    """Safe, normalized failure from validating an OpenAI response."""

    def __init__(self, reason: str, *, provider_error_code: str | None = None):
        self.reason = reason
        self.message = _RESPONSE_FAILURE_MESSAGES.get(reason, "OpenAI response validation failed.")
        self.provider_error_code = provider_error_code
        super().__init__(self.message)


def validate_response(
    path: str,
    result: Any,
    *,
    responses_path: str = "/responses",
    allowed_error_codes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate a decoded OpenAI response without provider or application side effects."""
    failure = response_failure_reason(path, result, responses_path)
    if failure is None:
        return result

    provider_error_code = None
    if failure == "response_error":
        provider_error = result.get("error")
        code = provider_error.get("code") if isinstance(provider_error, dict) else None
        if isinstance(code, str) and code in allowed_error_codes:
            provider_error_code = code
    raise OpenAIResponseFailure(failure, provider_error_code=provider_error_code)


def _content_text(content: Any) -> str | None:
    if not isinstance(content, dict):
        return None
    if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str) and content["text"]:
        return content["text"]
    if content.get("type") == "refusal" and content.get("refusal"):
        return f"The coach declined to answer: {content['refusal']}"
    return None


def _item_text(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    refusal = _content_text(item) if item.get("type") == "refusal" else None
    if refusal:
        return [refusal]
    if item.get("type") != "message":
        return []
    return [text for content in item.get("content", []) if (text := _content_text(content))]


def response_text(response: dict[str, Any]) -> str:
    """Extract displayable text from a Responses API response."""
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    return "\n".join(text for item in response.get("output", []) for text in _item_text(item)).strip()


def consume_sse_event(
    data_lines: list[str],
    event_name: str,
    on_text_delta: Callable[[str], None],
    on_response_id: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    """Interpret one OpenAI Responses API SSE event without side effects."""
    if not data_lines:
        return None
    event = _decode_sse_event(data_lines)
    if event is None:
        return None
    kind = event_name or str(event.get("type") or "")
    candidate = event.get("response") if isinstance(event.get("response"), dict) else event
    if kind in {"response.created", "response.in_progress"}:
        response_id = str(candidate.get("id") or "").strip()
        if response_id and on_response_id is not None:
            on_response_id(response_id)
    elif kind == "response.output_text.delta":
        delta = event.get("delta")
        if isinstance(delta, str) and delta:
            on_text_delta(delta)
    elif kind in {"response.completed", "response.incomplete", "response.failed"}:
        return candidate
    return None


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
            raise provider_http.ProviderResponseTooLarge("provider response exceeds configured size limit")
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            event_response = consume_sse_event(data_lines, event_name, on_text_delta, on_response_id)
            check_cancelled()
            event_name = ""
            data_lines = []
            if event_response is not None:
                final_response = event_response
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    check_cancelled()
    event_response = consume_sse_event(data_lines, event_name, on_text_delta, on_response_id)
    check_cancelled()
    if event_response is not None:
        final_response = event_response
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
    response = provider_http.open_interruptibly(request, timeout, cancel_event, opener=opener)
    transport_state.status = getattr(response, "status", None) or getattr(response, "code", None) or 200
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
            if cancel_event is not None and getattr(cancel_event, "_provider_response", missing) is response:
                delattr(cancel_event, "_provider_response")


@dataclass(frozen=True)
class OpenAIStreamConfig:
    """Static request and transport settings for the Responses SSE client."""

    api_key: str | None
    base_url: str
    default_base_url: str
    responses_path: str
    timeout: int
    max_bytes: int
    app_version: str
    media_type: str


class OpenAIStreamTelemetry:
    """Persist provider state and emit safe diagnostics for one streaming client."""

    def __init__(
        self,
        provider_state: ProviderStateService,
        diagnostic_capture: Any,
        logger: Any,
        clock: Callable[[], float],
        now: Callable[[], str],
    ) -> None:
        self.provider_state = provider_state
        self.diagnostic_capture = diagnostic_capture
        self.logger = logger
        self.clock = clock
        self.now = now

    def record_usage(self, response: Any, operation: str) -> None:
        self.provider_state.record_usage("openai", response, operation)

    def record_transport(self, state: StreamReadState) -> None:
        if state.headers is not None:
            self.record_rate_limits(state.headers)
        if state.status is not None:
            self.provider_state.record_success("openai", state.status)

    def record_rate_limits(self, headers: Any) -> None:
        self.provider_state.record_rate_limits(headers)

    def record_started(self, context: dict[str, Any]) -> None:
        self.logger.info(
            "External HTTP request started",
            extra={"event": "external_request_started", "context": context},
        )
        self.diagnostic_capture.capture(
            "openai_stream_started",
            {
                "service": "openai",
                "method": "POST",
                "host": context["host"],
                "path": context["path"],
                "request_bytes": context["request_bytes"],
            },
        )

    def record_success(
        self,
        response: dict[str, Any],
        state: StreamReadState,
        started: float,
        context: dict[str, Any],
    ) -> None:
        self.record_usage(response, "responses_stream")
        duration_ms = round((self.clock() - started) * 1000, 1)
        self.diagnostic_capture.capture(
            "openai_stream_completed",
            {
                "service": "openai",
                "status": 200,
                "duration_ms": duration_ms,
                "response_bytes": state.response_bytes,
            },
        )
        self.logger.info(
            "External HTTP request completed",
            extra={
                "event": "external_request_completed",
                "context": {
                    **context,
                    "status": 200,
                    "duration_ms": duration_ms,
                    "response_bytes": state.response_bytes,
                },
            },
        )

    def record_retry(self, attempt: int, delay: int) -> None:
        self.logger.warning(
            "OpenAI streaming conversation is temporarily locked; retrying",
            extra={
                "event": "openai_conversation_locked",
                "context": {"attempt": attempt, "retry_in_seconds": delay},
            },
        )

    def log_failure(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
        reason: str,
        status: int,
        *,
        level: int = logging.WARNING,
    ) -> None:
        self.logger.log(
            level,
            "External HTTP request failed",
            extra={
                "event": "external_request_failed",
                "context": {
                    **context,
                    "status": status,
                    "reason": reason,
                    "duration_ms": round((self.clock() - started) * 1000, 1),
                    "response_bytes": response_bytes,
                },
            },
        )

    def capture_failure(
        self,
        status: int,
        reason: str,
        started: float,
        response_bytes: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "service": "openai",
            "status": status,
            "reason": reason,
            "duration_ms": round((self.clock() - started) * 1000, 1),
            "response_bytes": response_bytes,
        }
        if extra:
            details.update(extra)
        self.diagnostic_capture.capture("openai_stream_failed", details)

    def record_app_error(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
        reason: str,
        status: int,
        *,
        level: int = logging.WARNING,
    ) -> None:
        self.log_failure(context, started, response_bytes, reason, status, level=level)
        self.capture_failure(status, reason, started, response_bytes)

    def record_cancelled(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
    ) -> None:
        self.record_usage({"usage": {}}, "responses_stream_cancelled")
        self.log_failure(context, started, response_bytes, "chat_cancelled", 499, level=logging.INFO)
        self.capture_failure(499, "chat_cancelled", started, response_bytes)

    def record_disconnect(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
    ) -> None:
        self.log_failure(context, started, response_bytes, "client_disconnected", 499, level=logging.INFO)
        self.capture_failure(499, "client_disconnected", started, response_bytes)

    def record_timeout(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
    ) -> None:
        self.provider_state.record_status(
            "openai",
            state="error",
            reason="provider_timeout",
            message="OpenAI hat nicht rechtzeitig geantwortet.",
            http_status=504,
        )
        self.log_failure(context, started, response_bytes, "provider_timeout", 504)
        self.capture_failure(504, "provider_timeout", started, response_bytes)

    def record_network_failure(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
    ) -> None:
        self.provider_state.record_status(
            "openai",
            state="error",
            reason="provider_unavailable",
            message="OpenAI ist vorübergehend nicht verfügbar.",
            http_status=503,
        )
        self.log_failure(context, started, response_bytes, "provider_unavailable", 503)
        self.capture_failure(503, "provider_unavailable", started, response_bytes)

    def record_http_error(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
        status: int,
        details: Mapping[str, Any],
        diagnostic: dict[str, Any],
    ) -> None:
        self.provider_state.record_status(
            "openai",
            state=details["state"],
            reason=details["reason"],
            message=details["message"],
            http_status=details["http_status"],
            provider_error_code=details.get("provider_error_code"),
        )
        self.log_failure(
            context,
            started,
            response_bytes,
            safe_log_reason(details["reason"]),
            status,
        )
        self.capture_failure(status, details["reason"], started, response_bytes, diagnostic)

class OpenAIStreamClient:
    """Own one complete OpenAI Responses SSE request."""

    def __init__(
        self,
        config: OpenAIStreamConfig,
        telemetry: OpenAIStreamTelemetry,
        thinking_level: Callable[[], str],
        opener: Any = urlopen,
        wait: Callable[[float], Any] = time.sleep,
    ) -> None:
        self.config = config
        self.telemetry = telemetry
        self.thinking_level = thinking_level
        self.opener = opener
        self.wait = wait

    def _require_api_key(self) -> None:
        if not self.config.api_key:
            raise AppError(503, OPENAI_API_KEY_ERROR)

    def _raise_if_cancelled(self, cancel_event: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise provider_http.ProviderRequestCancelled

    def _record_transport(self, state: StreamReadState) -> None:
        self.telemetry.record_transport(state)

    def _context(self, body: bytes) -> dict[str, Any]:
        config = self.config
        parsed = urlparse(endpoint(config.base_url, config.responses_path, default_base_url=config.default_base_url))
        context = {
            "service": "openai",
            "method": "POST",
            "host": observability.safe_url_netloc(parsed),
            "path": observability.safe_provider_path(parsed.path),
            "timeout_seconds": config.timeout,
            "request_bytes": len(body),
        }
        return context

    def _app_error(
        self,
        exc: AppError,
        cancel_event: Any,
        final_response: dict[str, Any] | None,
        context: dict[str, Any],
        started: float,
        stream_bytes: int,
    ) -> NoReturn:
        reason = safe_log_reason(exc.reason or "request_failed")
        if cancel_event is not None and cancel_event.is_set() and final_response is None:
            self.telemetry.record_usage({"usage": {}}, "responses_stream_cancelled")
        self.telemetry.record_app_error(
            context,
            started,
            stream_bytes,
            reason,
            exc.status,
            level=logging.INFO if exc.reason == "chat_cancelled" else logging.WARNING,
        )
        raise exc

    def _disconnect(
        self,
        final_response: dict[str, Any] | None,
        context: dict[str, Any],
        started: float,
        stream_bytes: int,
    ) -> NoReturn:
        if final_response is None:
            self.telemetry.record_usage({"usage": {}}, "responses_stream_cancelled")
        self.telemetry.record_disconnect(context, started, stream_bytes)
        raise ClientDisconnected()

    def _http_error(
        self,
        exc: HTTPError,
        context: dict[str, Any],
        started: float,
        stream_bytes: int,
    ) -> NoReturn:
        headers = getattr(exc, "headers", None)
        self.telemetry.record_rate_limits(headers)
        raw_error = provider_http.read_error_body(exc, self.config.max_bytes)
        status = int(getattr(exc, "code", 502) or 502)
        details = error_details(status, raw_error, headers, updated_at=self.telemetry.now())
        diagnostic = error_diagnostic_details(
            raw_error,
            headers,
            max_response_bytes=self.config.max_bytes,
        )
        provider_code = diagnostic.get("error_code")
        if provider_code not in observability.OPENAI_RESPONSE_ERROR_CODES:
            provider_code = None
        details["provider_error_code"] = provider_code
        self.telemetry.record_http_error(
            context,
            started,
            stream_bytes,
            status,
            details,
            diagnostic,
        )
        error = AppError(status, details["message"], reason=details["reason"])
        retry_after = details.get("retry_after_seconds")
        if isinstance(retry_after, int):
            error.retry_after_seconds = retry_after
        raise error from exc

    def _timeout(
        self,
        exc: TimeoutError,
        cancel_event: Any,
        context: dict[str, Any],
        started: float,
        stream_bytes: int,
    ) -> NoReturn:
        if cancel_event is not None and cancel_event.is_set():
            self.telemetry.record_cancelled(context, started, stream_bytes)
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled") from exc
        self.telemetry.record_timeout(context, started, stream_bytes)
        raise AppError(504, "OpenAI hat nicht rechtzeitig geantwortet.", reason="provider_timeout") from exc

    def _network(
        self,
        exc: OSError | ValueError,
        cancel_event: Any,
        context: dict[str, Any],
        started: float,
        stream_bytes: int,
    ) -> NoReturn:
        if cancel_event is not None and cancel_event.is_set():
            self.telemetry.record_cancelled(context, started, stream_bytes)
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled") from exc
        self.telemetry.record_network_failure(context, started, stream_bytes)
        raise AppError(503, "OpenAI ist vorübergehend nicht verfügbar.", reason="provider_unavailable") from exc

    def _stream_once(
        self,
        payload: Mapping[str, Any],
        on_text_delta: Callable[[str], None],
        *,
        cancel_event: Any,
        on_response_id: Callable[[str], Any] | None,
        attempt_state: dict[str, Any],
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        config = self.config
        url = endpoint(config.base_url, config.responses_path, default_base_url=config.default_base_url)
        request = Request(
            url,
            data=body,
            headers={
                "Accept": "text/event-stream",
                "Content-Type": config.media_type,
                "Authorization": f"Bearer {config.api_key}",
                "User-Agent": f"IntervalsCoach/{config.app_version}",
            },
            method="POST",
        )
        context = self._context(body)
        started = self.telemetry.clock()
        attempt_state.update(context=context, started=started, stream_bytes=0, final_response=None)
        self.telemetry.record_started(context)
        stream_state = StreamReadState()
        try:
            self._raise_if_cancelled(cancel_event)
            try:
                result = request_stream_response(
                    request,
                    timeout=config.timeout,
                    max_bytes=config.max_bytes,
                    cancel_event=cancel_event,
                    on_text_delta=on_text_delta,
                    on_response_id=on_response_id,
                    opener=self.opener,
                    state=stream_state,
                )
            finally:
                self._record_transport(stream_state)
            final_response = result.response
            attempt_state["final_response"] = final_response
            attempt_state["stream_bytes"] = stream_state.response_bytes
            self._raise_if_cancelled(cancel_event)
            if final_response is None:
                raise AppError(
                    502,
                    "OpenAI hat keine vollständige Streaming-Antwort zurückgegeben.",
                    reason="invalid_response",
                )
            final_response = self.telemetry.provider_state.validate_openai_response(config.responses_path, final_response)
            self.telemetry.record_success(final_response, stream_state, started, context)
            return final_response
        except AppError as exc:
            self._app_error(
                exc,
                cancel_event,
                attempt_state.get("final_response"),
                context,
                started,
                stream_state.response_bytes,
            )
        except ClientDisconnected:
            self._disconnect(attempt_state.get("final_response"), context, started, stream_state.response_bytes)
        except provider_http.ProviderRequestCancelled:
            self._app_error(
                AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled"),
                cancel_event,
                attempt_state.get("final_response"),
                context,
                started,
                stream_state.response_bytes,
            )
        except provider_http.ProviderResponseTooLarge:
            self._app_error(
                AppError(502, "Die Streaming-Antwort von OpenAI ist zu groß.", reason="response_too_large"),
                cancel_event,
                attempt_state.get("final_response"),
                context,
                started,
                stream_state.response_bytes,
            )
        except HTTPError as exc:
            self._http_error(exc, context, started, stream_state.response_bytes)
        except TimeoutError as exc:
            self._timeout(exc, cancel_event, context, started, stream_state.response_bytes)
        except (OSError, ValueError) as exc:
            self._network(exc, cancel_event, context, started, stream_state.response_bytes)

    def stream(
        self,
        payload: Mapping[str, Any],
        on_text_delta: Callable[[str], None],
        *,
        cancel_event: Any = None,
        on_response_id: Callable[[str], Any] | None = None,
    ) -> dict[str, Any]:
        """Stream one Responses request, retrying only a locked conversation."""
        self._require_api_key()
        request_payload = responses_payload(
            payload,
            thinking_level=self.thinking_level(),
            stream=True,
        )
        attempt_state: dict[str, Any] = {}
        try:
            return request_with_conversation_retry(
                lambda: self._stream_once(
                    request_payload,
                    on_text_delta,
                    cancel_event=cancel_event,
                    on_response_id=on_response_id,
                    attempt_state=attempt_state,
                ),
                cancel_event=cancel_event,
                on_retry=lambda attempt, delay: self.telemetry.record_retry(attempt, delay),
                wait=self.wait,
            )
        except provider_http.ProviderRequestCancelled as exc:
            context = attempt_state.get("context", {"service": "openai", "method": "POST"})
            started = attempt_state.get("started", self.telemetry.clock())
            stream_bytes = attempt_state.get("stream_bytes", 0)
            self.telemetry.record_cancelled(context, started, stream_bytes)
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled") from exc


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


def retry_after_seconds(headers: Any) -> int | None:
    """Parse a bounded numeric Retry-After hint without retaining raw headers."""
    if headers is None:
        return None
    try:
        seconds = float(str(headers.get("retry-after")).strip())
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return max(1, min(math.ceil(seconds), 24 * 60 * 60))


def _safe_openai_error_token(value: Any) -> str | None:
    """Keep a provider error classifier without retaining provider text."""
    token = str(value or "").strip().casefold()
    if not token or len(token) > 160 or not re.fullmatch(r"[a-z0-9_.\[\]-]+", token):
        return None
    return token


def _provider_error_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body) if raw_body else None
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else {}


def error_diagnostic_details(raw_body: bytes, headers: Any = None, *, max_response_bytes: int) -> dict[str, Any]:
    """Return safe OpenAI error metadata; never retain an upstream message/body."""
    error = _provider_error_payload(raw_body)
    max_bytes = max(0, max_response_bytes)
    details: dict[str, Any] = {"error_body_bytes": min(len(raw_body or b""), max_bytes + 1)}
    for source, target in (("code", "error_code"), ("type", "error_type"), ("param", "parameter")):
        token = _safe_openai_error_token(error.get(source))
        if token:
            details[target] = token
    try:
        request_id = _safe_openai_error_token(headers.get("x-request-id")) if headers is not None else None
    except (AttributeError, TypeError):
        request_id = None
    if request_id:
        details["request_id"] = request_id
    return details


def _openai_error_tokens(error: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Return transient normalized tokens used only for OpenAI error classification."""
    code = str(error.get("code") or "").strip().casefold()
    error_type = str(error.get("type") or "").strip().casefold()
    parameter = str(error.get("param") or "").strip().casefold()
    provider_message = str(error.get("message") or "").strip().casefold()
    searchable = f"{code} {error_type} {provider_message}"
    return code, error_type, parameter, provider_message, searchable


def _openai_invalid_input_state(error_type: str, parameter: str, provider_message: str) -> bool:
    """Identify recoverable tool-output and reasoning continuation state errors."""
    return error_type == "invalid_request_error" and parameter.startswith("input") and (
        "no tool output found for function call" in provider_message
        or ("reasoning" in provider_message and "required following item" in provider_message)
    )


def _openai_conversation_error(
    status: int,
    code: str,
    error_type: str,
    parameter: str,
    provider_message: str,
    searchable: str,
) -> tuple[str, str] | None:
    """Classify conversation locking and invalid continuation state separately."""
    if code in {"conversation_locked", "conversation_lock_timeout", "concurrent_request"} or (
        "conversation" in searchable and "lock" in searchable
    ):
        return "conversation_locked", "Die OpenAI-Konversation wird gerade von einer anderen Anfrage verwendet. Bitte kurz warten und erneut versuchen."
    invalid_state = _openai_invalid_input_state(error_type, parameter, provider_message)
    continuation_error = "conversation" in searchable and any(
        marker in searchable for marker in ("state", "previous", "invalid", "not found")
    )
    if status == 400 and (
        code in {"conversation_not_found", "invalid_conversation", "conversation_state_invalid", "invalid_function_call_output"}
        or "function_call_output" in searchable
        or invalid_state
        or continuation_error
    ):
        return "conversation_state_invalid", "Der KI-Dienst konnte den bisherigen Gesprächszustand nicht fortsetzen. Bitte versuche es erneut; dein lokaler Chat bleibt erhalten."
    return None


def _openai_billing_error(code: str, error_type: str, searchable: str) -> tuple[str, str] | None:
    """Classify quota and billing limits before generic rate limiting."""
    if code == "credit_balance_exhausted":
        return "credit_balance_exhausted", "Das OpenAI-Guthaben ist aufgebraucht. Bitte im OpenAI-Billing Guthaben hinzufügen."
    if code in {"organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded"}:
        return code, "Das OpenAI-Ausgaben- oder Nutzungslimit ist erreicht. Bitte das Limit im OpenAI-Konto prüfen."
    if code in {"insufficient_quota", "billing_hard_limit_reached"} or error_type == "insufficient_quota" or any(
        marker in searchable for marker in ("insufficient_quota", "quota", "billing_hard_limit", "credits")
    ):
        return "insufficient_quota", "Das OpenAI-Guthaben bzw. Kontingent ist aufgebraucht. Bitte Guthaben und Abrechnung im OpenAI-Konto prüfen."
    return None


def _openai_error_reason(status: int, error: dict[str, Any]) -> tuple[str, str]:
    """Map safe OpenAI error markers to an athlete-facing recovery action."""
    code, error_type, parameter, provider_message, searchable = _openai_error_tokens(error)
    conversation_error = _openai_conversation_error(status, code, error_type, parameter, provider_message, searchable)
    if conversation_error:
        return conversation_error
    billing_error = _openai_billing_error(code, error_type, searchable)
    if billing_error:
        return billing_error
    if status == 429 or code == "rate_limit_exceeded" or error_type == "rate_limit_exceeded":
        return "rate_limit_exceeded", "OpenAI hat das Anfragelimit erreicht. Bitte kurz warten und erneut versuchen."
    if status in {401, 403} or code in {"invalid_api_key", "invalid_organization", "permission_denied"}:
        return "authentication_or_permission", "Der OpenAI-Zugang wurde abgelehnt. Bitte API-Schlüssel und Projektberechtigungen prüfen."
    if status == 404 or code in {"model_not_found", "not_found"}:
        return "not_found", "Das konfigurierte OpenAI-Modell oder der angeforderte Dienst wurde nicht gefunden."
    if status >= 500:
        return "provider_unavailable", "OpenAI ist vorübergehend nicht verfügbar. Bitte später erneut versuchen."
    return "http_error", f"OpenAI konnte die Anfrage nicht verarbeiten (HTTP {status})."


def error_details(
    status: int,
    raw_body: bytes,
    headers: Any = None,
    *,
    updated_at: str,
) -> dict[str, Any]:
    """Classify an OpenAI error without exposing the provider's raw message."""
    reason, message = _openai_error_reason(status, _provider_error_payload(raw_body))
    details = {
        "state": "error",
        "reason": reason,
        "message": message,
        "http_status": status,
        "updated_at": updated_at,
    }
    retry_after = retry_after_seconds(headers)
    if retry_after is not None:
        details["retry_after_seconds"] = retry_after
    return details


def safe_log_reason(reason: Any) -> str:
    """Project an OpenAI status reason onto static values safe for structured logs."""
    if not isinstance(reason, str):
        return "http_error"
    return _SAFE_LOG_REASONS.get(reason, "http_error")


def rate_limit_snapshot(headers: Any, *, updated_at: str) -> dict[str, Any] | None:
    """Project only the allowlisted OpenAI rate-limit headers."""
    if headers is None:
        return None
    values: dict[str, str] = {}
    for header_name, value_name in OPENAI_RATE_LIMIT_HEADERS.items():
        try:
            value = headers.get(header_name)
        except (AttributeError, TypeError):
            continue
        if value not in (None, ""):
            values[value_name] = str(value)
    return {"updated_at": updated_at, **values} if values else None
