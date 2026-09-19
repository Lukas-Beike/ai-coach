"""Shared, dependency-light provider HTTP error contracts.

The application decides how errors are presented. Provider modules only need a
bounded, secret-free classification that can be persisted or translated into
an application error by their caller.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from backend import observability

_SECRET_PATTERNS = (
    (re.compile(r"(?i)https?://[^\s<>\"'`]+"), "[REDACTED_URL]"),
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(basic|bearer)\s+[^\s,\"'}]+"), r"\1[REDACTED]"),
)


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
        raise ValueError("provider response exceeds configured size limit")
    return raw


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
