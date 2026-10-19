"""Read-only Garmin activity detail loading for local activities.

Two entry points share one map-and-store path. ``refresh`` fetches the bounded
detail sets of one Garmin activity on demand. ``backfill`` runs after a
successful Garmin sync, under the sync lock, and fetches a small batch of recent
activities, newest first, so the last 90 days fill up over several syncs. It
pauses after a Garmin rate limit and skips manual activities. Kinds a payload
does not return keep their stored sets. Nothing is written back to Garmin.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from backend.canonical.mapping import MappingResult
from backend.canonical.vocabulary import ActivityRecordState, RecordingOrigin
from backend.db.activity_detail_store import (
    activity_detail_backfill_candidates,
    activity_detail_backfill_universe,
    detail_sets_for,
    replace_detail_set,
)
from backend.db.canonical_store import (
    ACTIVITY_ID_PREFIX,
    active_provider_record_hash,
    activity_record_for_session,
    activity_record_link,
)
from backend.errors import AppError
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.descriptors import GARMIN_ID
from backend.providers.garmin_activity_detail_mapping import (
    MAPPER_VERSION,
    map_garmin_activity_detail,
)
from backend.sync.activity_details import normalize_activity_id
from backend.sync.garmin import GARMIN_CAPABILITY_PAUSE_SECONDS
from backend.sync.refresh import sync_job_error_class

_LOGGER = logging.getLogger(__name__)
COOLDOWN: Final = timedelta(minutes=10)
BACKFILL_BATCH_SIZE: Final = 10
BACKFILL_WINDOW: Final = timedelta(days=90)
BACKFILL_RATE_LIMIT_PAUSE: Final = timedelta(seconds=GARMIN_CAPABILITY_PAUSE_SECONDS)
BACKFILL_STATE_KEY: Final = "garmin_activity_detail_backfill"
DETAIL_CAPABILITIES: Final = (
    "activity_details",
    "activity_splits",
    "activity_hr_zones",
    "activity_power_zones",
)


@dataclass(frozen=True)
class _BackfillState:
    paused_until: datetime | None = None
    empty: dict[str, str] = field(default_factory=dict)


class GarminActivityDetailService:
    """Fetch Garmin activity detail sets on demand or in small batches; never remove sets."""

    def __init__(
        self,
        *,
        database_manager: Any,
        reader: Any,
        configured: Callable[[], bool],
        guard: Callable[[], AbstractContextManager[Any]],
        utc_now: Callable[[], str],
        key_values: Any | None = None,
        capability_allowed: Callable[[str], bool] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._reader = reader
        self._configured = configured
        self._guard = guard
        self._utc_now = utc_now
        self._key_values = key_values
        self._capability_allowed = capability_allowed

    def refresh(self, activity_id: str) -> dict[str, Any]:
        requested = normalize_activity_id(activity_id)
        with self._database_manager.reader() as db:
            record = _resolve_record(db, requested)
        if record is None:
            raise _not_found()
        provider_activity_id = str(record["provider_activity_id"])
        recorded_by = _recorded_by(record["recorded_by"])
        if not self._configured():
            raise AppError(
                503, "Garmin ist nicht konfiguriert.", reason="not_configured"
            )
        if recorded_by == RecordingOrigin.MANUAL:
            return {
                "status": "skipped",
                "reason": "manual_activity",
                "activity_id": provider_activity_id,
            }
        with self._database_manager.reader() as db:
            stored = detail_sets_for(db, GARMIN_ID, provider_activity_id)
            current_summary = active_provider_record_hash(
                db, GARMIN_ID, ACTIVITY_RECORD_KIND, provider_activity_id
            )
        if _within_cooldown(stored, current_summary, _aware(self._utc_now())):
            return {
                "status": "unchanged",
                "activity_id": provider_activity_id,
                "kinds": sorted({item.detail.kind.value for item in stored}),
            }

        with self._guard():
            collected = self._reader.fetch_activity_detail(provider_activity_id)
            now = self._utc_now()
            mapped = _map_collected(collected, recorded_by=recorded_by, now=now)
        # Malformed parts are dropped by the mapper, so they count like failures.
        incomplete = bool(collected.get("errors") or mapped.issues)
        if not mapped.records:
            if incomplete:
                # Every requested part failed: report the job as failed.
                raise AppError(
                    502,
                    "Garmin hat keine Aktivitätsdetails geliefert.",
                    reason="activity_details_unavailable",
                )
            return {
                "status": "unchanged",
                "activity_id": provider_activity_id,
                "kinds": [],
            }
        if not self._store_records(provider_activity_id, mapped, now=now):
            raise _not_found()
        return {
            "status": "partial" if incomplete else "completed",
            "activity_id": provider_activity_id,
            "kinds": sorted({item.kind.value for item in mapped.records}),
        }

    def backfill(self, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        """Fetch details for a small batch of recent Garmin activities.

        The caller MUST already hold the Garmin sync lock and resync gate, as
        ``GarminSyncService`` does during a sync. This method does not take the
        non-blocking guard, because that guard would fail while the sync holds it.
        Returns counts only; no activity ids or provider messages.
        """
        if not self._configured():
            return _backfill_result("not_configured")
        if self._key_values is None or self._capability_allowed is None:
            raise RuntimeError("Garmin activity detail backfill is not composed.")
        now = _aware(self._utc_now())
        since = now - BACKFILL_WINDOW
        state = self._load_backfill_state()
        with self._database_manager.reader() as db:
            universe = activity_detail_backfill_universe(db, GARMIN_ID, since=since)
            # The limit covers every window record, so marks for empty activities
            # cannot push pending candidates out of the batch.
            candidates = activity_detail_backfill_candidates(
                db,
                GARMIN_ID,
                ACTIVITY_RECORD_KIND,
                since=since,
                limit=len(universe),
            )
        window_ids = set(universe)
        empty = {
            provider_activity_id: value
            for provider_activity_id, value in state.empty.items()
            if provider_activity_id in window_ids
        }
        pending = [
            item
            for item in candidates
            if empty.get(item["provider_activity_id"]) != item["summary_sha256"]
        ]
        paused_until = state.paused_until
        if paused_until is not None and paused_until <= now:
            paused_until = None
        if paused_until is not None or not self._detail_capabilities_allowed():
            self._save_backfill_state(paused_until=paused_until, empty=empty)
            return _backfill_result("paused", remaining=len(pending))
        batch = pending[:BACKFILL_BATCH_SIZE]
        if not batch:
            self._save_backfill_state(paused_until=None, empty=empty)
            return _backfill_result("completed")

        by_id = {item["provider_activity_id"]: item for item in batch}
        fetched = marked = skipped = 0
        status = "completed"
        details = self._reader.fetch_activity_details(
            list(by_id), cancel_event=cancel_event
        )
        try:
            for provider_activity_id, collected in details:
                candidate = by_id[provider_activity_id]
                observed = self._utc_now()
                mapped = _map_collected(
                    collected,
                    recorded_by=_recorded_by(candidate["recorded_by"]),
                    now=observed,
                )
                if collected.get("rate_limited"):
                    # Keep the parts that arrived, then stop until the pause ends.
                    if mapped.records and self._store_records(
                        provider_activity_id, mapped, now=observed
                    ):
                        fetched += 1
                    paused_until = _aware(observed) + BACKFILL_RATE_LIMIT_PAUSE
                    status = "rate_limited"
                    break
                if mapped.records:
                    if self._store_records(provider_activity_id, mapped, now=observed):
                        fetched += 1
                    else:
                        skipped += 1
                elif collected.get("errors"):
                    # Nothing is marked, so a later sync retries this activity.
                    status = "failed"
                    break
                else:
                    empty[provider_activity_id] = candidate["summary_sha256"]
                    marked += 1
                if not self._detail_capabilities_allowed():
                    status = "paused"
                    break
                if _is_set(cancel_event):
                    status = "cancelled"
                    break
        except Exception as error:  # noqa: BLE001 - backfill errors are logged by type and never stop the sync
            if sync_job_error_class(error) == "rate_limited":
                paused_until = _aware(self._utc_now()) + BACKFILL_RATE_LIMIT_PAUSE
                status = "rate_limited"
            else:
                status = "failed"
                _LOGGER.warning(
                    "garmin activity detail backfill stopped after an error",
                    extra={
                        "event": "garmin_activity_detail_backfill_failed",
                        "error_type": type(error).__name__,
                    },
                )
        finally:
            # Closing the generator persists the Garmin tokens on early stop.
            details.close()
        if status == "completed" and _is_set(cancel_event):
            status = "cancelled"
        self._save_backfill_state(paused_until=paused_until, empty=empty)
        return _backfill_result(
            status,
            fetched=fetched,
            empty=marked,
            remaining=len(pending) - fetched - marked - skipped,
        )

    def _store_records(
        self, provider_activity_id: str, mapped: MappingResult[Any], *, now: str
    ) -> bool:
        """Replace the mapped sets of one active record; False when it is no longer active."""
        with self._database_manager.unit_of_work() as db:
            # Re-check inside the write transaction: the record may have been
            # deleted or merged while the provider call was running.
            link = activity_record_link(db, GARMIN_ID, provider_activity_id)
            if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
                return False
            # The details belong to the activity summary stored right now.
            summary_sha256 = active_provider_record_hash(
                db, GARMIN_ID, ACTIVITY_RECORD_KIND, provider_activity_id
            )
            for item in mapped.records:
                replace_detail_set(
                    db,
                    item,
                    mapper_version=MAPPER_VERSION,
                    summary_sha256=summary_sha256,
                    now=now,
                )
        return True

    def _detail_capabilities_allowed(self) -> bool:
        allowed = self._capability_allowed
        return allowed is not None and all(
            allowed(capability) for capability in DETAIL_CAPABILITIES
        )

    def _backfill_key_values(self) -> Any:
        if self._key_values is None:
            raise RuntimeError("Garmin activity detail backfill is not composed.")
        return self._key_values

    def _load_backfill_state(self) -> _BackfillState:
        key_values = self._backfill_key_values()
        with self._database_manager.reader() as db:
            raw = key_values.get(db, BACKFILL_STATE_KEY)
        return _parse_backfill_state(raw)

    def _save_backfill_state(
        self, *, paused_until: datetime | None, empty: dict[str, str]
    ) -> None:
        key_values = self._backfill_key_values()
        stored: dict[str, Any] = {"empty": dict(sorted(empty.items()))}
        if paused_until is not None:
            stored["paused_until"] = paused_until.isoformat()
        with self._database_manager.unit_of_work() as db:
            key_values.set(db, BACKFILL_STATE_KEY, json.dumps(stored, sort_keys=True))


def _map_collected(
    collected: dict[str, Any], *, recorded_by: RecordingOrigin, now: str
) -> MappingResult[Any]:
    mapped = map_garmin_activity_detail(
        collected,
        recorded_by=recorded_by,
        retrieved_at=_aware(now),
    )
    if mapped.issues:
        _LOGGER.warning(
            "garmin activity detail mapping produced issues",
            extra={
                "event": "garmin_activity_detail_mapping_issues",
                "issues": len(mapped.issues),
            },
        )
    return mapped


def _resolve_record(db: Any, activity_id: str) -> dict[str, Any] | None:
    """Map a local ``act_`` session or a bare Garmin id to its active record."""
    if activity_id.startswith(ACTIVITY_ID_PREFIX):
        return activity_record_for_session(db, GARMIN_ID, activity_id)
    link = activity_record_link(db, GARMIN_ID, activity_id)
    if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
        return None
    return {
        "provider_activity_id": activity_id,
        "recorded_by": link["recorded_by"],
    }


def _not_found() -> AppError:
    return AppError(
        404,
        "Diese Aktivität ist lokal nicht vorhanden.",
        reason="activity_details_not_found",
    )


def _recorded_by(value: object) -> RecordingOrigin:
    if not isinstance(value, str):
        return RecordingOrigin.UNKNOWN
    try:
        return RecordingOrigin(value)
    except ValueError:
        return RecordingOrigin.UNKNOWN


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("utc_now must return an ISO timestamp with an offset")
    return parsed


def _within_cooldown(
    stored: list[Any], current_summary: str | None, now: datetime
) -> bool:
    """True when the stored sets match the current summary and are recent.

    A changed activity summary makes the stored sets stale, so it bypasses the
    cooldown.
    """
    if any(item.summary_sha256 != current_summary for item in stored):
        return False
    newest = max(
        (parsed for parsed in map(_stored_fetch_time, stored) if parsed is not None),
        default=None,
    )
    return newest is not None and now - newest < COOLDOWN


def _stored_fetch_time(item: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(item.fetched_at))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _parse_backfill_state(raw: object) -> _BackfillState:
    """Read the stored backfill state; unreadable content resets to an empty state."""
    if not isinstance(raw, str) or not raw:
        return _BackfillState()
    try:
        parsed = json.loads(raw)
    except ValueError:
        return _BackfillState()
    if not isinstance(parsed, dict):
        return _BackfillState()
    marks = parsed.get("empty")
    empty = (
        {str(key): str(value) for key, value in marks.items()}
        if isinstance(marks, dict)
        else {}
    )
    return _BackfillState(
        paused_until=_parse_time(parsed.get("paused_until")), empty=empty
    )


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _backfill_result(
    status: str, *, fetched: int = 0, empty: int = 0, remaining: int = 0
) -> dict[str, Any]:
    return {
        "status": status,
        "fetched": fetched,
        "empty": empty,
        "remaining": remaining,
    }


def _is_set(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()
