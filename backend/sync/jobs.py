"""Provider-job contracts shared by the persistence and worker layers.

The module deliberately has no database, HTTP, or provider dependency.  It
owns the small state-machine vocabulary so the server can persist jobs without
duplicating validation and retry decisions in request handlers.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


PROVIDERS = frozenset({"intervals", "garmin", "calendar", "weather"})
JOB_TYPES = frozenset({
    "refresh",
    "performance_refresh",
    "plan_push",
    "competition_push",
    "historical_backfill",
})
JOB_STATUSES = frozenset({"queued", "running", "completed", "partial", "failed"})
ITEM_STATUSES = frozenset({"queued", "running", "completed", "partial", "failed", "skipped"})
TERMINAL_JOB_STATUSES = frozenset({"completed", "partial", "failed"})
TERMINAL_ITEM_STATUSES = frozenset({"completed", "partial", "failed", "skipped"})
RETRYABLE_ERROR_CLASSES = frozenset({
    "network_error",
    "timeout",
    "provider_unavailable",
    "rate_limited",
    "temporary_error",
    "process_interrupted",
})


class JobValidationError(ValueError):
    """Raised when an API or worker job request violates the contract."""


def utc_timestamp(now: datetime | None = None) -> str:
    """Return a stable UTC timestamp for durable job records."""
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def validate_job_request(provider: Any, job_type: Any, payload: Any = None) -> dict[str, Any]:
    """Validate and copy the bounded provider-job envelope."""
    provider_value = str(provider or "").strip().casefold()
    if provider_value not in PROVIDERS:
        raise JobValidationError("Unsupported provider.")
    type_value = str(job_type or "").strip().casefold()
    if type_value not in JOB_TYPES:
        raise JobValidationError("Unsupported job type.")
    if payload is None:
        payload_value: dict[str, Any] = {}
    elif isinstance(payload, Mapping):
        payload_value = dict(payload)
    else:
        raise JobValidationError("Job payload must be an object.")
    if len(payload_value) > 32:
        raise JobValidationError("Job payload contains too many fields.")
    return {"provider": provider_value, "type": type_value, "payload": payload_value}


def retry_delay(attempt: int, *, base_seconds: int, max_seconds: int) -> int:
    """Return bounded exponential backoff after a failed attempt."""
    try:
        number = max(1, int(attempt))
    except (TypeError, ValueError):
        number = 1
    return min(max_seconds, base_seconds * (2 ** min(number - 1, 16)))


def is_retryable_error(error_class: Any) -> bool:
    return str(error_class or "").strip().casefold() in RETRYABLE_ERROR_CLASSES


def aggregate_job_status(items: list[Mapping[str, Any]]) -> str:
    """Derive the public job status from item states."""
    if not items:
        return "completed"
    statuses = {str(item.get("status") or "queued") for item in items}
    if statuses - TERMINAL_ITEM_STATUSES:
        return "running" if "running" in statuses else "queued"
    failures = statuses & {"failed", "partial"}
    successes = statuses & {"completed", "skipped"}
    if failures and successes:
        return "partial"
    if failures:
        return "failed" if failures == {"failed"} else "partial"
    return "completed"


def bounded_progress(items: list[Mapping[str, Any]]) -> tuple[int, int]:
    """Return completed item count and total, ignoring malformed rows safely."""
    total = len(items)
    completed = sum(
        1 for item in items
        if str(item.get("status") or "") in TERMINAL_ITEM_STATUSES
    )
    return completed, total

