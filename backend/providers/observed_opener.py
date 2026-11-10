"""Observation of raw provider openers that bypass the shared JSON client.

Yazio, Open Food Facts and the Wahoo FIT download open their own requests. The
wrapper records start, status and failure class in the log and the diagnostic
capture, and re-raises every exception unchanged so each caller keeps its own
error classification. Only the service, method, host, a redacted path, timing
and the exception class are recorded, never URLs, queries, headers or bodies.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from backend import observability
from backend.providers.http import urlopen

Opener = Callable[[Any, float], Any]


def observed_opener(
    service: str,
    *,
    logger: Any,
    diagnostic_capture: Any,
    operation_context: Callable[[], Mapping[str, Any] | None] | None = None,
    include_path: bool = True,
    opener: Any = urlopen,
    monotonic: Callable[[], float] = time.perf_counter,
) -> Opener:
    """Return an opener that observes each request and leaves its outcome intact.

    ``include_path`` is False for signed download URLs, whose path is a secret.
    """

    def open_observed(request: Any, timeout: float) -> Any:
        parsed = urlsplit(str(request.full_url))
        context: dict[str, Any] = {
            "service": service,
            "method": str(request.get_method()).upper(),
            "host": observability.safe_url_netloc(parsed),
        }
        if include_path:
            context["path"] = observability.safe_provider_path(parsed.path)
        correlation = operation_context() if operation_context is not None else None
        for key in ("operation_id", "trigger"):
            if correlation and key in correlation:
                context[key] = correlation[key]
        diagnostic_id = uuid.uuid4().hex
        started = monotonic()
        logger.info(
            "External HTTP request started",
            extra={"event": "external_request_started", "context": context},
        )
        diagnostic_capture.capture(
            "external_http_started", {"diagnostic_id": diagnostic_id, **context}
        )
        try:
            response = opener(request, timeout=timeout)
        except Exception as error:
            duration_ms = round((monotonic() - started) * 1000, 1)
            safe_error = observability.safe_diagnostic_error(error)
            logger.warning(
                "External HTTP request failed",
                extra={
                    "event": "external_request_failed",
                    "context": {
                        **context,
                        "duration_ms": duration_ms,
                        "error_type": type(error).__name__,
                        "status": safe_error.get("status"),
                    },
                },
            )
            diagnostic_capture.capture(
                "external_http_failed",
                {
                    "diagnostic_id": diagnostic_id,
                    **context,
                    "duration_ms": duration_ms,
                    "error": safe_error,
                    "exception_type": type(error).__name__,
                },
            )
            raise
        status = getattr(response, "status", None) or getattr(response, "code", None)
        duration_ms = round((monotonic() - started) * 1000, 1)
        logger.info(
            "External HTTP request completed",
            extra={
                "event": "external_request_completed",
                "context": {**context, "status": status, "duration_ms": duration_ms},
            },
        )
        diagnostic_capture.capture(
            "external_http_completed",
            {
                "diagnostic_id": diagnostic_id,
                **context,
                "status": status,
                "duration_ms": duration_ms,
            },
        )
        return response

    return open_observed
