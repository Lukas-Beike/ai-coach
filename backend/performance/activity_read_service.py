"""Completed-activity analysis combining activity reads and performance context."""

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from backend.activities import detail_projection
from backend.activities.activity_reference import ActivityReferenceResolver
from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
from backend.activities.read_service import ActivityReadService, _first_present
from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.performance.activity_validation import activity_performance_validation
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    performance_options,
    read_performance_inputs,
)
from backend.performance.context import current_performance_context
from backend.providers.source_labels import SourceView, provider_label
from backend.runtime.ports import ActivityRowReader, ProviderSnapshotReader


class ActivityAnalysisReadService(ActivityReadService):
    def __init__(
        self,
        database_manager: Any,
        snapshot_reader: ProviderSnapshotReader,
        row_reader: ActivityRowReader,
        feedback_service: Any,
        detail_store: ActivityDetailStore | None = None,
        *,
        read_equipment: Callable[[], dict[str, Any]] = dict,
        references: ActivityReferenceResolver | None = None,
        canonical: CanonicalPerformanceSource | None = None,
    ) -> None:
        super().__init__(
            database_manager,
            snapshot_reader,
            row_reader,
            feedback_service,
            detail_store,
            read_equipment=read_equipment,
            references=references,
        )
        self._canonical = canonical

    def _performance_inputs(
        self,
    ) -> tuple[dict[str, Any], CanonicalPerformanceInputs | None]:
        """Read the snapshot, and CTL and ATL in the same unit of work when configured."""
        source = self._canonical
        if source is None:
            return self._snapshot(), None
        with source.database_manager().unit_of_work() as db:
            snapshot = self._snapshot()
            canonical = read_performance_inputs(
                source.observation_reader(),
                db,
                snapshot,
                activity_reader=source.activity_row_reader(),
            )
        return snapshot, canonical

    def detail(
        self,
        activity_id: Any,
        *,
        garmin_snapshot: dict[str, Any],
        profile: dict[str, Any],
        today: date,
    ) -> dict[str, Any]:
        normalized_id = str(activity_id or "").strip()
        if not normalized_id or len(normalized_id) > 200:
            raise AppError(
                400,
                "Die Aktivität konnte nicht eindeutig zugeordnet werden.",
                reason="invalid_activity_request",
            )
        normalized_id = str(self._references.resolve(normalized_id))
        snapshot, canonical = self._performance_inputs()
        activity = _raw_activity(
            snapshot,
            normalized_id,
            None if canonical is None else canonical.activity_rows,
        )
        cached = self._detail_store.get(normalized_id) if self._detail_store else None
        stale = bool(
            cached
            and cached.get("summary_sha256")
            and cached["summary_sha256"] != summary_fingerprint(activity)
        )
        if cached:
            activity = {**activity, **cached["activity"]}
        feedback = next(
            (
                item
                for item in self._feedback_service.list(500)
                if item.get("activity_id") == normalized_id
            ),
            None,
        )
        performance = current_performance_context(
            snapshot,
            garmin_snapshot,
            profile,
            today,
            **performance_options(canonical),
        )
        equipment = _activity_equipment(self._read_equipment(), normalized_id)
        local_ids = self._references.local_ids([normalized_id])
        return {
            "ok": True,
            "snapshot_synced_at": snapshot.get("synced_at"),
            "activity": detail_projection.detailed_activity(activity),
            "activity_validation": activity_performance_validation(
                [activity],
                performance.get("metrics", {}),
                performance.get("comparisons", {}),
            ),
            "activity_feedback": feedback,
            "equipment": equipment,
            "session_analysis": cached.get("session_analysis", {})
            if cached and not stale
            else {},
            "activity_id": normalized_id,
            "local_activity_id": local_ids.get(normalized_id),
            "detail_data": _detail_metadata(cached, stale, activity),
            "data_scope": "bounded sanitized detail projection of exactly one Intervals.icu activity",
        }


def _raw_activity(
    snapshot: dict,
    normalized_id: str,
    activity_rows: Sequence[Any] | None = None,
) -> dict:
    """Find one raw activity row, in the canonical rows when they were read."""
    raw_provider_data = snapshot.get("raw_provider_data")
    raw_activities = (
        activity_rows
        if activity_rows is not None
        else raw_provider_data.get("activities")
        if isinstance(raw_provider_data, dict)
        else None
    )
    activity = (
        next(
            (
                item
                for item in raw_activities
                if isinstance(item, dict)
                and str(_first_present(item, ("id", "activityId", "external_id")) or "")
                == normalized_id
            ),
            None,
        )
        if isinstance(raw_activities, list | tuple)
        else None
    )
    if activity is None:
        raise AppError(
            404,
            "Die vollständigen Rohdaten dieser Aktivität sind im lokalen Intervals.icu-Snapshot nicht vorhanden.",
            reason="activity_details_not_found",
        )

    return activity


def _detail_metadata(
    cached: dict | None, stale: bool, activity: dict
) -> dict[str, Any]:
    return {
        "source": provider_label(ProviderId.INTERVALS, SourceView.ACTIVITY_DETAIL),
        "observed_at": cached.get("observed_at") if cached else None,
        "full_resolution": bool(cached and cached.get("full_resolution")),
        "stale": stale,
        "content_sha256": cached.get("content_sha256") if cached else None,
        "coverage": cached.get("coverage", {}) if cached else {},
        "available_streams": cached.get("available_streams", []) if cached else [],
        "display_sampled": bool(
            cached
            and any(
                len(series) > detail_projection.COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS
                for series in activity.get("streams", {}).values()
            )
        ),
    }


def _activity_equipment(equipment: dict, activity_id: str) -> list[dict]:
    assignment = next(
        (
            row
            for row in equipment.get("assignments", [])
            if row["activity_id"] == activity_id
        ),
        None,
    )
    equipment_ids = {assignment["equipment_id"]} if assignment else set()
    return [
        row
        for row in equipment.get("items", [])
        if row["id"] in equipment_ids or row.get("parent_id") in equipment_ids
    ]
