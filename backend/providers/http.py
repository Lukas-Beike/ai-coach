"""Shared, dependency-light provider HTTP error contracts.

The application decides how errors are presented. Provider modules only need a
bounded, secret-free classification that can be persisted or translated into
an application error by their caller.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from backend import observability
from backend.errors import COACH_ABORTED_ERROR, AppError, provider_error

_SECRET_PATTERNS = (
    (re.compile(r"(?i)https?://[^\s<>\"'`]+"), "[REDACTED_URL]"),
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(basic|bearer)\s+[^\s,\"'}]+"), r"\1[REDACTED]"),
)


class ProviderRequestCancelled(Exception):
    """Transport-level signal for a provider request cancelled by its caller."""


class ProviderResponseTooLarge(ValueError):
    """Transport-level signal for a response exceeding its configured limit."""


class ProviderInvalidResponse(Exception):
    """Transport-level signal for a response that is not UTF-8 JSON."""


@dataclass(frozen=True)
class JsonResponse:
    """Bounded, decoded JSON response metadata."""

    payload: Any
    status: int
    headers: Any
    response_bytes: int


_INVALID_JSON_MESSAGE = "provider response is not valid UTF-8 JSON"


def _close_response(response: Any) -> None:
    if response is None:
        return
    try:
        response.close()
    except Exception:  # noqa: BLE001
        return


class _OpenState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cancelled = False
        self.has_response = False
        self.response: Any = None
        self.error: Exception | None = None

    def save_response(self, response: Any) -> bool:
        with self.lock:
            if self.cancelled:
                return False
            self.response = response
            self.has_response = True
            return True

    def save_error(self, error: Exception) -> None:
        with self.lock:
            if not self.cancelled:
                self.error = error

    def cancel(self) -> tuple[bool, Any]:
        with self.lock:
            self.cancelled = True
            if not self.has_response:
                return False, None
            response = self.response
            self.has_response = False
            return True, response

    def result(self) -> tuple[Any, Exception | None]:
        with self.lock:
            return self.response, self.error


def _open_request(opener: Any, request: Any, timeout: int, state: _OpenState, completed: threading.Event) -> None:
    try:
        response = opener(request, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        state.save_error(exc)
    else:
        if not state.save_response(response):
            _close_response(response)
    finally:
        completed.set()


def _cancel_open(state: _OpenState) -> None:
    has_response, response = state.cancel()
    if has_response:
        _close_response(response)


def open_interruptibly(
    request: Any,
    timeout: int,
    cancel_event: Any = None,
    *,
    opener: Any = urlopen,
    poll_seconds: float = 0.1,
) -> Any:
    """Open a provider request while allowing header-wait cancellation."""
    if cancel_event is None:
        return opener(request, timeout=timeout)

    completed = threading.Event()
    state = _OpenState()
    threading.Thread(
        target=_open_request,
        args=(opener, request, timeout, state, completed),
        name="provider-header-wait",
        daemon=True,
    ).start()

    while not completed.wait(poll_seconds):
        if cancel_event.is_set():
            _cancel_open(state)
            raise ProviderRequestCancelled

    if cancel_event.is_set():
        _cancel_open(state)
        raise ProviderRequestCancelled
    response, error = state.result()
    if error is not None:
        raise error
    return response


def request_body(payload: Any | None, raw_body: bytes | None) -> bytes | None:
    """Encode a JSON payload unless an already encoded body was provided."""
    if raw_body is not None and payload is not None:
        raise ValueError("payload and raw_body are mutually exclusive")
    if raw_body is not None:
        return raw_body
    return json.dumps(payload).encode("utf-8") if payload is not None else None


def json_request_parts(
    method: str,
    url: str,
    *,
    payload: Any | None = None,
    raw_body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: int = 45,
    service: str | None = None,
    content_type: str | None = None,
    app_version: str,
    operation_context: Mapping[str, Any] | None = None,
) -> tuple[Request, Any, dict[str, str], dict[str, Any]]:
    """Build a JSON provider request and its safe diagnostic context."""
    body = request_body(payload, raw_body)
    request_headers = {"Accept": "application/json", "User-Agent": f"IntervalsCoach/{app_version}"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    if content_type is not None and body is not None:
        request_headers["Content-Type"] = content_type

    parsed_url = urlparse(url)
    request = Request(url, data=body, headers=request_headers, method=method)
    request_context: dict[str, Any] = {
        "service": service or parsed_url.netloc,
        "method": method.upper(),
        "host": parsed_url.netloc,
        "path": observability.safe_provider_path(parsed_url.path),
        "timeout_seconds": timeout,
        "request_bytes": len(body or b""),
    }
    if operation_context:
        for key in ("operation_id", "trigger"):
            if key in operation_context:
                request_context[key] = operation_context[key]
        request_context["phase"] = operation_context.get(
            "phase", request_context["path"].rsplit("/", 1)[-1] or "request"
        )
    if parsed_url.query:
        request_context["query_keys"] = sorted(parse_qs(parsed_url.query, keep_blank_values=True))
    return request, parsed_url, request_headers, request_context


def read_error_body(error: Any, max_bytes: int) -> bytes:
    """Read at most ``max_bytes + 1`` bytes and close the error response."""
    try:
        try:
            raw = error.read(max_bytes + 1)
        except TypeError:
            raw = error.read()
        return raw[: max_bytes + 1]
    finally:
        error.close()


def multipart_form_data(
    fields: list[tuple[str, str]],
    file_field: str,
    filename: str,
    file_content_type: str,
    file_data: bytes,
    *,
    boundary_token: str | None = None,
) -> tuple[bytes, str]:
    """Build a bounded multipart request without persisting the uploaded data."""
    boundary = "----IntervalsCoach" + (boundary_token if boundary_token is not None else secrets.token_hex(16))
    boundary_bytes = boundary.encode("ascii")
    parts: list[bytes] = []
    for name, value in fields:
        parts.extend((b"--" + boundary_bytes + b"\r\n",))
        parts.extend((f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),))
        parts.extend((value.encode("utf-8"), b"\r\n"))
    parts.extend((b"--" + boundary_bytes + b"\r\n",))
    parts.extend((
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("ascii"),
        f"Content-Type: {file_content_type}\r\n\r\n".encode("ascii"),
        file_data,
        b"\r\n--" + boundary_bytes + b"--\r\n",
    ))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def redact_provider_text(value: Any, *, limit: int = 500) -> str:
    """Return bounded provider detail without credentials or control noise."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:limit]


@dataclass(frozen=True)
class ProviderHTTPError(Exception):
    """Safe provider failure data; raw response bodies never belong here."""

    service: str
    category: str
    status: int | None = None
    detail: str = ""
    retry_after: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", redact_provider_text(self.detail))

    def __str__(self) -> str:
        status = f" HTTP {self.status}" if self.status else ""
        detail = f": {self.detail}" if self.detail else ""
        return f"{self.service} {self.category}{status}{detail}"


def classify_provider_status(status: int, service: str, detail: Any = "") -> ProviderHTTPError:
    """Classify an HTTP response without leaking its body to callers."""
    category = {429: "rate_limited", 401: "authentication", 403: "authentication"}.get(status, "http")
    return ProviderHTTPError(service, category, status, redact_provider_text(detail))


def read_bounded_response(response: Any, max_bytes: int, *, before_read: Any = None) -> bytes:
    """Read a provider response without accepting oversized bodies."""
    if before_read is not None:
        before_read()
    try:
        try:
            raw = response.read(max_bytes + 1)
        except TypeError:
            raw = response.read()
    finally:
        if before_read is not None:
            before_read()
    if len(raw) > max_bytes:
        raise ProviderResponseTooLarge("provider response exceeds configured size limit")
    return raw


def read_response(response: Any, max_bytes: int, cancel_event: Any = None) -> bytes:
    """Read a bounded provider response while honoring caller cancellation."""
    if cancel_event is None:
        return read_bounded_response(response, max_bytes)

    def check_cancelled() -> None:
        if cancel_event.is_set():
            raise ProviderRequestCancelled

    check_cancelled()
    cancel_event._provider_response = response
    try:
        raw = read_bounded_response(response, max_bytes, before_read=check_cancelled)
        check_cancelled()
        return raw
    finally:
        missing = object()
        if getattr(cancel_event, "_provider_response", missing) is response:
            delattr(cancel_event, "_provider_response")


def request_json(
    request: Any,
    *,
    timeout: int,
    max_bytes: int,
    cancel_event: Any = None,
    opener: Any = urlopen,
) -> JsonResponse:
    """Execute one bounded provider request and decode its JSON response."""
    with open_interruptibly(request, timeout, cancel_event, opener=opener) as response:
        raw_body = read_response(response, max_bytes, cancel_event)
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderInvalidResponse(_INVALID_JSON_MESSAGE) from None
        status = getattr(response, "status", None) or getattr(response, "code", None) or 200
        return JsonResponse(payload, status, getattr(response, "headers", None), len(raw_body))


class JsonHttpClient:
    """Execute one observed, bounded JSON request without application globals."""

    def __init__(
        self,
        app_version: str,
        max_response_bytes: int,
        logger: Any,
        diagnostic_capture: Any,
        provider_state: Any,
        redact_text: Any,
        safe_response_headers: Any,
        now: Any,
        operation_context: Callable[[], Mapping[str, Any] | None],
        *,
        opener: Any = urlopen,
        monotonic: Any = time.perf_counter,
    ) -> None:
        self.app_version = app_version
        self.max_response_bytes = max_response_bytes
        self.logger = logger
        self.diagnostic_capture = diagnostic_capture
        self.provider_state = provider_state
        self.redact_text = redact_text
        self.safe_response_headers = safe_response_headers
        self.now = now
        self.operation_context = operation_context
        self.opener = opener
        self.monotonic = monotonic

    def request(
        self,
        method: str,
        url: str,
        payload: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: int = 45,
        service: str | None = None,
        raw_body: bytes | None = None,
        content_type: str | None = None,
        cancel_event: Any = None,
    ) -> Any:
        request, parsed_url, request_headers, request_context = json_request_parts(
            method,
            url,
            payload=payload,
            raw_body=raw_body,
            headers=headers,
            timeout=timeout,
            service=service,
            content_type=content_type,
            app_version=self.app_version,
            operation_context=self.operation_context() if self.operation_context is not None else None,
        )
        # Drop URL userinfo before metadata reaches logs or diagnostics.
        request_context = {
            **request_context,
            "service": service or observability.safe_url_netloc(parsed_url),
            "host": observability.safe_url_netloc(parsed_url),
        }
        started = self.monotonic()
        self.logger.info(
            "External HTTP request started",
            extra={"event": "external_request_started", "context": request_context},
        )
        self.diagnostic_capture.capture("external_http_started", {
            "service": request_context["service"],
            "method": request_context["method"],
            "host": observability.safe_url_netloc(parsed_url),
            "path": request_context["path"],
            "query_keys": request_context.get("query_keys", []),
            "request_bytes": request_context["request_bytes"],
            "content_type": request_headers.get("Content-Type"),
        })
        try:
            self._raise_cancelled(cancel_event)
            response = request_json(
                request,
                timeout=timeout,
                max_bytes=self.max_response_bytes,
                cancel_event=cancel_event,
                opener=self.opener,
            )
            self._raise_cancelled(cancel_event)
            return self._success(response, service, request_context, parsed_url, started)
        except ProviderRequestCancelled as exc:
            raise self._cancelled_error(request_context, parsed_url, started) from exc
        except ProviderResponseTooLarge as exc:
            error = AppError(502, "Die Antwort des externen Dienstes ist zu groß.")
            self._capture_failure(request_context, parsed_url, started, error)
            raise error from exc
        except HTTPError as exc:
            self._http_error(exc, service, request_context, parsed_url, started, cancel_event)
        except (OSError, ValueError) as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise self._cancelled_error(request_context, parsed_url, started) from exc
            if service == "openai":
                self.provider_state.record_status(
                    "openai",
                    state="error",
                    reason="network_error",
                    message="OpenAI ist nicht erreichbar. Bitte Netzwerkverbindung prüfen und später erneut versuchen.",
                )
            self.logger.exception(
                "Upstream service is unavailable",
                extra={
                    "event": "upstream_network_error",
                    "context": self._failure_context(request_context, started, exc),
                },
            )
            self._capture_failure(request_context, parsed_url, started, exc)
            raise provider_error(service, "network") from exc
        except AppError as exc:
            self._capture_failure(request_context, parsed_url, started, exc)
            raise
        except Exception as exc:
            if service == "openai":
                self.provider_state.record_status(
                    "openai",
                    state="error",
                    reason="client_error",
                    message="Die OpenAI-Antwort konnte nicht verarbeitet werden. Bitte später erneut versuchen.",
                )
            self.logger.exception(
                "External HTTP request failed while processing response",
                extra={
                    "event": "external_request_failed",
                    "context": self._failure_context(request_context, started, exc),
                },
            )
            self._capture_failure(request_context, parsed_url, started, exc)
            raise provider_error(service, "client") from exc

    def _raise_cancelled(self, cancel_event: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ProviderRequestCancelled

    def _cancelled_error(self, request_context: dict[str, Any], parsed_url: Any, started: float) -> AppError:
        error = AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")
        self._capture_failure(request_context, parsed_url, started, error)
        return error

    def _safe_error_code(self, error: BaseException) -> str:
        return _external_call_error_code(error)

    def _failure_context(
        self, request_context: dict[str, Any], started: float, error: BaseException,
    ) -> dict[str, Any]:
        return {
            **request_context,
            "duration_ms": round((self.monotonic() - started) * 1000, 1),
            "error_type": type(error).__name__,
            "error_code": self._safe_error_code(error),
            "error": self.redact_text(str(error))[:500],
        }

    def _capture_failure(
        self,
        request_context: dict[str, Any],
        parsed_url: Any,
        started: float,
        error: BaseException,
        *,
        error_bytes: int | None = None,
        headers: Any = None,
    ) -> None:
        context: dict[str, Any] = {
            "service": request_context["service"],
            "method": request_context["method"],
            "host": observability.safe_url_netloc(parsed_url),
            "path": request_context["path"],
            "duration_ms": round((self.monotonic() - started) * 1000, 1),
            "error": observability.safe_diagnostic_error(error),
        }
        if error_bytes is not None:
            context["error_bytes"] = error_bytes
        if headers is not None:
            context["headers"] = self.safe_response_headers(headers)
        self.diagnostic_capture.capture("external_http_failed", context)

    def _success(
        self,
        response: JsonResponse,
        service: str | None,
        request_context: dict[str, Any],
        parsed_url: Any,
        started: float,
    ) -> Any:
        result = response.payload if response.response_bytes else None
        if service == "openai":
            self.provider_state.record_rate_limits(response.headers)
            self.provider_state.record_success("openai", response.status)
        duration_ms = round((self.monotonic() - started) * 1000, 1)
        self.logger.info(
            "External HTTP request completed",
            extra={
                "event": "external_request_completed",
                "context": {
                    **request_context,
                    "status": response.status,
                    "duration_ms": duration_ms,
                    "response_bytes": response.response_bytes,
                    **observability.external_result_context(result),
                },
            },
        )
        self.diagnostic_capture.capture("external_http_completed", {
            "service": request_context["service"],
            "method": request_context["method"],
            "host": observability.safe_url_netloc(parsed_url),
            "path": request_context["path"],
            "status": response.status,
            "duration_ms": duration_ms,
            "response_bytes": response.response_bytes,
            "headers": self.safe_response_headers(response.headers),
            "response": observability.diagnostic_capture_response(result),
        })
        return result

    def _http_error(
        self,
        error: HTTPError,
        service: str | None,
        request_context: dict[str, Any],
        parsed_url: Any,
        started: float,
        cancel_event: Any,
    ) -> None:
        raw_body = read_error_body(error, self.max_response_bytes)
        if cancel_event is not None and cancel_event.is_set():
            raise self._cancelled_error(request_context, parsed_url, started) from error
        details = self._provider_error_details(service, error, raw_body)
        self.logger.exception(
            "Upstream HTTP request failed",
            extra={
                "event": "upstream_http_error",
                "context": {
                    **request_context,
                    "status": error.code,
                    "duration_ms": round((self.monotonic() - started) * 1000, 1),
                    "error_type": type(error).__name__,
                    **({"reason": details["reason"]} if details else {}),
                },
            },
        )
        self._capture_failure(
            request_context,
            parsed_url,
            started,
            error,
            error_bytes=len(raw_body),
            headers=getattr(error, "headers", None),
        )
        if details:
            if service == "gemini":
                self.provider_state.record_status(
                    "gemini",
                    state="error",
                    reason=details["reason"],
                    message=details["message"],
                    http_status=error.code,
                )
            status = error.code if service == "gemini" or error.code == 429 else 502
            app_error = AppError(status, details["message"], reason=details["reason"])
            retry_after = details.get("retry_after_seconds")
            if isinstance(retry_after, int):
                app_error.retry_after_seconds = retry_after
            raise app_error from error
        detail = self._interval_error_detail(raw_body) if service == "intervals" else ""
        message = (
            f"Intervals.icu weist die Anfrage zurück ({error.code}): {detail}"
            if detail and service == "intervals"
            else f"Anfrage an externen Dienst fehlgeschlagen ({error.code})."
        )
        raise AppError(502, message, reason="provider_http_error") from error

    def _provider_error_details(
        self, service: str | None, error: HTTPError, raw_body: bytes
    ) -> dict[str, Any] | None:
        if service == "openai":
            from backend.providers import openai as openai_provider

            self.provider_state.record_rate_limits(getattr(error, "headers", None))
            details = openai_provider.error_details(
                error.code,
                raw_body,
                getattr(error, "headers", None),
                updated_at=self.now(),
            )
            self.provider_state.record_status(
                "openai",
                state=details.get("state"),
                reason=details.get("reason"),
                message=details.get("message"),
                http_status=details.get("http_status"),
                provider_error_code=details.get("provider_error_code"),
            )
            return details
        if service == "gemini":
            from backend.providers import gemini as gemini_provider

            return gemini_provider.error_details(error.code, raw_body, updated_at=self.now())
        return None

    def _interval_error_detail(self, raw_body: bytes) -> str:
        return error_detail(
            raw_body,
            redact=lambda value, *, limit: redact_provider_text(self.redact_text(value), limit=limit),
        )


def _decoded_error_payload(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body.decode("utf-8", errors="replace")) if raw_body else None
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_error_field(payload: dict[str, Any], keys: tuple[str, ...] = ("message", "detail", "title")) -> Any:
    return next((payload[key] for key in keys if payload.get(key)), "")


def error_detail(raw_body: bytes, *, limit: int = 500, redact: Any = redact_provider_text) -> str:
    """Extract a bounded, redacted detail from a JSON provider error body."""
    payload = _decoded_error_payload(raw_body)
    error = payload.get("error")
    if isinstance(error, str) and error:
        return redact(error, limit=limit)
    detail = _first_error_field(error) if isinstance(error, dict) else _first_error_field(payload)
    if not detail and isinstance(error, dict):
        detail = _first_error_field(payload)
    return redact(detail, limit=limit)


def _external_call_error_code(error: BaseException) -> str:
    """Return a bounded technical code without retaining exception text."""
    if isinstance(error, AppError) and error.reason:
        return re.sub(r"[^a-z0-9_]+", "_", str(error.reason).casefold()).strip("_")[:80] or "application_error"
    if isinstance(error, TimeoutError):
        return "timeout"
    return "internal_error"


def external_call(
    service: str,
    operation: str,
    call: Any,
    details: dict[str, Any] | None = None,
    *,
    logger: Any,
    diagnostic_capture: Any,
    operation_context: Mapping[str, Any] | None = None,
) -> Any:
    """Observe one SDK call using caller-owned logging and diagnostics."""
    safe_details = observability.safe_diagnostic_context(details)
    context = {"service": service, "operation": operation, **safe_details}
    if operation_context:
        for key in ("operation_id", "trigger"):
            if key in operation_context:
                context[key] = operation_context[key]
        context["phase"] = operation

    started = time.perf_counter()
    logger.info("External call started", extra={"event": "external_call_started", "context": context})
    diagnostic_capture.capture("external_call_started", {
        "service": service,
        "operation": operation,
        "details": safe_details,
    })
    try:
        result = call()
    except AppError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        diagnostic_capture.capture("external_call_failed", {
            "service": service,
            "operation": operation,
            "duration_ms": duration_ms,
            "error": observability.safe_diagnostic_error(exc),
        })
        raise
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception(
            "External call failed",
            extra={
                "event": "external_call_failed",
                "context": {**context, "duration_ms": duration_ms, "error_code": _external_call_error_code(exc)},
            },
        )
        diagnostic_capture.capture("external_call_failed", {
            "service": service,
            "operation": operation,
            "duration_ms": duration_ms,
            "error": observability.safe_diagnostic_error(exc),
        })
        raise provider_error(service, "client") from exc

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info(
        "External call completed",
        extra={
            "event": "external_call_completed",
            "context": {**context, "duration_ms": duration_ms, **observability.external_result_context(result)},
        },
    )
    diagnostic_capture.capture("external_call_completed", {
        "service": service,
        "operation": operation,
        "duration_ms": duration_ms,
        "response": observability.diagnostic_capture_response(result),
    })
    return result
