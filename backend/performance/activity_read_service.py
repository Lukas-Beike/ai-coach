"""Completed-activity analysis combining activity reads and performance context."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from backend.activities.activity_reference import ActivityReferenceResolver
from backend.activities.detail_contract import measured_order
from backend.activities.detail_store import ActivityDetailStore
from backend.activities.read_service import ActivityReadService, _first_present
from backend.canonical.records import ActivityRecord
from backend.errors import AppError
from backend.performance.canonical_detail import (
    CanonicalDetailReader,
    RefreshableProviders,
    SessionRecordReader,
)
from backend.performance.canonical_inputs import (
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    performance_options,
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
        canonical: CanonicalPerformanceSource | None = None,
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
        )
        self._canonical = canonical
        self._session_records = session_records
        self._refreshable = refreshable

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
        if self._session_records is None:
            raise RuntimeError("activity detail reads need the session records")
        inputs: dict[str, Any] = {}

        def summary_row(_db: Any, provider_activity_id: str) -> dict | None:
            # Snapshot first, then the full local history, like the summary read.
            snapshot, canonical, rows = self._performance_inputs(
                today, provider_activity_id
            )
            inputs.update(snapshot=snapshot, canonical=canonical)
            return _find_activity(
                _snapshot_activities(snapshot) if rows is None else rows,
                provider_activity_id,
            )

        def performance() -> Mapping[str, Any]:
            if not inputs:
                snapshot, canonical, _rows = self._performance_inputs(today)
                inputs.update(snapshot=snapshot, canonical=canonical)
            return current_performance_context(
                inputs["snapshot"],
                garmin_snapshot,
                profile,
                today,
                **performance_options(inputs["canonical"]),
            )

        reader = CanonicalDetailReader(
            self._session_records,
            refreshable=self._refreshable,
            summary_row=summary_row,
            failures=None if self._detail_store is None else self._detail_store.failures,
            envelope=DetailEnvelopeReader(
                feedback_service=self._feedback_service,
                read_equipment=self._read_equipment,
                references=self._references,
                performance=performance,
            ),
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


def _snapshot_activities(snapshot: dict) -> Any:
    raw_provider_data = snapshot.get("raw_provider_data")
    if isinstance(raw_provider_data, dict):
        return raw_provider_data.get("activities")
    return None


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
