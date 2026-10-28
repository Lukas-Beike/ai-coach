"""Authorized deletion of duplicate Intervals.icu activities."""

from __future__ import annotations

from typing import Any

from backend.activities.activity_reference import (
    ActivityReferenceResolver,
    NoActivityReferences,
    resolve_duplicate_ids,
)
from backend.activities.duplicate_inspection import DuplicateInspector
from backend.activities.duplicates import validate_duplicate_delete
from backend.canonical.vocabulary import ProviderId
from backend.db import canonical_store
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.source_labels import SourceView, provider_label


class DuplicateActivityService:
    """Own the remote-delete use case and its local canonical tombstones."""

    def __init__(
        self,
        database_manager: Any,
        inspector: DuplicateInspector,
        clock: Any,
        event_buffer: Any,
        references: ActivityReferenceResolver | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._inspector = inspector
        self._clock = clock
        self._event_buffer = event_buffer
        self._references = NoActivityReferences() if references is None else references

    def delete(self, payload: Any, intervals_client: Any) -> dict[str, Any]:
        """Delete the confirmed Garmin copy and retain the Wahoo activity."""
        current = self._inspector.latest()
        payload = resolve_duplicate_ids(payload, self._references)
        canonical_id, duplicate_id = validate_duplicate_delete(payload, current)

        intervals_client.delete_activity(duplicate_id)

        with self._database_manager.unit_of_work() as db:
            # Table-served readers must not return the removed copy.
            canonical_store.mark_activity_deleted(
                db,
                ProviderId.INTERVALS.value,
                record_kind=ACTIVITY_RECORD_KIND,
                provider_activity_id=duplicate_id,
                now=self._clock(),
            )

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
