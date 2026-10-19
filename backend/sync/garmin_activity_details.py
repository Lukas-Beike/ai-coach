"""On-demand, read-only Garmin activity detail refresh for one local activity.

One job fetches the bounded detail sets of one Garmin activity, maps them with
Garmin provenance and replaces each returned kind in one transaction. Kinds the
payload does not return keep their stored sets. Nothing is scheduled, bulk
loaded or written back to Garmin.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any, Final

from backend.canonical.vocabulary import ActivityRecordState, RecordingOrigin
from backend.db.activity_detail_store import detail_sets_for, replace_detail_set
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

_LOGGER = logging.getLogger(__name__)
COOLDOWN: Final = timedelta(minutes=10)


class GarminActivityDetailService:
    """Fetch one Garmin activity's detail sets on demand; never remove sets."""

    def __init__(
        self,
        *,
        database_manager: Any,
        reader: Any,
        configured: Callable[[], bool],
        guard: Callable[[], AbstractContextManager[Any]],
        utc_now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._reader = reader
        self._configured = configured
        self._guard = guard
        self._utc_now = utc_now

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
        if _within_cooldown(stored, _aware(self._utc_now())):
            return {
                "status": "unchanged",
                "activity_id": provider_activity_id,
                "kinds": sorted({item.detail.kind.value for item in stored}),
            }

        with self._guard():
            collected = self._reader.fetch_activity_detail(provider_activity_id)
            now = self._utc_now()
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
        if not mapped.records:
            if collected.get("errors"):
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
        with self._database_manager.unit_of_work() as db:
            # Re-check inside the write transaction: the record may have been
            # deleted or merged while the provider call was running.
            link = activity_record_link(db, GARMIN_ID, provider_activity_id)
            if link is None or link["state"] != ActivityRecordState.ACTIVE.value:
                raise _not_found()
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
        return {
            "status": "partial" if collected.get("errors") else "completed",
            "activity_id": provider_activity_id,
            "kinds": sorted({item.kind.value for item in mapped.records}),
        }


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


def _within_cooldown(stored: list[Any], now: datetime) -> bool:
    """True when the newest stored fetch of this activity is under the cooldown."""
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
