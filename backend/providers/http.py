"""Shared, dependency-light provider HTTP error contracts.

The application decides how errors are presented. Provider modules only need a
bounded, secret-free classification that can be persisted or translated into
an application error by their caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_SECRET_PATTERNS = (
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
    category = "rate_limited" if status == 429 else "authentication" if status in {401, 403} else "http"
    return ProviderHTTPError(service, category, status, redact_provider_text(detail))
