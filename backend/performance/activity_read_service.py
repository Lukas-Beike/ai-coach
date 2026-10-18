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
from backend.providers.intervals_performance_fields import (
    HEART_RATE_ZONE_TIMES,
    ZONE_TIMES,
)
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
        read_equipment: Callable[[str], dict[str, Any]] = lambda _: {},
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
        self, as_of: date, activity_id: str | None = None
    ) -> tuple[dict[str, Any], CanonicalPerformanceInputs | None, Sequence[Any] | None]:
        """Read the snapshot, CTL and ATL, and the activity's rows in one read snapshot.

        The performance inputs cover only the recent year, so an older activity
        is looked up in the full history of the same read snapshot.
        """
        source = self._canonical
        if source is None:
            return self._snapshot(), None, None
        with source.database_manager().read_snapshot() as db:
            snapshot = self._snapshot()
            reader = source.activity_row_reader()
            canonical = read_performance_inputs(
                source.observation_reader(),
                db,
                snapshot,
                activity_reader=reader,
                as_of=as_of,
            )
            rows = None if canonical is None else canonical.activity_rows
            if (
                rows is not None
                and reader is not None
                and activity_id is not None
                and _find_activity(rows, activity_id) is None
            ):
                rows = tuple(reader.activity_rows(db))
        return snapshot, canonical, rows

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
        snapshot, canonical, rows = self._performance_inputs(today, normalized_id)
        activity = _raw_activity(snapshot, normalized_id, rows)
        cached = self._detail_store.get(normalized_id) if self._detail_store else None
        stale = bool(
            cached
            and cached.get("summary_sha256")
            and cached["summary_sha256"] != summary_fingerprint(activity)
        )
        if cached:
            # Zone times are outside the fingerprint, so the live row stays authoritative.
            live_zones = {
                key: activity[key]
                for key in (HEART_RATE_ZONE_TIMES, ZONE_TIMES)
                if key in activity
            }
            activity = {**activity, **cached["activity"], **live_zones}
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
        equipment = _activity_equipment(
            self._read_equipment(normalized_id), normalized_id
        )
        local_ids = self._references.local_ids([normalized_id])
        failure = (
            self._detail_store.failures([normalized_id]).get(normalized_id)
            if self._detail_store
            else None
        )
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
            "detail_data": _detail_metadata(cached, stale, activity, failure),
            "data_scope": "bounded sanitized detail projection of exactly one Intervals.icu activity",
        }


def _find_activity(raw_activities: Any, normalized_id: str) -> dict | None:
    if not isinstance(raw_activities, list | tuple):
        return None
    return next(
        (
            item
            for item in raw_activities
            if isinstance(item, dict)
            and str(_first_present(item, ("id", "activityId", "external_id")) or "")
            == normalized_id
        ),
        None,
    )


def _raw_activity(
    snapshot: dict,
    normalized_id: str,
    activity_rows: Sequence[Any] | None = None,
) -> dict:
    """Find one raw activity row, in the canonical rows when they were read."""
    raw_activities: Any = activity_rows
    if raw_activities is None:
        raw_provider_data = snapshot.get("raw_provider_data")
        if isinstance(raw_provider_data, dict):
            raw_activities = raw_provider_data.get("activities")
    activity = _find_activity(raw_activities, normalized_id)
    if activity is None:
        raise AppError(
            404,
            "Die vollständigen Rohdaten dieser Aktivität sind im lokalen Intervals.icu-Snapshot nicht vorhanden.",
            reason="activity_details_not_found",
        )

    return activity


def _detail_metadata(
    cached: dict | None, stale: bool, activity: dict, failure: dict | None = None
) -> dict[str, Any]:
    return {
        "load_error": {
            "message": failure.get("message"),
            "observed_at": failure.get("observed_at"),
        }
        if failure
        else None,
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
    # Garmin can link one activity to several main items.
    equipment_ids = {
        row["equipment_id"]
        for row in equipment.get("assignments", [])
        if row["activity_id"] == activity_id and row["equipment_id"]
    }
    return [
        row
        for row in equipment.get("items", [])
        if row["id"] in equipment_ids or row.get("parent_id") in equipment_ids
    ]
