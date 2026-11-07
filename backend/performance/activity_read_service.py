"""Completed-activity analysis combining activity reads and performance context."""

import functools
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_reference import ActivityReferenceResolver
from backend.activities.activity_summary import ActivitySummary
from backend.activities.detail_contract import measured_order
from backend.activities.detail_store import ActivityDetailStore
from backend.activities.read_service import ActivityReadService, ActivitySummarySource
from backend.activities.zone_settings import ZoneSettings
from backend.athlete.profile import timezone_name
from backend.canonical.local_time import local_date
from backend.canonical.records import ActivityRecord
from backend.errors import AppError
from backend.performance.canonical_current import read_zone_thresholds
from backend.performance.canonical_detail import (
    CanonicalDetailReader,
    RefreshableProviders,
    SessionRecordReader,
)
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    read_performance_inputs,
    resolve_reader,
    with_read_status,
)
from backend.performance.context import current_performance_context
from backend.performance.current_thresholds import ZoneConfigurationSource
from backend.performance.detail_envelope import (
    DetailEnvelopeReader,
    feedback_session_load,
)
from backend.performance.freshness import GarminSyncStatus


class ActivityAnalysisReadService(ActivityReadService):
    def __init__(
        self,
        database_manager: Any,
        summaries: ActivitySummarySource,
        feedback_service: Any,
        detail_store: ActivityDetailStore | None = None,
        *,
        read_equipment: Callable[[str], dict[str, Any]] = lambda _: {},
        references: ActivityReferenceResolver | None = None,
        canonical: CanonicalPerformanceSource,
        session_records: SessionRecordReader | None = None,
        refreshable: RefreshableProviders = frozenset,
    ) -> None:
        super().__init__(
            database_manager,
            summaries,
            feedback_service,
            detail_store,
            read_equipment=read_equipment,
            references=references,
            coverage=canonical.coverage,
        )
        self._canonical = canonical
        self._session_records = session_records
        self._refreshable = refreshable

    def _zone_settings_reader(
        self, profile: Mapping[str, Any]
    ) -> Callable[[Any, ActivityRecord], ZoneSettings]:
        return _session_zone_settings(
            self._canonical, ZoneInfo(timezone_name(profile.get("timezone")))
        )

    def _performance_inputs(
        self, as_of: date, activity_id: str | None = None
    ) -> tuple[
        CanonicalPerformanceInputs | None,
        Sequence[ActivitySummary] | None,
    ]:
        """Read the performance inputs and the activity summaries in one read snapshot.

        The performance inputs cover only the recent year, so an older activity
        is looked up in the full history of the same read snapshot.
        """
        source = self._canonical
        with source.database_manager().read_snapshot() as db:
            reader = source.activity_summary_reader()
            canonical = with_read_status(
                source,
                db,
                read_performance_inputs(
                    source.observation_reader(),
                    db,
                    activity_reader=reader,
                    as_of=as_of,
                    include_local_load=True,
                    preferences=source.preferences_in(db),
                ),
            )
            summaries = None if canonical is None else canonical.activities
            if reader is not None and (
                summaries is None
                or (
                    activity_id is not None
                    and _find_summary(summaries, activity_id) is None
                )
            ):
                summaries = tuple(reader.activity_summaries(db))
        return canonical, summaries

    def summaries_between(self, start: date, end: date) -> list[ActivitySummary] | None:
        """Canonical activity summaries from ``start`` to ``end``; ``None`` if unreadable."""
        source = self._canonical
        reader = source.activity_summary_reader()
        if reader is None:
            return None
        with source.database_manager().read_snapshot() as db:
            return list(reader.activity_summaries(db, start=start, end=end))

    def summaries_on_days(
        self, days: Sequence[date]
    ) -> dict[date, list[ActivitySummary]]:
        """Canonical activity summaries of each local day, read in one snapshot."""
        reader = self._canonical.activity_summary_reader()
        if reader is None:
            return {}
        with self._canonical.database_manager().read_snapshot() as db:
            return {
                day: list(reader.activity_summaries(db, start=day, end=day))
                for day in days
            }

    def session_rpe_load(self, activity_id: Any, today: date) -> dict[str, Any] | None:
        """The session-RPE load the detail document serves for one activity."""
        normalized_id = str(activity_id or "").strip()
        if not normalized_id or len(normalized_id) > 200:
            return None
        _canonical, summaries = self._performance_inputs(today, normalized_id)
        reference = str(self._references.resolve_reference(normalized_id).activity_id)
        return feedback_session_load(
            self._feedback_service,
            [reference, normalized_id],
            _find_summary(summaries, normalized_id),
        )

    def detail(
        self,
        activity_id: Any,
        *,
        garmin_status: GarminSyncStatus,
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
        if self._session_records is None:
            raise RuntimeError("activity detail reads need the session records")
        inputs: dict[str, Any] = {}

        def load_inputs(activity_id: str) -> Sequence[ActivitySummary] | None:
            # Recent canonical summaries first, then the full local history.
            canonical, summaries = self._performance_inputs(today, activity_id)
            inputs.update(canonical=canonical)
            return summaries

        summary_reader = self._canonical.activity_summary_reader()

        @functools.cache
        def requested_summary() -> ActivitySummary | None:
            return _find_summary(load_inputs(normalized_id), normalized_id)

        def performance() -> Mapping[str, Any]:
            if not inputs:
                canonical, _rows = self._performance_inputs(today)
                inputs.update(canonical=canonical)
            return current_performance_context(
                garmin_status,
                profile,
                today,
                canonical=inputs["canonical"] or EMPTY_PERFORMANCE_INPUTS,
            )

        reader = CanonicalDetailReader(
            self._session_records,
            refreshable=self._refreshable,
            fingerprints=summary_reader,
            envelope=DetailEnvelopeReader(
                feedback_service=self._feedback_service,
                read_equipment=self._read_equipment,
                references=self._references,
                performance=performance,
                summary=requested_summary,
            ),
            zone=ZoneInfo(timezone_name(profile.get("timezone"))),
            zone_settings=self._zone_settings_reader(profile),
        )
        with self._database_manager.read_snapshot() as db:
            document = reader.read(db, normalized_id)
            if document is None:
                raise AppError(
                    404,
                    "Diese Aktivität ist lokal nicht vorhanden.",
                    reason="activity_details_not_found",
                )
            records = self._session_records(db, document["session"]["activity_id"])
        _add_purpose(document["session"], requested_summary())
        return {"ok": True, **document, "data_scope": _data_scope(document, records)}


def _add_purpose(session: dict[str, Any], summary: ActivitySummary | None) -> None:
    """Copy the session's purpose and competition link from its summary."""
    if summary is None:
        return
    if "purpose" in summary:
        session["purpose"] = summary["purpose"]
    if "competition_id" in summary:
        session["competition_id"] = summary["competition_id"]
    source = summary.get("sources", {}).get("purpose")
    if source:
        session["purpose_source"] = source


def _session_zone_settings(
    source: CanonicalPerformanceSource, zone: ZoneInfo
) -> Callable[[Any, ActivityRecord], ZoneSettings]:
    """The zones in effect for a session's sport, environment and local day.

    Local configurations first, then provider configurations, then the plan-zone
    thresholds of that day with the default limits, as planned units use them.
    """

    def read(db: Any, record: ActivityRecord) -> ZoneSettings:
        day = local_date(record.started_at, zone)
        reader = resolve_reader(source.observation_reader(), db)
        thresholds = read_zone_thresholds(
            reader, db, as_of=day, preferences=source.preferences_in(db)
        )
        configurations = (
            reader.zone_configurations(db)
            if isinstance(reader, ZoneConfigurationSource)
            else ()
        )
        # The zones of planning's resolve_thresholds, without importing planning.
        return ZoneSettings.from_configurations(
            configurations,
            record.sport,
            record.environment,
            day,
            fallback=ZoneSettings.from_thresholds(thresholds, record.sport),
        )

    return read


def _find_summary(
    summaries: Sequence[ActivitySummary] | None, activity_id: str
) -> ActivitySummary | None:
    """Return the summary whose session id or any provider id is ``activity_id``."""
    return next(
        (
            summary
            for summary in summaries or ()
            if summary.get("id") == activity_id
            or activity_id in (summary.get("record_ids") or {}).values()
        ),
        None,
    )


def _data_scope(document: Mapping[str, Any], records: Sequence[ActivityRecord]) -> str:
    """Name the document's providers and the recorder of its primary record."""
    labels = ", ".join(
        str(entry["label"]) for entry in document["detail_data"]["providers"]
    )
    recorder = measured_order(records)[0].provenance.recorded_by.value
    return (
        "bounded sanitized activity_detail.v1 document of exactly one local "
        f"session; providers: {labels}; recorded by: {recorder}"
    )
