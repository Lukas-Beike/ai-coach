"""OpenAI Responses provider internals."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request

from backend import observability
from backend.errors import (
    COACH_ABORTED_ERROR,
    OPENAI_API_KEY_ERROR,
    AppError,
    ClientDisconnected,
    ProviderErrorClassifier,
)
from backend.providers import http as provider_http
from backend.providers.http import urlopen
from backend.providers.openai_errors import (
    _safe_openai_error_token,
    error_details,
    error_diagnostic_details,
    safe_log_reason,
)
from backend.providers.openai_events import StreamReadState, request_stream_response
from backend.providers.openai_requests import (
    _payload_shape,
    endpoint,
    request_with_conversation_retry,
    responses_payload,
)
from backend.providers.openai_responses import (
    response_diagnostic_content,
    response_diagnostic_details,
)

if TYPE_CHECKING:
    from backend.providers.state import ProviderStateService

__all__ = [
    "OpenAIStreamClient",
    "OpenAIStreamConfig",
    "OpenAIStreamTelemetry",
]


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

    def record_started(
        self, context: dict[str, Any], payload: Mapping[str, Any] | None = None
    ) -> None:
        optional_context: dict[str, Any] = {
            key: context[key]
            for key in (
                "model",
                "reasoning_effort",
                "max_output_tokens",
                "tools_count",
                "input_chars",
                "instructions_chars",
                "conversation_present",
            )
            if key in context
        }
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
                "diagnostic_id": context.get("diagnostic_id"),
                "attempt": context.get("attempt"),
                "request_sha256": context.get("request_sha256"),
                "request_shape": _payload_shape(payload),
                **optional_context,
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
                "diagnostic_id": context.get("diagnostic_id"),
                "attempt": context.get("attempt"),
                "provider_response_shape": _payload_shape(response),
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
        diagnostic: Mapping[str, str] | None = None,
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
                    **(diagnostic or {}),
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
        final_response: dict[str, Any] | None = None,
        *,
        state: StreamReadState | None = None,
        level: int = logging.WARNING,
    ) -> None:
        diagnostic = response_diagnostic_details(final_response)
        if state is not None:
            if state.terminal_event_type in {
                "error",
                "response.completed",
                "response.incomplete",
                "response.failed",
            }:
                diagnostic["terminal_event_type"] = state.terminal_event_type
            try:
                request_id = (
                    state.headers.get("x-request-id")
                    if state.headers is not None
                    else None
                )
            except AttributeError, TypeError:
                request_id = None
            if isinstance(request_id, str) and re.fullmatch(
                r"req_[A-Za-z0-9_-]{1,128}", request_id
            ):
                diagnostic["request_id"] = request_id
        self.log_failure(
            context,
            started,
            response_bytes,
            reason,
            status,
            diagnostic=diagnostic,
            level=level,
        )
        self.capture_failure(
            status,
            reason,
            started,
            response_bytes,
            {
                **diagnostic,
                "diagnostic_id": context.get("diagnostic_id"),
                "attempt": context.get("attempt"),
                **response_diagnostic_content(final_response),
                "provider_error": final_response.get("error")
                if isinstance(final_response, dict)
                else None,
                "provider_response": final_response,
            },
        )

    def record_cancelled(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
    ) -> None:
        self.record_usage({"usage": {}}, "responses_stream_cancelled")
        self.log_failure(
            context, started, response_bytes, "chat_cancelled", 499, level=logging.INFO
        )
        self.capture_failure(499, "chat_cancelled", started, response_bytes)

    def record_disconnect(
        self,
        context: dict[str, Any],
        started: float,
        response_bytes: int,
    ) -> None:
        self.log_failure(
            context,
            started,
            response_bytes,
            "client_disconnected",
            499,
            level=logging.INFO,
        )
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
        self.capture_failure(
            status, details["reason"], started, response_bytes, diagnostic
        )


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
            raise AppError(503, OPENAI_API_KEY_ERROR, reason="not_configured")

    def _raise_if_cancelled(self, cancel_event: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise provider_http.ProviderRequestCancelled

    def _record_transport(self, state: StreamReadState) -> None:
        self.telemetry.record_transport(state)

    def _context(
        self,
        body: bytes,
        payload: Mapping[str, Any],
        *,
        diagnostic_id: str,
        attempt: int,
    ) -> dict[str, Any]:
        config = self.config
        parsed = urlparse(
            endpoint(
                config.base_url,
                config.responses_path,
                default_base_url=config.default_base_url,
            )
        )
        context = {
            "service": "openai",
            "method": "POST",
            "host": observability.safe_url_netloc(parsed),
            "path": observability.safe_provider_path(parsed.path),
            "timeout_seconds": config.timeout,
            "request_bytes": len(body),
            "diagnostic_id": diagnostic_id,
            "attempt": attempt,
            "request_sha256": hashlib.sha256(body).hexdigest(),
        }
        model = _safe_openai_error_token(payload.get("model"))
        if model and re.fullmatch(r"gpt-[a-z0-9.-]{1,60}", model):
            context["model"] = model
        reasoning = payload.get("reasoning")
        if isinstance(reasoning, Mapping):
            effort = _safe_openai_error_token(reasoning.get("effort"))
            if effort in {"none", "minimal", "low", "medium", "high", "xhigh"}:
                context["reasoning_effort"] = effort
        max_tokens = payload.get("max_output_tokens")
        if type(max_tokens) is int and 0 <= max_tokens <= 1_000_000:
            context["max_output_tokens"] = max_tokens
        tools = payload.get("tools")
        if isinstance(tools, list):
            context["tools_count"] = len(tools)
        input_value = payload.get("input")
        if isinstance(input_value, str):
            context["input_chars"] = len(input_value)
        elif isinstance(input_value, list):
            context["input_chars"] = len(json.dumps(input_value, ensure_ascii=False))
        instructions = payload.get("instructions")
        if isinstance(instructions, str):
            context["instructions_chars"] = len(instructions)
        context["conversation_present"] = bool(payload.get("conversation"))
        return context

    def _app_error(
        self,
        exc: AppError,
        cancel_event: Any,
        final_response: dict[str, Any] | None,
        context: dict[str, Any],
        started: float,
        stream_bytes: int,
        stream_state: StreamReadState | None = None,
    ) -> NoReturn:
        reason = safe_log_reason(exc.reason or "request_failed")
        if (
            cancel_event is not None
            and cancel_event.is_set()
            and final_response is None
        ):
            self.telemetry.record_usage({"usage": {}}, "responses_stream_cancelled")
        self.telemetry.record_app_error(
            context,
            started,
            stream_bytes,
            reason,
            exc.status,
            final_response,
            state=stream_state,
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
        details = error_details(
            status, raw_error, headers, updated_at=self.telemetry.now()
        )
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
        self.telemetry.diagnostic_capture.capture(
            "openai_http_failed",
            {
                "diagnostic_id": context.get("diagnostic_id"),
                "status": status,
                "response_body": raw_error.decode("utf-8", errors="replace"),
            },
        )
        error = ProviderErrorClassifier.classify_upstream(
            details["message"],
            reason=details["reason"],
            upstream_status=status,
            retry_after_seconds=details.get("retry_after_seconds"),
        )
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
        raise AppError(
            504, "OpenAI hat nicht rechtzeitig geantwortet.", reason="provider_timeout"
        ) from exc

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
        raise AppError(
            503,
            "OpenAI ist vorübergehend nicht verfügbar.",
            reason="provider_unavailable",
        ) from exc

    def _stream_once(
        self,
        payload: Mapping[str, Any],
        on_text_delta: Callable[[str], None],
        *,
        cancel_event: Any,
        on_response_id: Callable[[str], Any] | None,
        attempt_state: dict[str, Any],
        diagnostic_id: str,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        config = self.config
        url = endpoint(
            config.base_url,
            config.responses_path,
            default_base_url=config.default_base_url,
        )
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
        attempt = int(attempt_state.get("attempt", 0)) + 1
        attempt_state["attempt"] = attempt
        context = self._context(
            body, payload, diagnostic_id=diagnostic_id, attempt=attempt
        )
        started = self.telemetry.clock()
        attempt_state.update(
            context=context, started=started, stream_bytes=0, final_response=None
        )
        self.telemetry.record_started(context, payload)
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
                self.telemetry.diagnostic_capture.capture(
                    "openai_stream_transport",
                    {
                        "diagnostic_id": context["diagnostic_id"],
                        "attempt": context["attempt"],
                        "http_status": stream_state.status,
                        "headers": observability.safe_response_headers(
                            stream_state.headers, redact=str
                        ),
                        "response_id": stream_state.response_id,
                        "terminal_event_type": stream_state.terminal_event_type,
                        "event_counts": stream_state.event_counts,
                        "invalid_events": stream_state.invalid_events,
                        "text_delta_chars": stream_state.text_delta_chars,
                        "response_bytes": stream_state.response_bytes,
                    },
                )
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
            final_response = self.telemetry.provider_state.validate_openai_response(
                config.responses_path, final_response
            )
            self.telemetry.record_success(
                final_response, stream_state, started, context
            )
            return final_response
        except AppError as exc:
            self._app_error(
                exc,
                cancel_event,
                attempt_state.get("final_response"),
                context,
                started,
                stream_state.response_bytes,
                stream_state,
            )
        except ClientDisconnected:
            self._disconnect(
                attempt_state.get("final_response"),
                context,
                started,
                stream_state.response_bytes,
            )
        except provider_http.ProviderRequestCancelled:
            self._app_error(
                AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled"),
                cancel_event,
                attempt_state.get("final_response"),
                context,
                started,
                stream_state.response_bytes,
                stream_state,
            )
        except provider_http.ProviderResponseTooLarge:
            self._app_error(
                AppError(
                    502,
                    "Die Streaming-Antwort von OpenAI ist zu groß.",
                    reason="response_too_large",
                ),
                cancel_event,
                attempt_state.get("final_response"),
                context,
                started,
                stream_state.response_bytes,
                stream_state,
            )
        except HTTPError as exc:
            self._http_error(exc, context, started, stream_state.response_bytes)
        except TimeoutError as exc:
            self._timeout(
                exc, cancel_event, context, started, stream_state.response_bytes
            )
        except (OSError, ValueError) as exc:
            self._network(
                exc, cancel_event, context, started, stream_state.response_bytes
            )

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
        diagnostic_id = uuid.uuid4().hex
        try:
            return request_with_conversation_retry(
                lambda: self._stream_once(
                    request_payload,
                    on_text_delta,
                    cancel_event=cancel_event,
                    on_response_id=on_response_id,
                    attempt_state=attempt_state,
                    diagnostic_id=diagnostic_id,
                ),
                cancel_event=cancel_event,
                on_retry=lambda attempt, delay: self.telemetry.record_retry(
                    attempt, delay
                ),
                wait=self.wait,
            )
        except provider_http.ProviderRequestCancelled as exc:
            context = attempt_state.get(
                "context", {"service": "openai", "method": "POST"}
            )
            started = attempt_state.get("started", self.telemetry.clock())
            stream_bytes = attempt_state.get("stream_bytes", 0)
            self.telemetry.record_cancelled(context, started, stream_bytes)
            raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled") from exc
