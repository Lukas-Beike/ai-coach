"""Provider-job contracts shared by the persistence and worker layers.

The module deliberately has no database, HTTP, or provider dependency.  It
owns the small state-machine vocabulary so the server can persist jobs without
duplicating validation and retry decisions in request handlers.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import json


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


def decode_job_payload(value: Any) -> dict[str, Any]:
    """Decode a persisted payload without allowing malformed data to escape."""
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def job_dto(job: Mapping[str, Any], items: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Build the public, credential-free representation of one sync job."""
    if not hasattr(job, "get"):
        job = dict(job)
    normalized_items = [item if hasattr(item, "get") else dict(item) for item in items]
    item_dtos = [
        {
            "id": item["id"],
            "item_key": item["item_key"],
            "operation": item["operation"],
            "remote_id": item.get("remote_id"),
            "status": item["status"],
            "attempts": int(item.get("attempts") or 0),
            "error_class": item.get("error_class"),
            "error_detail": item.get("error_detail"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        for item in normalized_items
    ]
    completed, total = bounded_progress(item_dtos)
    return {
        "id": job["id"],
        "provider": job["provider"],
        "type": job["type"],
        "status": str(job.get("status") or aggregate_job_status(item_dtos)),
        "payload": decode_job_payload(job.get("payload")),
        "requested_by": job.get("requested_by") or "system",
        "attempts": int(job.get("attempts") or 0),
        "progress": {"completed": completed, "total": total},
        "available_at": job.get("available_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error_class": job.get("error_class"),
        "items": item_dtos,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def read_job(db: Any, job_id: str) -> tuple[Any | None, list[Any]]:
    """Read one job and its ordered items through a caller-owned connection."""
    job = db.execute("SELECT * FROM sync_jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        return None, []
    items = db.execute(
        "SELECT * FROM sync_job_items WHERE job_id=? ORDER BY created_at, id", (job_id,)
    ).fetchall()
    return job, items


def list_jobs(db: Any, limit: int) -> list[dict[str, Any]]:
    """Project recent jobs without taking ownership of the database scope."""
    jobs = db.execute(
        "SELECT * FROM sync_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [job_dto(job, read_job(db, job["id"])[1]) for job in jobs]


def has_active_job(db: Any, provider: str, job_type: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sync_jobs WHERE provider=? AND type=? "
        "AND status IN ('queued', 'running') LIMIT 1",
        (provider, job_type),
    ).fetchone()
    return row is not None


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

