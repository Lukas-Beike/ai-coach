"""Read the newest Wahoo/Garmin duplicate pair from the canonical activity records."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import tzinfo
from typing import Any

from backend.activities.canonical_sessions import wahoo_garmin_copy_match
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, Sport
from backend.runtime.ports import ActivityReader

_NAME_LIMIT = 200


class DuplicateInspector:
    """Find the current duplicate pair from the canonical activity tables.

    ``activities`` must be the table-backed reader, never the read selector: before
    the first backfill the selector serves the snapshot projection, which does not
    know a tombstoned copy. Only active Intervals.icu records are compared, so a
    removed duplicate is no longer reported (a pair may be missed before the
    backfill, never repeated). The stored snapshot is not read.
    """

    def __init__(
        self,
        database_manager: Any,
        activities: ActivityReader,
        zone: Callable[[], tzinfo],
    ) -> None:
        self._database_manager = database_manager
        self._activities = activities
        self._zone = zone

    def latest(self) -> dict[str, Any] | None:
        """Return the newest exact-source ride pair, always keeping Wahoo canonical."""
        with self._database_manager.read_snapshot() as db:
            records = self._activities.activities(db)
        return latest_wahoo_garmin_duplicate(records, zone=self._zone())


def latest_wahoo_garmin_duplicate(
    records: Iterable[ActivityRecord], *, zone: tzinfo
) -> dict[str, Any] | None:
    """Return the manifest of the newest Wahoo/Garmin ride pair that holds the newest activity.

    ``snapshot_synced_at`` is the newest canonical fetch time of the two records,
    so a later fetch of either record invalidates an earlier confirmation.
    """
    intervals = [
        record
        for record in records
        if record.provenance.provider is ProviderId.INTERVALS
    ]
    if not intervals:
        return None
    latest = max(intervals, key=lambda record: (record.started_at, record.activity_id))
    rides = [record for record in intervals if record.sport is Sport.RIDE]
    wahoo = [r for r in rides if r.provenance.recorded_by is RecordingOrigin.WAHOO]
    garmin = [r for r in rides if r.provenance.recorded_by is RecordingOrigin.GARMIN]
    pairs = [
        (keep, copy)
        for keep in wahoo
        for copy in garmin
        if keep.activity_id != copy.activity_id
        and latest.activity_id in {keep.activity_id, copy.activity_id}
        and wahoo_garmin_copy_match(keep, copy, zone=zone)
    ]
    if not pairs:
        return None
    keep, copy = max(pairs, key=lambda pair: pair[0].started_at)
    fetched = [
        record.provenance.retrieved_at
        for record in (keep, copy)
        if record.provenance.retrieved_at is not None
    ]
    wall = keep.started_at.astimezone(zone).replace(tzinfo=None)
    return {
        "canonical_id": keep.activity_id,
        "canonical_name": (keep.name or "Wahoo-Radeinheit")[:_NAME_LIMIT],
        "duplicate_id": copy.activity_id,
        "duplicate_name": (copy.name or "Garmin-Radeinheit")[:_NAME_LIMIT],
        "start_date_local": wall.isoformat(timespec="seconds"),
        "moving_time": keep.duration_s,
        "distance": keep.distance_m,
        "snapshot_synced_at": max(fetched).isoformat() if fetched else None,
    }
