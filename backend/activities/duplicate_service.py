"""Authorized deletion of duplicate Intervals.icu activities."""

from __future__ import annotations

from typing import Any

from backend.activities.activity_reference import (
    ActivityReferenceResolver,
    NoActivityReferences,
    resolve_duplicate_ids,
)
from backend.activities.duplicate_inspection import DuplicateInspector
from backend.activities.duplicates import (
    remove_activity_from_snapshot,
    validate_duplicate_delete,
)
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.snapshot_projection import intervals_snapshot_is_stripped
from backend.providers.source_labels import SourceView, provider_label
from backend.runtime.ports import ActivityRowReader, ProviderSnapshotReader


class DuplicateActivityService:
    """Own the remote-delete use case and its local snapshot and canonical records."""

    def __init__(
        self,
        database_manager: Any,
        snapshot_repository: Any,
        snapshot_reader: ProviderSnapshotReader,
        row_reader: ActivityRowReader,
        clock: Any,
        event_buffer: Any,
        references: ActivityReferenceResolver | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._snapshot_repository = snapshot_repository
        self._snapshot_reader = snapshot_reader
        self._inspector = DuplicateInspector(
            database_manager, snapshot_reader, row_reader
        )
        self._clock = clock
        self._event_buffer = event_buffer
        self._row_reader = row_reader
        self._references = NoActivityReferences() if references is None else references

    def delete(self, payload: Any, intervals_client: Any) -> dict[str, Any]:
        """Delete the confirmed Garmin copy and retain the Wahoo activity."""
        current = self._inspector.latest()
        payload = resolve_duplicate_ids(payload, self._references)
        canonical_id, duplicate_id = validate_duplicate_delete(payload, current)

        intervals_client.delete_activity(duplicate_id)

        synced_at = self._clock()
        with self._database_manager.unit_of_work() as db:
            snapshot = self._snapshot_reader.latest_snapshot(db)
            updated = remove_activity_from_snapshot(
                snapshot,
                duplicate_id,
                synced_at=synced_at,
            )
            # Same transaction: table-served readers must not return the removed copy.
            canonical_store.mark_activity_deleted(
                db,
                ProviderId.INTERVALS.value,
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id=duplicate_id,
                now=synced_at,
            )
            if updated is not None:
                self._save_snapshot(db, updated, synced_at)

        self._event_buffer.publish(
            "provider",
            {"provider": ProviderId.INTERVALS, "status": "duplicate_deleted"},
        )
        return {
            "status": "deleted",
            "deleted_activity_id": duplicate_id,
            "kept_activity_id": canonical_id,
            "kept_source": provider_label(ProviderId.WAHOO, SourceView.DUPLICATE),
        }

    def _save_snapshot(self, db: Any, snapshot: dict[str, Any], synced_at: Any) -> None:
        """Save the snapshot; a stripped one keeps the live activity count."""
        if not intervals_snapshot_is_stripped(snapshot):
            self._snapshot_repository.save(db, snapshot, synced_at)
            return
        self._snapshot_repository.save(
            db,
            snapshot,
            synced_at,
            activity_count=len(self._row_reader.activity_rows(db, limit=500)),
        )
