"""Store provider snapshots without the sections the canonical tables serve.

Every Intervals.icu sync ingests its payload into the canonical tables in the same
transaction as the snapshot. Once the tables serve reads (``CanonicalTableServing``),
the snapshot no longer needs its activity sections: ``recent_activities`` and
``raw_provider_data.activities``. They are left out of the stored row and the row is
marked (``canonical_sections``). Until the tables serve, for example right after an
upgrade, the snapshot is stored in full, because the backfill still reads it.

Sections that stay in the snapshot, and why:

* ``recent_wellness`` and ``raw_provider_data.wellness`` carry wellness fields that
  have no canonical observation (``tsb``, ``rampRate``, subjective scores, eFTP), and
  the performance readers overlay observations on these rows.
* ``athlete``, ``raw_provider_data.athlete``, ``upcoming_calendar``,
  ``provider_sync``, ``cycling_power_profile`` and ``synced_at`` are read directly.

Only the storage is reduced. The ingest and the coverage summary run on the full
in-memory payload before the stripped snapshot is stored, in the same unit of work.

The next incremental or historical sync merges its window with the previous
snapshot. When that snapshot is stripped, ``merge_base`` rebuilds its activity
sections from the canonical activity rows, so the merge sees what it saw before.
"""

from __future__ import annotations

from datetime import tzinfo
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.providers.snapshot_projection import (
    intervals_activity_sections_are_mapped,
    intervals_snapshot_is_stripped,
    restore_intervals_activity_sections,
    strip_intervals_activity_sections,
    without_intervals_activities,
)
from backend.runtime.ports import ActivityRowReader, CanonicalTableServing
from backend.sync.intervals_compaction import compact_activity_rows
from backend.sync.state import SyncStateRepository


class SnapshotStorage:
    """Writes snapshots in the form the serving source needs and reads merge bases.

    Without ``database_manager``, ``serving`` and ``rows`` every snapshot is stored
    and read unchanged.
    """

    def __init__(
        self,
        state: SyncStateRepository,
        *,
        database_manager: DatabaseManager | None = None,
        serving: CanonicalTableServing | None = None,
        rows: ActivityRowReader | None = None,
    ) -> None:
        self._state = state
        self._database_manager = database_manager
        self._serving = serving
        self._rows = rows

    def merge_base(self, db: Any | None = None) -> dict[str, Any] | None:
        """Return the latest snapshot with its activity sections, rebuilt if stripped.

        Activities whose canonical record is tombstoned (a confirmed duplicate delete,
        a provider disappearance) are left out, so a merge never re-adds them. A row
        the provider returns again is ingested from the fresh fetch as usual.
        """
        if db is not None:
            return self._merge_base(db)
        if self._database_manager is None or self._rows is None:
            return self._state.latest_snapshot()
        with self._database_manager.unit_of_work() as unit_db:
            return self._merge_base(unit_db)

    def _merge_base(self, db: Any) -> dict[str, Any] | None:
        snapshot = self._state.latest_snapshot(db)
        if snapshot is None:
            return snapshot
        if not intervals_snapshot_is_stripped(snapshot):
            # A snapshot that still carries its activity sections (a rejected row,
            # or stored before the backfill) must not bring back a tombstoned
            # activity: the ingest of the merge would revive it.
            return without_intervals_activities(
                snapshot,
                canonical_store.deleted_activity_ids(db, ProviderId.INTERVALS.value),
            )
        if (
            self._serving is None
            or self._rows is None
            or not self._serving.serves_tables(db)
        ):
            # The activities live only in the tables; merging against an empty
            # history would store a snapshot that forgets them.
            raise AppError(
                409,
                "Die gespeicherten Aktivitäten sind noch nicht lesbar.",
                reason="canonical_tables_unavailable",
            )
        rows = self._rows.activity_rows(db)
        return restore_intervals_activity_sections(
            snapshot, raw_rows=rows, compact_rows=compact_activity_rows(rows)
        )

    def save(
        self,
        db: Any,
        snapshot: dict[str, Any],
        *,
        zone: tzinfo,
        update_full_sync: bool | None = True,
        activity_days: int | None = None,
    ) -> None:
        """Store the snapshot in the caller's unit of work, stripped when tables serve.

        The sections stay whenever an activity row would not reach the tables, so
        a row the mapper cannot handle is never lost. The recent-activity count of
        the full snapshot is kept for the state version.
        """
        options: dict[str, Any] = {"update_full_sync": update_full_sync}
        if activity_days is not None:
            options["activity_days"] = activity_days
        if (
            self._serving is None
            or not self._serving.serves_tables(db)
            or not intervals_activity_sections_are_mapped(snapshot, zone=zone)
        ):
            self._state.save_snapshot(snapshot, **options)
            return
        recent = snapshot.get("recent_activities")
        self._state.save_snapshot(
            strip_intervals_activity_sections(snapshot),
            activity_count=len(recent) if isinstance(recent, list) else 0,
            **options,
        )
