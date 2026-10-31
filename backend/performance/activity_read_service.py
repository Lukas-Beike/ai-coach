"""Completed-activity analysis combining activity reads and performance context."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_reference import ActivityReferenceResolver
from backend.activities.activity_summary import ActivitySummary
from backend.activities.detail_contract import measured_order
from backend.activities.detail_store import ActivityDetailStore
from backend.activities.read_service import ActivityReadService
from backend.athlete.profile import timezone_name
from backend.canonical.records import ActivityRecord
from backend.errors import AppError
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
)
from backend.performance.context import current_performance_context
from backend.performance.detail_envelope import DetailEnvelopeReader
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
        canonical: CanonicalPerformanceSource,
        summary_rows: ActivityRowReader | None = None,
        session_records: SessionRecordReader | None = None,
        refreshable: RefreshableProviders = frozenset,
    ) -> None:
        super().__init__(
            database_manager,
            snapshot_reader,
            row_reader,
            feedback_service,
            detail_store,
            read_equipment=read_equipment,
            references=references,
            summary_rows=summary_rows,
            coverage=canonical.coverage,
        )
        self._canonical = canonical
        self._session_records = session_records
        self._refreshable = refreshable

    def _performance_inputs(
        self, as_of: date, activity_id: str | None = None
    ) -> tuple[
        dict[str, Any],
        CanonicalPerformanceInputs | None,
        Sequence[ActivitySummary] | None,
    ]:
        """Read the snapshot, CTL and ATL, and the activity summaries in one read snapshot.

        The performance inputs cover only the recent year, so an older activity
        is looked up in the full history of the same read snapshot.
        """
        source = self._canonical
        with source.database_manager().read_snapshot() as db:
            snapshot = self._snapshot()
            reader = source.activity_summary_reader()
            canonical = read_performance_inputs(
                source.observation_reader(),
                db,
                activity_reader=reader,
                as_of=as_of,
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
        return snapshot, canonical, summaries

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
        if self._session_records is None:
            raise RuntimeError("activity detail reads need the session records")
        inputs: dict[str, Any] = {}

        def load_inputs(activity_id: str) -> Sequence[ActivitySummary] | None:
            # Recent canonical summaries first, then the full local history.
            snapshot, canonical, summaries = self._performance_inputs(
                today, activity_id
            )
            inputs.update(snapshot=snapshot, canonical=canonical)
            return summaries

        def summary_row(db: Any, provider_activity_id: str) -> dict | None:
            # The stored Intervals.icu row the detail document fingerprints.
            if self._summary_rows is None:
                return None
            return _find_row(self._summary_rows.activity_rows(db), provider_activity_id)

        def requested_summary() -> ActivitySummary | None:
            return _find_summary(load_inputs(normalized_id), normalized_id)

        def performance() -> Mapping[str, Any]:
            if not inputs:
                snapshot, canonical, _rows = self._performance_inputs(today)
                inputs.update(snapshot=snapshot, canonical=canonical)
            return current_performance_context(
                inputs["snapshot"],
                garmin_snapshot,
                profile,
                today,
                canonical=inputs["canonical"] or EMPTY_PERFORMANCE_INPUTS,
            )

        reader = CanonicalDetailReader(
            self._session_records,
            refreshable=self._refreshable,
            summary_row=summary_row,
            failures=None
            if self._detail_store is None
            else self._detail_store.failures,
            envelope=DetailEnvelopeReader(
                feedback_service=self._feedback_service,
                read_equipment=self._read_equipment,
                references=self._references,
                performance=performance,
                summary=requested_summary,
            ),
            zone=ZoneInfo(timezone_name(profile.get("timezone"))),
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
        return {"ok": True, **document, "data_scope": _data_scope(document, records)}


def _find_row(raw_rows: Any, provider_activity_id: str) -> dict | None:
    if not isinstance(raw_rows, list | tuple):
        return None
    return next(
        (
            item
            for item in raw_rows
            if isinstance(item, dict)
            and str(item.get("id") or "") == provider_activity_id
        ),
        None,
    )


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
