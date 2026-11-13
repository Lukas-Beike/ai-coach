"""Provider-job contracts shared by the persistence and worker layers.

The module deliberately has no database, HTTP, or provider transport dependency.
Provider rules (accepted providers, job types, refresh fields) come from the
declarative provider registry. It owns the small state-machine vocabulary so the
server can persist jobs without duplicating validation and retry decisions in
request handlers.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import logging
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.vocabulary import ProviderId
from backend.runtime.clock import utc_now as system_utc_now
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

PROVIDERS = frozenset(DEFAULT_PROVIDER_REGISTRY.ids())
JOB_TYPES = frozenset(
    {
        "refresh",
        "activity_details",
        "plan_push",
        "competition_push",
        "nutrition_sync",
        "historical_backfill",
        "wellness_backfill",
        "stream_backfill",
    }
)
# Backfill chains and the sync-state cursor stream each one walks back.
WELLNESS_BACKFILL = "wellness_backfill"
WELLNESS_HISTORY_CURSOR = "wellness_history"
STREAM_BACKFILL = "stream_backfill"
STREAM_HISTORY_CURSOR = "stream_history"
BACKFILL_CURSOR_STREAMS: dict[str, str] = {
    "historical_backfill": "historical",
    WELLNESS_BACKFILL: WELLNESS_HISTORY_CURSOR,
    STREAM_BACKFILL: STREAM_HISTORY_CURSOR,
}
BACKFILL_JOB_TYPES = frozenset(BACKFILL_CURSOR_STREAMS)
# Jobs that only read providers and store the result locally: running one again
# is safe. Every other type (plan_push, competition_push, nutrition_sync) may
# have written to a remote service, so a lost outcome is never replayed for it.
REPLAYABLE_JOB_TYPES = frozenset({"refresh", "activity_details", *BACKFILL_JOB_TYPES})
_BACKFILL_PROVIDER_MESSAGES = {
    "historical_backfill": ("Historischer Backfill ist nur für Garmin zulässig."),
    WELLNESS_BACKFILL: "Der Wellness-Backfill ist nur für Garmin zulässig.",
    STREAM_BACKFILL: "Der Stream-Backfill ist nur für Garmin und Wahoo zulässig.",
}
# Built from the fixed type names above, never from request data.
_BACKFILL_TYPES_SQL = "({})".format(
    ", ".join(f"'{job_type}'" for job_type in sorted(BACKFILL_JOB_TYPES))
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
        "database_busy",
        "timeout",
        "provider_unavailable",
        "rate_limited",
        "temporary_error",
        "process_interrupted",
    }
)
SYNC_JOB_LIST_LIMIT = 50
# Retention of finished jobs: a completed job is pruned once it is older than
# the age bound, and the newest SYNC_JOB_KEEP_NEWEST jobs of any status stay
# regardless. Queued, running, failed and partial jobs are never pruned: they
# are work in flight or need the athlete's attention.
SYNC_JOB_RETENTION_DAYS = 30
SYNC_JOB_KEEP_NEWEST = 200
SYNC_JOB_MAX_ATTEMPTS = 3
# Served by idx_sync_jobs_backfill_end; keep the filter and the expression in step.
BACKFILL_CONTINUATION_SQL = (
    "SELECT 1 FROM sync_jobs WHERE provider=? AND type=? "
    "AND requested_by='backfill' AND json_extract(payload, '$.end_date')=? "
    "AND created_at>=? AND id!=? LIMIT 1"
)
MAX_JOB_REFRESH_DAYS = 3660
MAX_EMPTY_BACKFILL_CHUNKS = 100
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
    # The one documented, redacted cause: an item's already redacted detail, failed items first.
    detailed = [item for item in item_dtos if item["error_detail"]]
    detailed.sort(key=lambda item: item["status"] != "failed")
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
        "error_detail": detailed[0]["error_detail"] if detailed else None,
        "items": item_dtos,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


# Item ids are f"{job_id}-{index}" and every item of a job shares one timestamp, so
# the text id sorts "-10" before "-2". Order by the numeric index; ids that do not
# follow that format keep a stable id order.
ITEM_ORDER = (
    "created_at, CASE WHEN substr(id, 1, length(job_id) + 1) = job_id || '-' "
    "THEN CAST(substr(id, length(job_id) + 2) AS INTEGER) ELSE 0 END, id"
)
# Items that finished successfully are never rewritten by a later failure or retry.
_SETTLED_ITEMS = "status NOT IN ('completed', 'skipped')"
# Only automatic requesters coalesce; an explicit user or coach request always
# queues. A "backfill" continuation carries the next chunk's end_date cursor, so it
# is never folded into another job: that would drop the cursor and stop the chain.
_COALESCED_REQUESTERS = frozenset({"scheduler", "startup", "connection"})
_COALESCED_TYPES = frozenset({"refresh", *BACKFILL_JOB_TYPES})


def read_job(db: Any, job_id: str) -> tuple[Any | None, builtins.list[Any]]:
    """Read one job and its ordered items through a caller-owned connection."""
    job = db.execute("SELECT * FROM sync_jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        return None, []
    items = db.execute(
        f"SELECT * FROM sync_job_items WHERE job_id=? ORDER BY {ITEM_ORDER}", (job_id,)
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


def last_finished_at(db: Any, provider: str) -> tuple[str | None, str | None]:
    """Latest finish of a job that reached the provider and of a failed job.

    A completed or partial job reached the provider; a failed one did not.
    """
    row = db.execute(
        "SELECT "
        "MAX(CASE WHEN status IN ('completed', 'partial') THEN finished_at END) AS ok, "
        "MAX(CASE WHEN status = 'failed' THEN finished_at END) AS failed "
        "FROM sync_jobs WHERE provider=?",
        (provider,),
    ).fetchone()
    return row["ok"], row["failed"]


def utc_timestamp(now: datetime | None = None) -> str:
    """Return a stable UTC timestamp for durable job records."""
    value = now or datetime.fromisoformat(system_utc_now())
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def validate_job_request(
    provider: Any,
    job_type: Any,
    payload: Any = None,
) -> dict[str, Any]:
    """Validate and copy the bounded provider-job envelope."""
    provider_value = str(provider or "").strip().casefold()
    if provider_value not in DEFAULT_PROVIDER_REGISTRY.ids():
        raise JobValidationError("Unsupported provider.")
    type_value = str(job_type or "").strip().casefold()
    if type_value not in JOB_TYPES:
        raise JobValidationError("Unsupported job type.")
    # The refresh normalizer does not consult supports_job, so gate it here.
    if type_value == "refresh" and not DEFAULT_PROVIDER_REGISTRY.supports_job(
        provider_value, type_value
    ):
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
    provider: Any,
    job_type: Any,
    payload: Any = None,
    *,
    all_sync_days: int,
    enforce_period_limit: bool = False,
) -> dict[str, Any]:
    """Validate and normalize the provider-specific payload persisted for a job.

    ``enforce_period_limit`` applies the provider's own sync-window limit to new
    refresh requests. Persisted jobs are normalized again at execution without
    it, so a job queued under an older limit still runs.
    """
    envelope = validate_job_request(provider, job_type, payload)
    provider_value = envelope["provider"]
    type_value = envelope["type"]
    values = envelope["payload"]
    if type_value in BACKFILL_JOB_TYPES and not DEFAULT_PROVIDER_REGISTRY.supports_job(
        provider_value, type_value
    ):
        raise JobValidationError(_BACKFILL_PROVIDER_MESSAGES[type_value])
    if type_value == "activity_details":
        normalized_payload = _normalize_activity_details_job(provider_value, values)
    elif type_value == "nutrition_sync":
        normalized_payload = _normalize_nutrition_sync_job(provider_value, values)
    elif type_value == "competition_push":
        normalized_payload = _normalize_competition_push_job(provider_value, values)
    elif type_value == "plan_push":
        normalized_payload = _normalize_plan_push_job(provider_value, values)
    else:
        normalized_payload = _normalize_refresh_job(
            provider_value,
            values,
            all_sync_days,
            enforce_period_limit,
            historical=type_value in BACKFILL_JOB_TYPES,
        )
    return {
        "provider": provider_value,
        "type": type_value,
        "payload": normalized_payload,
    }


def _normalize_activity_details_job(
    provider: str, values: dict[str, Any]
) -> dict[str, Any]:
    supported = DEFAULT_PROVIDER_REGISTRY.supports_job(provider, "activity_details")
    if not supported or set(values) != {"activity_id"}:
        raise JobValidationError("Ungültiger Aktivitätsdetailauftrag.")
    value = values.get("activity_id")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise JobValidationError("Die Aktivitäts-ID ist ungültig.")
    return {"activity_id": value}


def _normalize_nutrition_sync_job(
    provider: str, values: dict[str, Any]
) -> dict[str, Any]:
    allowed_fields = {"date", "pending_limit", "approval_manifest"}
    supported = DEFAULT_PROVIDER_REGISTRY.supports_job(provider, "nutrition_sync")
    if not supported or set(values) - allowed_fields:
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


def _normalize_competition_push_job(
    provider: str, values: dict[str, Any]
) -> dict[str, Any]:
    if not DEFAULT_PROVIDER_REGISTRY.supports_job(provider, "competition_push"):
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


def _normalize_plan_push_entry(entry: Any, *, removable: bool) -> dict[str, Any]:
    workout_id = (
        str(entry.get("library_workout_id") or "") if isinstance(entry, dict) else ""
    )
    if not isinstance(entry, dict) or not re.fullmatch(r"[0-9a-f-]{36}", workout_id):
        raise JobValidationError("Jede Plan-Push-Einheit benötigt eine lokale UUID.")
    if "remove" in entry:
        # Only Garmin and Wahoo remove what they hold; elsewhere the flag would be
        # dropped and the entry silently pushed instead.
        if not removable or entry["remove"] is not True:
            raise JobValidationError(
                "remove ist nur für Garmin und Wahoo mit true zulässig."
            )
        return {"library_workout_id": workout_id, "remove": True}
    payload_hash = str(entry.get("expected_payload_hash") or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(payload_hash):
        raise JobValidationError(
            "Jede Plan-Push-Einheit benötigt einen aktuellen Payload-Hash."
        )
    return {"library_workout_id": workout_id, "expected_payload_hash": payload_hash}


def _normalize_plan_push_job(provider: str, values: dict[str, Any]) -> dict[str, Any]:
    if not DEFAULT_PROVIDER_REGISTRY.supports_job(provider, "plan_push"):
        raise JobValidationError(
            "Plan-Push-Jobs sind nur für Intervals.icu, Wahoo und Garmin zulässig."
        )
    if set(values) - {"entries", "reason", "repair"}:
        raise JobValidationError("Ein Plan-Push-Job enthält nicht unterstützte Felder.")
    entries = values.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 28:
        raise JobValidationError(
            "Ein Plan-Push-Job benötigt 1 bis 28 ausgewählte Einheiten."
        )
    removable = provider in {ProviderId.GARMIN.value, ProviderId.WAHOO.value}
    normalized_entries = [
        _normalize_plan_push_entry(entry, removable=removable) for entry in entries
    ]
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
    provider_value: str,
    values: dict[str, Any],
    all_sync_days: int,
    enforce_period_limit: bool,
    *,
    historical: bool = False,
) -> dict[str, Any]:
    # A backfill chain carries its count of consecutive empty chunks in the job.
    allowed = DEFAULT_PROVIDER_REGISTRY.refresh_fields(provider_value)
    if historical:
        allowed = allowed | {"empty_chunks", "end_date"}
    if set(values) - allowed:
        raise JobValidationError(UNSUPPORTED_JOB_FIELDS_ERROR)

    normalized_payload: dict[str, Any] = {}
    if historical and "empty_chunks" in values:
        normalized_payload["empty_chunks"] = _normalize_empty_chunks(
            values["empty_chunks"]
        )
    if "days" in values:
        max_days = MAX_JOB_REFRESH_DAYS
        if enforce_period_limit:
            max_days = min(
                max_days, DEFAULT_PROVIDER_REGISTRY.max_sync_days(provider_value)
            )
        normalized_payload["days"] = _normalize_refresh_days(
            values["days"], all_sync_days, max_days
        )
    if "force" in values:
        normalized_payload["force"] = _normalize_refresh_flag(values["force"], "force")
    if "end_date" in values:
        normalized_payload["end_date"] = _normalize_refresh_end_date(values["end_date"])
    if values.get("reason") is not None:
        normalized_payload["reason"] = _normalize_refresh_reason(values["reason"])
    return normalized_payload


def _normalize_refresh_days(value: Any, all_sync_days: int, max_days: int) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise JobValidationError("Der Synchronisationszeitraum ist ungültig.") from exc
    if days != all_sync_days and (days < 1 or days > max_days):
        raise JobValidationError("Der Synchronisationszeitraum ist zu groß.")
    return days


def _normalize_empty_chunks(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise JobValidationError("Der Backfill-Leerzähler ist ungültig.") from exc
    if count < 0 or count > MAX_EMPTY_BACKFILL_CHUNKS:
        raise JobValidationError("Der Backfill-Leerzähler ist ungültig.")
    return count


def _normalize_refresh_flag(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise JobValidationError(f"{field} muss ein Boolean sein.")
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
        *,
        foreground_busy: Callable[[], bool] | None = None,
        held_providers: Callable[[], Collection[str]] | None = None,
    ):
        self._database_manager = database_manager
        self._now = now
        self._uuid_factory = uuid_factory
        self._foreground_busy = foreground_busy
        # Providers whose queued jobs stay unclaimed (a running full resync).
        self._held_providers = held_providers

    def state(self, job_id: str) -> dict[str, Any] | None:
        # Job reads are pure SELECTs: a WAL snapshot never waits behind a sync.
        with self._database_manager.read_snapshot() as db:
            job, items = read_job(db, job_id)
            return job_dto(job, items) if job else None

    def list(self, limit: int) -> builtins.list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), SYNC_JOB_LIST_LIMIT))
        with self._database_manager.read_snapshot() as db:
            return list_jobs(db, bounded_limit)

    def active(self, provider: str, job_type: str) -> bool:
        with self._database_manager.reader() as db:
            return has_active_job(db, provider, job_type)

    def prune_finished(
        self,
        *,
        retention_days: int = SYNC_JOB_RETENTION_DAYS,
        keep_newest: int = SYNC_JOB_KEEP_NEWEST,
    ) -> int:
        """Delete old completed jobs and their items; return how many jobs went.

        A job is pruned only when it completed more than ``retention_days`` ago
        and is not among the ``keep_newest`` most recently created jobs.
        """
        now = datetime.fromisoformat(self._now())
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = (now - timedelta(days=max(1, retention_days))).isoformat()
        with self._database_manager.unit_of_work() as db:
            stale = (
                "SELECT id FROM sync_jobs WHERE status='completed' "
                "AND COALESCE(finished_at, updated_at, created_at) < ? "
                "AND id NOT IN (SELECT id FROM sync_jobs "
                "ORDER BY created_at DESC, id DESC LIMIT ?)"
            )
            parameters = (cutoff, max(0, keep_newest))
            db.execute(
                f"DELETE FROM sync_job_items WHERE job_id IN ({stale})", parameters
            )
            return int(
                db.execute(
                    f"DELETE FROM sync_jobs WHERE id IN ({stale})", parameters
                ).rowcount
            )

    def has_backfill_continuation(
        self,
        provider: str,
        end_date: str,
        created_since: str,
        job_type: str = "historical_backfill",
        exclude_job_id: str = "",
    ) -> bool:
        """Report whether a backfill chain already continued to ``end_date``.

        ``exclude_job_id`` is the job asking: a chunk that re-reads its own window
        (a skipped file) names its own end day and must not count as its successor.
        """
        with self._database_manager.reader() as db:
            row = db.execute(
                BACKFILL_CONTINUATION_SQL,
                (provider, job_type, end_date, created_since, exclude_job_id),
            ).fetchone()
            return row is not None

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
                envelope.get("provider"),
                envelope.get("type"),
                envelope.get("payload"),
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
                normalized["type"] in _COALESCED_TYPES
                and requested in _COALESCED_REQUESTERS
            ):
                existing = db.execute(
                    "SELECT * FROM sync_jobs WHERE provider=? AND type=? "
                    "AND status IN ('queued', 'running') ORDER BY created_at, id LIMIT 1",
                    (normalized["provider"], normalized["type"]),
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
        """Settle the jobs a stopped process left ``running``; return the requeued.

        A restart is a lost outcome like any other (#2137, A-501): a job that may
        have written to a remote service, or that used up its attempts, fails
        with ``outcome_not_persisted`` instead of running again.
        """
        self._fail_unreplayable_running()
        now = self._now()
        with self._database_manager.unit_of_work() as db:
            resumed = self._requeue_running(db, now)
            # Callers run before the workers start or under the drained restore
            # gate, so no competition sync can be in flight either.
            db.execute(
                "UPDATE kv SET value='0', updated_at=? "
                "WHERE key='competition_sync_running' AND value!='0'",
                (now,),
            )
            db.execute(
                "UPDATE kv SET value='', updated_at=? "
                "WHERE key='competition_sync_status' AND value!=''",
                (now,),
            )
            return resumed

    def requeue_unowned_running(self) -> int:
        """Settle ``running`` jobs while the single worker is between claims.

        Only the worker runs jobs and it calls this before each claim, so a row
        still ``running`` then lost its outcome (a failed write). A read-only job
        (``REPLAYABLE_JOB_TYPES``) runs again instead of blocking its provider's
        scheduled work until a restart. A job that may have written to a remote
        service, or that used up its attempts, is marked failed with
        ``outcome_not_persisted`` and its open items fail with it: only the
        athlete's explicit resolve runs it again. Returns how many jobs were settled.
        """
        failed, replayable = self._fail_unreplayable_running()
        if not replayable:
            return failed
        with self._database_manager.unit_of_work() as db:
            return failed + self._requeue_running(db, self._now())

    def _fail_unreplayable_running(self) -> tuple[int, int]:
        """Fail running jobs with remote effects or no attempts left.

        Returns how many failed and how many running jobs remain to requeue.
        """
        with self._database_manager.reader() as db:
            running = db.execute(
                "SELECT id, type, attempts FROM sync_jobs WHERE status='running'"
            ).fetchall()
        failed = 0
        for row in running:
            if (
                row["type"] not in REPLAYABLE_JOB_TYPES
                or int(row["attempts"] or 0) >= SYNC_JOB_MAX_ATTEMPTS
            ):
                self.update(row["id"], "failed", "outcome_not_persisted")
                failed += 1
        return failed, len(running) - failed

    def _requeue_running(self, db: Any, now: str) -> int:
        jobs = db.execute("SELECT id FROM sync_jobs WHERE status='running'").fetchall()
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
        """Claim the oldest due job; backfill jobs yield to all other work.

        While the Coach has queued or running work, backfill jobs stay queued so
        the single database writer remains free for the athlete's request. Jobs
        of a provider whose full resync is running stay queued as well: they are
        neither claimed nor charged an attempt, and run once the resync ends.
        """
        now = self._now()
        hold_backfill = self._foreground_busy is not None and self._foreground_busy()
        held = tuple(self._held_providers()) if self._held_providers else ()
        with self._database_manager.unit_of_work() as db:
            candidate = db.execute(
                "SELECT id FROM sync_jobs WHERE status='queued' "
                "AND (available_at IS NULL OR available_at<=?) "
                + (f"AND type NOT IN {_BACKFILL_TYPES_SQL} " if hold_backfill else "")
                # Placeholders only; the provider names are bound parameters.
                + (
                    f"AND provider NOT IN ({', '.join('?' * len(held))}) "
                    if held
                    else ""
                )
                + f"ORDER BY type IN {_BACKFILL_TYPES_SQL}, created_at, id LIMIT 1",
                (now, *held),
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
            if not job:
                return None
            claimed = dict(job)
            # A retried or resumed job re-runs only the items still open.
            claimed["settled_item_keys"] = [
                str(row["item_key"])
                for row in db.execute(
                    "SELECT item_key FROM sync_job_items WHERE job_id=? "
                    "AND status IN ('completed', 'skipped')",
                    (job_id,),
                ).fetchall()
            ]
            return claimed

    def update(
        self,
        job_id: str,
        item_status: str,
        error_class: str | None = None,
        error_detail: str | None = None,
    ) -> dict[str, Any] | None:
        """Update every unfinished item; completed items are kept as they are.

        Detail must already be redacted and is clipped here.
        """
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
                f"WHERE job_id=? AND {_SETTLED_ITEMS}",
                (item_status, error_class, detail, now, job_id),
            )
            items = [
                dict(item)
                for item in db.execute(
                    f"SELECT status FROM sync_job_items WHERE job_id=? ORDER BY {ITEM_ORDER}",
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
                    f"SELECT id, item_key, status FROM sync_job_items WHERE job_id=? ORDER BY {ITEM_ORDER}",
                    (job_id,),
                ).fetchall()
            ]
            stored_by_key = {
                str(item.get("item_key") or ""): item for item in stored_items
            }
            if len(stored_items) == 1 and len(item_results) > 1:
                # One stored item stands for the whole job; a later success
                # must not hide an earlier failure.
                failed = [item for item in item_results if self._failed(item)]
                item_results = failed[:1] or item_results[-1:]
            # Unkeyed results map by position only when none is keyed and counts agree.
            positional = len(item_results) == len(stored_items) and not any(
                self._result_key(item) for item in item_results
            )
            for index, item in enumerate(item_results):
                self._update_result_item(
                    db,
                    item,
                    index,
                    stored_items,
                    stored_by_key,
                    positional,
                    redact,
                    now,
                )
            # An item the result did not report has an unknown outcome; fail it so
            # it stays retryable instead of leaving the job running forever.
            db.execute(
                "UPDATE sync_job_items SET status='failed', error_class='plan_push_error', "
                "error_detail='No result was reported for this item.', updated_at=? "
                "WHERE job_id=? AND status IN ('queued', 'running')",
                (now, job_id),
            )
            items = [
                dict(item)
                for item in db.execute(
                    f"SELECT status FROM sync_job_items WHERE job_id=? ORDER BY {ITEM_ORDER}",
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
    def _failed(item: Mapping[str, Any]) -> bool:
        outcome = str(item.get("status") or "error").strip().casefold()
        return outcome not in {"synced", "already_synced", "skipped"}

    @staticmethod
    def _result_key(item: Mapping[str, Any]) -> str:
        return str(item.get("library_workout_id") or item.get("item_key") or "").strip()

    @staticmethod
    def _update_result_item(
        db: Any,
        item: dict[str, Any],
        index: int,
        stored_items: builtins.list[dict[str, Any]],
        stored_by_key: dict[str, dict[str, Any]],
        positional: bool,
        redact: Callable[[str], str],
        now: str,
    ) -> None:
        item_key = SyncJobStore._result_key(item)
        target = stored_by_key.get(item_key)
        if target is None and len(stored_items) == 1:
            target = stored_items[0]
        if target is None and positional:
            target = stored_items[index]
        if target is None:
            return
        outcome = str(item.get("status") or "error").strip().casefold()
        item_state = (
            "completed"
            if outcome in {"synced", "already_synced", "skipped"}
            else "failed"
        )
        if item_state == "failed" and target.get("status") in {"completed", "skipped"}:
            # A settled item stays settled; a re-run never downgrades it.
            return
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
                f"WHERE job_id=? AND {_SETTLED_ITEMS}",
                (error_class, clipped_detail, now, job_id),
            )
            return True

    def defer(self, job: Mapping[str, Any], available_at: str) -> bool:
        """Requeue a claimed job without charging the attempt its claim counted.

        For a job that met a busy provider lock: it did no work, so it retries at
        ``available_at`` with the attempt budget it had before the claim.
        """
        now = self._now()
        try:
            attempts = max(0, int(job.get("attempts") or 1) - 1)
            job_id = str(job["id"])
            scheduled_at = self._scheduled_at(available_at, now)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise SyncJobInvalidOperationError(
                "Claimed sync job or retry time is invalid."
            ) from exc
        with self._database_manager.unit_of_work() as db:
            self._transition(
                db,
                job_id,
                "running",
                "queued",
                {
                    "attempts": attempts,
                    "available_at": scheduled_at,
                    "finished_at": None,
                    "error_class": None,
                    "updated_at": now,
                },
            )
            db.execute(
                "UPDATE sync_job_items SET status='queued', "
                "attempts=MAX(attempts-1, 0), updated_at=? "
                f"WHERE job_id=? AND {_SETTLED_ITEMS}",
                (now, job_id),
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
        logging.getLogger("intervals_coach").warning(
            "Sync job status transition rejected",
            extra={
                "event": "sync_job_transition_rejected",
                "context": {
                    "expected_status": expected_status,
                    "target_status": target_status,
                },
            },
        )

    @staticmethod
    def _scheduled_at(value: str | None, now: str) -> str:
        if value is None:
            return now
        try:
            return datetime.fromisoformat(str(value)).astimezone(UTC).isoformat()
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
