"""Shared, dependency-light provider HTTP error contracts.

The application decides how errors are presented. Provider modules only need a
bounded, secret-free classification that can be persisted or translated into
an application error by their caller.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import Any


_SECRET_PATTERNS = (
    (re.compile(r"(?i)https?://[^\s<>\"'`]+"), "[REDACTED_URL]"),
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(basic|bearer)\s+[^\s,\"'}]+"), r"\1[REDACTED]"),
)


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


def error_detail(raw_body: bytes, *, limit: int = 500, redact: Any = redact_provider_text) -> str:
    """Extract a bounded, redacted detail from a JSON provider error body."""
    try:
        payload = json.loads(raw_body.decode("utf-8", errors="replace")) if raw_body else None
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    top_level = payload if isinstance(payload, dict) else {}
    error = top_level.get("error")
    if isinstance(error, str) and error:
        return redact(error, limit=limit)
    candidate = error if isinstance(error, dict) else top_level
    if isinstance(candidate, dict):
        for key in ("message", "detail", "title"):
            if candidate.get(key):
                return redact(candidate[key], limit=limit)
        if candidate is not top_level:
            for key in ("message", "detail", "title"):
                if top_level.get(key):
                    return redact(top_level[key], limit=limit)
    return redact("", limit=limit)
