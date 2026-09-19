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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from backend import observability

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
