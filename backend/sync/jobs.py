"""Provider-job contracts shared by the persistence and worker layers.

The module deliberately has no database, HTTP, or provider dependency.  It
owns the small state-machine vocabulary so the server can persist jobs without
duplicating validation and retry decisions in request handlers.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.runtime.clock import utc_now as system_utc_now

PROVIDERS = frozenset({"intervals", "garmin", "calendar", "weather"})
JOB_TYPES = frozenset(
    {
        "refresh",
        "performance_refresh",
        "activity_details",
        "plan_push",
        "competition_push",
        "nutrition_sync",
        "historical_backfill",
    }
)
JOB_STATUSES = frozenset({"queued", "running", "completed", "partial", "failed"})
ALLOWED_JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running"}),
    "running": frozenset({"queued", "completed", "partial", "failed"}),
    "completed": frozenset(),
    "partial": frozenset({"queued"}),
    "failed": frozenset({"queued"}),
}
ITEM_STATUSES = frozenset(
    {"queued", "running", "completed", "partial", "failed", "skipped"}
)
TERMINAL_JOB_STATUSES = frozenset({"completed", "partial", "failed"})
TERMINAL_ITEM_STATUSES = frozenset({"completed", "partial", "failed", "skipped"})
RETRYABLE_ERROR_CLASSES = frozenset(
    {
        "network_error",
        "timeout",
        "provider_unavailable",
        "rate_limited",
        "temporary_error",
        "process_interrupted",
    }
)
SYNC_JOB_LIST_LIMIT = 50
SYNC_JOB_MAX_ATTEMPTS = 3
INVALID_NUTRITION_MANIFEST_ERROR = "Invalid nutrition approval manifest."
NUTRITION_MANIFEST_FIELDS = frozenset(
    {
        "date",
        "revision",
        "total_kcal",
        "total_carbs_g",
        "total_protein_g",
        "total_fat_g",
        "entry_count",
        "sha256",
    }
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ISO_DAY_ERROR = "Das Datum muss ein ISO-Kalendertag sein."
UNSUPPORTED_JOB_FIELDS_ERROR = "Der Job enth\u00e4lt nicht unterst\u00fctzte Felder."


class SyncJobNotFoundError(LookupError):
    """Raised when an explicit operation targets a missing sync job."""


class SyncJobInvalidStateError(RuntimeError):
    """Raised when a job cannot make the requested state transition."""


class SyncJobTransitionError(SyncJobInvalidStateError):
    """Raised when a guarded job transition is invalid or lost a race."""


class SyncJobInvalidOperationError(ValueError):
    """Raised when a sync-job operation violates its persistence contract."""


class JobValidationError(ValueError):
    """Raised when an API or worker job request violates the contract."""


def decode_job_payload(value: Any) -> dict[str, Any]:
    """Decode a persisted payload without allowing malformed data to escape."""
    try:
        payload = json.loads(value or "{}")
    except TypeError, ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def job_dto(
    job: Mapping[str, Any] | None, items: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build the public, credential-free representation of one sync job."""
    if job is None:
        raise SyncJobInvalidStateError("The persisted job is missing.")
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


def read_job(db: Any, job_id: str) -> tuple[Any | None, builtins.list[Any]]:
    """Read one job and its ordered items through a caller-owned connection."""
    job = db.execute("SELECT * FROM sync_jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        return None, []
    items = db.execute(
        "SELECT * FROM sync_job_items WHERE job_id=? ORDER BY created_at, id", (job_id,)
    ).fetchall()
    return job, items


def list_jobs(db: Any, limit: int) -> builtins.list[dict[str, Any]]:
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
    value = now or datetime.fromisoformat(system_utc_now())
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def validate_job_request(
    provider: Any, job_type: Any, payload: Any = None
) -> dict[str, Any]:
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


def normalize_sync_job_request(
    provider: Any, job_type: Any, payload: Any = None, *, all_sync_days: int
) -> dict[str, Any]:
    """Validate and normalize the provider-specific payload persisted for a job."""
    envelope = validate_job_request(provider, job_type, payload)
    provider_value = envelope["provider"]
    type_value = envelope["type"]
    values = envelope["payload"]
    if type_value == "historical_backfill" and provider_value not in {
        "intervals",
        "garmin",
    }:
        raise JobValidationError(
            "Historischer Backfill ist nur für Intervals.icu und Garmin zulässig."
        )
    if type_value == "activity_details":
        normalized_payload = _normalize_activity_details_job(provider_value, values)
    elif type_value == "nutrition_sync":
        normalized_payload = _normalize_nutrition_sync_job(provider_value, values)
    elif type_value == "competition_push":
        normalized_payload = _normalize_competition_push_job(provider_value, values)
    elif type_value == "performance_refresh":
        normalized_payload = _normalize_reason_only_job(provider_value, values)
    elif type_value == "plan_push":
        normalized_payload = _normalize_plan_push_job(provider_value, values)
    else:
        normalized_payload = _normalize_refresh_job(
            provider_value, values, all_sync_days
        )
    return {
        "provider": provider_value,
        "type": type_value,
        "payload": normalized_payload,
    }


def _normalize_activity_details_job(
    provider: str, values: dict[str, Any]
) -> dict[str, Any]:
    if provider != "intervals" or set(values) != {"activity_id"}:
        raise JobValidationError("Ungültiger Aktivitätsdetailauftrag.")
    value = values.get("activity_id")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise JobValidationError("Die Aktivitäts-ID ist ungültig.")
    return {"activity_id": value}


def _normalize_nutrition_sync_job(
    provider: str, values: dict[str, Any]
) -> dict[str, Any]:
    allowed_fields = {"date", "pending_limit", "approval_manifest"}
    if provider != "intervals" or set(values) - allowed_fields:
        raise JobValidationError("Ungültiger Ernährungssynchronisierungsauftrag.")
    if "approval_manifest" in values:
        return _normalize_approved_nutrition_job(values)
    if "date" in values and "pending_limit" in values:
        raise JobValidationError("Choose a date or pending days, not both.")
    if "date" in values:
        return {"date": _normalize_nutrition_date(values["date"])}
    return {
        "pending_limit": _normalize_nutrition_pending_limit(values.get("pending_limit"))
    }


def _normalize_approved_nutrition_job(values: dict[str, Any]) -> dict[str, Any]:
    if set(values) != {"approval_manifest"}:
        raise JobValidationError(
            "An approved nutrition sync cannot include other targets."
        )
    return {
        "approval_manifest": _normalize_nutrition_approval_manifest(
            values["approval_manifest"]
        )
    }


def _normalize_nutrition_date(value: Any) -> str:
    if not isinstance(value, str):
        raise JobValidationError(ISO_DAY_ERROR)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise JobValidationError(ISO_DAY_ERROR) from exc
    if parsed.isoformat() != value:
        raise JobValidationError(ISO_DAY_ERROR)
    return value


def _normalize_nutrition_pending_limit(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 31:
        raise JobValidationError("The nutrition sync limit must be between 1 and 31.")
    return value


def _normalize_nutrition_approval_manifest(value: Any) -> builtins.list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 31:
        raise JobValidationError(INVALID_NUTRITION_MANIFEST_ERROR)
    normalized: builtins.list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for entry in value:
        normalized.append(_normalize_nutrition_approval_entry(entry, seen_dates))
    return normalized


def _normalize_nutrition_approval_entry(
    entry: Any, seen_dates: set[str]
) -> dict[str, Any]:
    if not isinstance(entry, dict) or set(entry) != NUTRITION_MANIFEST_FIELDS:
        raise JobValidationError(INVALID_NUTRITION_MANIFEST_ERROR)
    raw_date = _normalize_nutrition_date(entry["date"])
    if raw_date in seen_dates:
        raise JobValidationError(ISO_DAY_ERROR)
    _validate_nutrition_approval_fields(entry)
    _validate_nutrition_approval_hash(entry)
    seen_dates.add(raw_date)
    return dict(entry)


def _validate_nutrition_approval_fields(entry: dict[str, Any]) -> None:
    integer_fields = ("revision", "total_kcal", "entry_count")
    if any(type(entry[key]) is not int or entry[key] < 0 for key in integer_fields):
        raise JobValidationError(INVALID_NUTRITION_MANIFEST_ERROR)
    total_fields = ("total_carbs_g", "total_protein_g", "total_fat_g")
    if any(
        value is not None and (type(value) not in {int, float} or value < 0)
        for value in (entry[key] for key in total_fields)
    ):
        raise JobValidationError(INVALID_NUTRITION_MANIFEST_ERROR)
    digest = entry["sha256"]
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        raise JobValidationError(INVALID_NUTRITION_MANIFEST_ERROR)


def _validate_nutrition_approval_hash(entry: dict[str, Any]) -> None:
    digest_values = {
        key: entry[key]
        for key in NUTRITION_MANIFEST_FIELDS
        if key not in {"revision", "sha256"}
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_values,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if digest != entry["sha256"]:
        raise JobValidationError("Nutrition approval hash does not match its totals.")


def _normalize_reason_only_job(provider: str, values: dict[str, Any]) -> dict[str, str]:
    if provider != "intervals":
        raise JobValidationError("Dieser Job ist nur für Intervals.icu zulässig.")
    if set(values) - {"reason"}:
        raise JobValidationError(UNSUPPORTED_JOB_FIELDS_ERROR)
    return {"reason": str(values.get("reason") or "job").strip()[:80] or "job"}


def _normalize_competition_push_job(
    provider: str, values: dict[str, Any]
) -> dict[str, Any]:
    if provider != "intervals":
        raise JobValidationError("Dieser Job ist nur für Intervals.icu zulässig.")
    if set(values) - {"reason", "approval_manifest"}:
        raise JobValidationError(UNSUPPORTED_JOB_FIELDS_ERROR)
    if "approval_manifest" not in values:
        raise JobValidationError(
            "Der Wettkampf-Sync benötigt eine bestätigte Vorschau."
        )
    normalized: dict[str, Any] = {
        "reason": str(values.get("reason") or "job").strip()[:80] or "job"
    }
    manifest = values["approval_manifest"]
    if not isinstance(manifest, list) or len(manifest) > 1000:
        raise JobValidationError("Die Wettkampf-Freigabevorschau ist ungültig.")
    entries = []
    for entry in manifest:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"type", "id", "sha256"}
            or entry.get("type") not in {"competition", "tombstone"}
            or not isinstance(entry.get("id"), str)
            or not entry["id"].strip()
            or len(entry["id"]) > 160
            or not isinstance(entry.get("sha256"), str)
            or not SHA256_PATTERN.fullmatch(entry["sha256"])
        ):
            raise JobValidationError("Die Wettkampf-Freigabevorschau ist ungültig.")
        entries.append(dict(entry))
    normalized["approval_manifest"] = entries
    return normalized


def _normalize_plan_push_entry(entry: Any) -> dict[str, str]:
    workout_id = (
        str(entry.get("library_workout_id") or "") if isinstance(entry, dict) else ""
    )
    if not isinstance(entry, dict) or not re.fullmatch(r"[0-9a-f-]{36}", workout_id):
        raise JobValidationError("Jede Plan-Push-Einheit benötigt eine lokale UUID.")
    payload_hash = str(entry.get("expected_payload_hash") or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(payload_hash):
        raise JobValidationError(
            "Jede Plan-Push-Einheit benötigt einen aktuellen Payload-Hash."
        )
    return {"library_workout_id": workout_id, "expected_payload_hash": payload_hash}


def _normalize_plan_push_job(provider: str, values: dict[str, Any]) -> dict[str, Any]:
    if provider != "intervals":
        raise JobValidationError("Plan-Push-Jobs sind nur für Intervals.icu zulässig.")
    if set(values) - {"entries", "reason", "repair"}:
        raise JobValidationError("Ein Plan-Push-Job enthält nicht unterstützte Felder.")
    entries = values.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 28:
        raise JobValidationError(
            "Ein Plan-Push-Job benötigt 1 bis 28 ausgewählte Einheiten."
        )
    normalized_entries = [_normalize_plan_push_entry(entry) for entry in entries]
    if "repair" in values and type(values["repair"]) is not bool:
        raise JobValidationError("repair muss ein Boolean sein.")
    normalized: dict[str, Any] = {
        "entries": normalized_entries,
        "reason": str(values.get("reason") or "job").strip()[:80] or "job",
    }
    if values.get("repair"):
        normalized["repair"] = True
    return normalized


def _normalize_refresh_job(
    provider_value: str, values: dict[str, Any], all_sync_days: int
) -> dict[str, Any]:
    if set(values) - _refresh_job_fields(provider_value):
        raise JobValidationError(UNSUPPORTED_JOB_FIELDS_ERROR)

    normalized_payload: dict[str, Any] = {}
    if "days" in values:
        normalized_payload["days"] = _normalize_refresh_days(
            values["days"], all_sync_days
        )
    if "force" in values:
        normalized_payload["force"] = _normalize_refresh_force(values["force"])
    if "end_date" in values:
        normalized_payload["end_date"] = _normalize_refresh_end_date(values["end_date"])
    if values.get("reason") is not None:
        normalized_payload["reason"] = _normalize_refresh_reason(values["reason"])
    return normalized_payload


def _refresh_job_fields(provider: str) -> set[str]:
    return {
        "intervals": {"days", "reason", "end_date"},
        "garmin": {"days", "reason", "end_date"},
        "calendar": {"reason"},
        "weather": {"force", "reason"},
    }[provider]


def _normalize_refresh_days(value: Any, all_sync_days: int) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise JobValidationError("Der Synchronisationszeitraum ist ungültig.") from exc
    if days != all_sync_days and (days < 1 or days > 3660):
        raise JobValidationError("Der Synchronisationszeitraum ist zu groß.")
    return days


def _normalize_refresh_force(value: Any) -> bool:
    if type(value) is not bool:
        raise JobValidationError("force muss ein Boolean sein.")
    return value


def _normalize_refresh_end_date(value: Any) -> str:
    try:
        return date.fromisoformat(iso_date_prefix(str(value))).isoformat()
    except (TypeError, ValueError) as exc:
        raise JobValidationError("Das Backfill-Enddatum ist ungültig.") from exc


def _normalize_refresh_reason(value: Any) -> str:
    return str(value).strip()[:80] or "job"


def retry_delay(attempt: int, *, base_seconds: int, max_seconds: int) -> int:
    """Return bounded exponential backoff after a failed attempt."""
    try:
        number = max(1, int(attempt))
    except TypeError, ValueError:
        number = 1
    return min(max_seconds, base_seconds * (2 ** min(number - 1, 16)))


def is_retryable_error(error_class: Any) -> bool:
    return str(error_class or "").strip().casefold() in RETRYABLE_ERROR_CLASSES


def aggregate_job_status(items: Sequence[Mapping[str, Any]]) -> str:
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


def bounded_progress(items: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """Return completed item count and total, ignoring malformed rows safely."""
    total = len(items)
    completed = sum(
        1 for item in items if str(item.get("status") or "") in TERMINAL_ITEM_STATUSES
    )
    return completed, total


class SyncJobStore:
    """Durable, provider-independent persistence for resumable sync jobs."""

    def __init__(
        self,
        database_manager: Any,
        now: Callable[[], str],
        uuid_factory: Callable[[], str],
    ):
        self._database_manager = database_manager
        self._now = now
        self._uuid_factory = uuid_factory

    def state(self, job_id: str) -> dict[str, Any] | None:
        with self._database_manager.unit_of_work() as db:
            job, items = read_job(db, job_id)
            return job_dto(job, items) if job else None

    def list(self, limit: int) -> builtins.list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), SYNC_JOB_LIST_LIMIT))
        with self._database_manager.unit_of_work() as db:
            return list_jobs(db, bounded_limit)

    def active(self, provider: str, job_type: str) -> bool:
        with self._database_manager.unit_of_work() as db:
            return has_active_job(db, provider, job_type)

    def pending_performance_job_id(self) -> str | None:
        with self._database_manager.unit_of_work() as db:
            row = db.execute(
                "SELECT id FROM sync_jobs WHERE provider='intervals' AND type='performance_refresh' "
                "AND status IN ('queued', 'running') ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            return row["id"] if row else None

    def enqueue(
        self,
        envelope: Mapping[str, Any],
        requested_by: str,
        operations: builtins.list[dict[str, Any]] | None,
        available_at: str | None,
    ) -> tuple[dict[str, Any], bool]:
        """Persist a normalized, credential-free envelope and its items atomically."""
        try:
            normalized = validate_job_request(
                envelope.get("provider"), envelope.get("type"), envelope.get("payload")
            )
        except (AttributeError, ValueError) as exc:
            raise SyncJobInvalidOperationError(str(exc)) from exc

        now = self._now()
        try:
            scheduled_at = self._scheduled_at(available_at, now)
            payload_json = json.dumps(
                normalized["payload"], ensure_ascii=False, separators=(",", ":")
            )
        except (TypeError, ValueError) as exc:
            raise SyncJobInvalidOperationError(
                "Job payload or start time is invalid."
            ) from exc

        requested = str(requested_by or "system").strip().casefold()[:40] or "system"
        item_operations = self._normalize_operations(normalized, operations)
        job_id = str(self._uuid_factory())

        with self._database_manager.unit_of_work() as db:
            if (
                normalized["provider"] == "intervals"
                and normalized["type"] == "performance_refresh"
            ):
                existing = db.execute(
                    "SELECT * FROM sync_jobs WHERE provider='intervals' AND type='performance_refresh' "
                    "AND status IN ('queued', 'running') ORDER BY created_at, id LIMIT 1"
                ).fetchone()
                if existing:
                    current, items = read_job(db, existing["id"])
                    return job_dto(current, items), False

            db.execute(
                "INSERT INTO sync_jobs(id, provider, type, status, payload, requested_by, attempts, "
                "progress_total, progress_completed, available_at, created_at, updated_at) "
                "VALUES (?, ?, ?, 'queued', ?, ?, 0, ?, 0, ?, ?, ?)",
                (
                    job_id,
                    normalized["provider"],
                    normalized["type"],
                    payload_json,
                    requested,
                    len(item_operations),
                    scheduled_at,
                    now,
                    now,
                ),
            )
            for index, operation in enumerate(item_operations):
                db.execute(
                    "INSERT INTO sync_job_items(id, job_id, item_key, operation, payload_hash, status, "
                    "attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?)",
                    (
                        f"{job_id}-{index}",
                        job_id,
                        operation["item_key"],
                        operation["operation"],
                        operation["payload_hash"],
                        now,
                        now,
                    ),
                )
            job, items = read_job(db, job_id)
            return job_dto(job, items), True

    def resume_interrupted(self) -> int:
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            jobs = db.execute(
                "SELECT id FROM sync_jobs WHERE status='running'"
            ).fetchall()
            for job in jobs:
                self._transition(
                    db,
                    job["id"],
                    "running",
                    "queued",
                    {
                        "available_at": now,
                        "started_at": None,
                        "error_class": "process_interrupted",
                        "updated_at": now,
                    },
                )
                db.execute(
                    "UPDATE sync_job_items SET status='queued', error_class='process_interrupted', "
                    "error_detail=NULL, updated_at=? WHERE job_id=? AND status='running'",
                    (now, job["id"]),
                )
            return len(jobs)

    def claim(self) -> dict[str, Any] | None:
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            candidate = db.execute(
                "SELECT id FROM sync_jobs WHERE status='queued' "
                "AND (available_at IS NULL OR available_at<=?) ORDER BY created_at, id LIMIT 1",
                (now,),
            ).fetchone()
            if not candidate:
                return None
            job_id = candidate["id"]
            self._transition(
                db,
                job_id,
                "queued",
                "running",
                {
                    "started_at": now,
                    "finished_at": None,
                    "error_class": None,
                    "updated_at": now,
                },
                increment_attempts=True,
                extra_where="AND (available_at IS NULL OR available_at<=?)",
                extra_parameters=(now,),
            )
            db.execute(
                "UPDATE sync_job_items SET status='running', attempts=attempts+1, error_class=NULL, "
                "error_detail=NULL, updated_at=? WHERE job_id=? AND status='queued'",
                (now, job_id),
            )
            job = db.execute("SELECT * FROM sync_jobs WHERE id=?", (job_id,)).fetchone()
            return dict(job) if job else None

    def update(
        self,
        job_id: str,
        item_status: str,
        error_class: str | None = None,
        error_detail: str | None = None,
    ) -> dict[str, Any] | None:
        """Update every item; detail must already be redacted and is clipped here."""
        if item_status not in ITEM_STATUSES:
            raise SyncJobInvalidOperationError("Invalid sync item status.")
        now = self._now()
        detail = str(error_detail or "")[:500] or None
        with self._database_manager.unit_of_work() as db:
            job, _ = read_job(db, job_id)
            if job is None:
                return None
            db.execute(
                "UPDATE sync_job_items SET status=?, error_class=?, error_detail=?, updated_at=? "
                "WHERE job_id=?",
                (item_status, error_class, detail, now, job_id),
            )
            items = [
                dict(item)
                for item in db.execute(
                    "SELECT status FROM sync_job_items WHERE job_id=? ORDER BY created_at, id",
                    (job_id,),
                ).fetchall()
            ]
            status = aggregate_job_status(items)
            completed, total = bounded_progress(items)
            finished = now if status in TERMINAL_JOB_STATUSES else None
            self._transition(
                db,
                job_id,
                str(job["status"]),
                status,
                {
                    "progress_total": total,
                    "progress_completed": completed,
                    "finished_at": finished,
                    "error_class": error_class,
                    "updated_at": now,
                },
            )
            updated, updated_items = read_job(db, job_id)
            return self._event_snapshot(updated, updated_items)

    def update_from_result(
        self,
        job_id: str,
        result: Any,
        fallback_status: str,
        redact: Callable[[str], str],
    ) -> dict[str, Any] | None:
        raw_results = result.get("results") if isinstance(result, dict) else None
        item_results = (
            [item for item in raw_results if isinstance(item, dict)]
            if isinstance(raw_results, list)
            else []
        )
        if not item_results:
            return self.update(job_id, fallback_status)

        now = self._now()
        with self._database_manager.unit_of_work() as db:
            job, _ = read_job(db, job_id)
            if job is None:
                return None
            stored_items = [
                dict(item)
                for item in db.execute(
                    "SELECT id, item_key FROM sync_job_items WHERE job_id=? ORDER BY created_at, id",
                    (job_id,),
                ).fetchall()
            ]
            stored_by_key = {
                str(item.get("item_key") or ""): item for item in stored_items
            }
            for index, item in enumerate(item_results):
                self._update_result_item(
                    db, item, index, stored_items, stored_by_key, redact, now
                )
            items = [
                dict(item)
                for item in db.execute(
                    "SELECT status FROM sync_job_items WHERE job_id=? ORDER BY created_at, id",
                    (job_id,),
                ).fetchall()
            ]
            status = aggregate_job_status(items)
            completed, total = bounded_progress(items)
            finished = now if status in TERMINAL_JOB_STATUSES else None
            error_class = None if status == "completed" else "plan_push_error"
            self._transition(
                db,
                job_id,
                str(job["status"]),
                status,
                {
                    "progress_total": total,
                    "progress_completed": completed,
                    "finished_at": finished,
                    "error_class": error_class,
                    "updated_at": now,
                },
            )
            updated, updated_items = read_job(db, job_id)
            return self._event_snapshot(updated, updated_items)

    @staticmethod
    def _update_result_item(
        db: Any,
        item: dict[str, Any],
        index: int,
        stored_items: builtins.list[dict[str, Any]],
        stored_by_key: dict[str, dict[str, Any]],
        redact: Callable[[str], str],
        now: str,
    ) -> None:
        item_key = str(
            item.get("library_workout_id") or item.get("item_key") or ""
        ).strip()
        target = stored_by_key.get(item_key)
        if target is None and len(stored_items) == 1:
            target = stored_items[0]
        if target is None and index < len(stored_items):
            target = stored_items[index]
        if target is None:
            return
        outcome = str(item.get("status") or "error").strip().casefold()
        item_state = (
            "completed"
            if outcome in {"synced", "already_synced", "skipped"}
            else "failed"
        )
        detail = str(redact(str(item.get("error") or "")) or "")[:500] or None
        db.execute(
            "UPDATE sync_job_items SET status=?, remote_id=COALESCE(?, remote_id), "
            "error_class=?, error_detail=?, updated_at=? WHERE id=?",
            (
                item_state,
                str(item.get("remote_id") or "").strip() or None,
                None if item_state == "completed" else "plan_push_error",
                detail,
                now,
                target["id"],
            ),
        )

    def requeue(
        self, job: Mapping[str, Any], error_class: str, detail: str, available_at: str
    ) -> bool:
        """Requeue a retryable claim; detail must already be redacted and is clipped."""
        now = self._now()
        try:
            attempts = int(job.get("attempts") or 1)
            job_id = str(job["id"])
            scheduled_at = self._scheduled_at(available_at, now)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise SyncJobInvalidOperationError(
                "Claimed sync job or retry time is invalid."
            ) from exc
        if not is_retryable_error(error_class) or attempts >= SYNC_JOB_MAX_ATTEMPTS:
            return False
        clipped_detail = str(detail or "")[:500] or None
        with self._database_manager.unit_of_work() as db:
            self._transition(
                db,
                job_id,
                "running",
                "queued",
                {
                    "available_at": scheduled_at,
                    "finished_at": None,
                    "error_class": error_class,
                    "updated_at": now,
                },
            )
            db.execute(
                "UPDATE sync_job_items SET status='queued', error_class=?, error_detail=?, updated_at=? "
                "WHERE job_id=?",
                (error_class, clipped_detail, now, job_id),
            )
            return True

    def resolve(self, job_id: str) -> dict[str, Any]:
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            job = db.execute(
                "SELECT status FROM sync_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if job is None:
                raise SyncJobNotFoundError(job_id)
            if job["status"] not in {"failed", "partial"}:
                raise SyncJobInvalidStateError(
                    "Only failed or partial sync jobs can be resolved."
                )
            self._transition(
                db,
                job_id,
                str(job["status"]),
                "queued",
                {
                    "attempts": 0,
                    "available_at": now,
                    "started_at": None,
                    "finished_at": None,
                    "error_class": None,
                    "progress_completed": 0,
                    "updated_at": now,
                },
            )
            db.execute(
                "UPDATE sync_job_items SET status='queued', attempts=0, error_class=NULL, "
                "error_detail=NULL, updated_at=? WHERE job_id=? AND status IN ('failed', 'partial')",
                (now, job_id),
            )
            resolved, items = read_job(db, job_id)
            return job_dto(resolved, items)

    @staticmethod
    def _transition(
        db: Any,
        job_id: str,
        expected_status: str,
        target_status: str,
        updates: Mapping[str, Any],
        *,
        increment_attempts: bool = False,
        extra_where: str = "",
        extra_parameters: tuple[Any, ...] = (),
    ) -> Any:
        """Validate and atomically apply one guarded job status transition."""
        allowed = ALLOWED_JOB_TRANSITIONS.get(expected_status, frozenset())
        if target_status not in allowed:
            SyncJobStore._log_transition_rejection(expected_status, target_status)
            raise SyncJobTransitionError("Invalid sync job status transition.")
        allowed_updates = {
            "attempts",
            "available_at",
            "started_at",
            "finished_at",
            "progress_total",
            "progress_completed",
            "error_class",
            "updated_at",
        }
        if set(updates) - allowed_updates:
            raise SyncJobInvalidOperationError("Invalid sync job transition fields.")
        assignments = []
        parameters: list[Any] = [target_status]
        for column, value in updates.items():
            assignments.append(f"{column}=?")
            parameters.append(value)
        if increment_attempts:
            assignments.append("attempts=attempts+1")
        sql = (
            f"UPDATE sync_jobs SET status=?, {', '.join(assignments)} "
            f"WHERE id=? AND status=? {extra_where}"
        )
        parameters.extend((job_id, expected_status, *extra_parameters))
        updated = db.execute(sql, tuple(parameters))
        if updated.rowcount != 1:
            SyncJobStore._log_transition_rejection(expected_status, target_status)
            raise SyncJobTransitionError("Sync job status transition lost a race.")
        return updated

    @staticmethod
    def _log_transition_rejection(expected_status: str, target_status: str) -> None:
        logging.getLogger(__name__).warning(
            "Sync job status transition rejected",
            extra={
                "event": "sync_job_transition_rejected",
                "expected_status": expected_status,
                "target_status": target_status,
            },
        )

    @staticmethod
    def _scheduled_at(value: str | None, now: str) -> str:
        if value is None:
            return now
        try:
            return (
                datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .isoformat()
            )
        except (TypeError, ValueError) as exc:
            raise SyncJobInvalidOperationError("Invalid sync job start time.") from exc

    @staticmethod
    def _normalize_operations(
        envelope: dict[str, Any], operations: builtins.list[dict[str, Any]] | None
    ) -> builtins.list[dict[str, str]]:
        values = operations or [
            {
                "item_key": f"{envelope['provider']}:{envelope['type']}",
                "operation": envelope["type"],
            }
        ]
        if not isinstance(values, list) or not 1 <= len(values) <= 1000:
            raise SyncJobInvalidOperationError(
                "A job must contain between 1 and 1000 operations."
            )
        normalized: builtins.list[dict[str, str]] = []
        keys: set[str] = set()
        for index, operation in enumerate(values):
            normalized.append(
                SyncJobStore._normalize_operation(operation, index, envelope, keys)
            )
        return normalized

    @staticmethod
    def _normalize_operation(
        operation: Any,
        index: int,
        envelope: Mapping[str, Any],
        keys: set[str],
    ) -> dict[str, str]:
        if not isinstance(operation, dict):
            raise SyncJobInvalidOperationError("Job operations must be objects.")
        item_key = str(operation.get("item_key") or f"item-{index}").strip()[:160]
        item_operation = str(operation.get("operation") or envelope["type"]).strip()[
            :80
        ]
        if not item_key or not item_operation:
            raise SyncJobInvalidOperationError("Job operations require a key and type.")
        if item_key in keys:
            raise SyncJobInvalidOperationError("Job operation keys must be unique.")
        keys.add(item_key)
        payload_hash = str(operation.get("payload_hash") or "")[:128]
        if not payload_hash:
            payload_hash = SyncJobStore._operation_payload_hash(
                item_operation, envelope["payload"]
            )
        return {
            "item_key": item_key,
            "operation": item_operation,
            "payload_hash": payload_hash,
        }

    @staticmethod
    def _operation_payload_hash(operation: str, payload: Any) -> str:
        try:
            serialized = json.dumps(
                {"operation": operation, "payload": payload},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise SyncJobInvalidOperationError(
                "Job payload is not JSON serializable."
            ) from exc
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _event_snapshot(
        job: Mapping[str, Any] | None, items: builtins.list[Mapping[str, Any]]
    ) -> dict[str, Any] | None:
        if job is None:
            return None
        job = dict(job)
        completed, total = bounded_progress([dict(item) for item in items])
        return {
            "job_id": job["id"],
            "provider": job["provider"],
            "type": job["type"],
            "status": job["status"],
            "progress": {"completed": completed, "total": total},
            "error_class": job.get("error_class"),
        }
