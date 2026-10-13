"""Canonical performance inputs read through the observation and activity-row ports.

Activities and wellness rows: the reader decides which source serves them, see
``backend.performance.canonical_sections``. The activity rows are the raw rows of
``ActivityRowReader`` and their compact projection; the wellness rows are rebuilt
from the Intervals.icu wellness-day observations and carry the snapshot's
non-canonical wellness fields. The latest wellness day is the latest day of any
wellness row or observation.

CTL and ATL: each value is selected by ``select_current`` pinned to the latest
wellness day, which is the row the legacy load context reads. The read window spans
the wellness rows and never extends past the latest day, so older or newer
canonical history cannot change the current load.

Current sport thresholds and VO2max come from the latest Intervals sync, see
``backend.performance.canonical_current``. The current sleep score, resting HR and
readiness come from ``backend.performance.canonical_recovery``. The 7-day resting HR
and readiness averages come from ``backend.performance.canonical_recovery_averages``
and replace the legacy average only when both cover the same days with equal values.

Without a usable wellness day the inputs still carry the activities and the
wellness rows, and no load, threshold or recovery value. Without a canonical
activity reader and without wellness rows there are no inputs, and the caller keeps
the legacy values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.performance import canonical_sections
from backend.performance.canonical_current import (
    CanonicalCurrentInputs,
    read_current_inputs,
)
from backend.performance.canonical_personal_recovery import (
    CanonicalPersonalRecoveryInputs,
    read_personal_recovery_inputs,
)
from backend.performance.canonical_recovery import (
    CanonicalRecoveryInputs,
    read_recovery_inputs,
)
from backend.performance.canonical_recovery_averages import (
    CanonicalRecoveryAverageInputs,
    read_recovery_average_inputs,
)
from backend.performance.source_policy import select_current
from backend.runtime.ports import (
    ActivityRowReader,
    CanonicalTableServing,
    ObservationReader,
    ObservationSourceSelector,
)


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceInputs:
    """CTL and ATL for the wellness day that the legacy load context reads.

    ``wellness_day`` is None when there is no usable wellness day. ``current`` holds
    the sport thresholds and VO2max of the latest sync, or None when they were not
    read. ``personal_recovery`` holds the daily resting HR of the personal recovery
    baselines, or None when it was not read.

    ``activity_rows`` are the raw activity rows (newest first, before
    de-duplication) and ``activities`` their compact projection, or None when no
    activity reader was configured. ``wellness_rows`` are the wellness rows of the
    performance context and ``history_wellness_rows`` those of the history views,
    which also keep the raw snapshot rows as carrier. Both are None when the inputs
    were built without wellness rows.
    """

    wellness_day: date | None
    ctl: float | None
    atl: float | None
    current: CanonicalCurrentInputs | None = None
    recovery: CanonicalRecoveryInputs | None = None
    personal_recovery: CanonicalPersonalRecoveryInputs | None = None
    recovery_averages: CanonicalRecoveryAverageInputs | None = None
    activity_rows: tuple[dict[str, Any], ...] | None = None
    activities: tuple[dict[str, Any], ...] | None = None
    wellness_rows: tuple[dict[str, Any], ...] | None = None
    history_wellness_rows: tuple[dict[str, Any], ...] | None = None


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceSource:
    """Lazy accessors a consumer uses to read canonical load inputs.

    Both callables are resolved at read time, as the other assemblies do, so the
    composition root can pass ``lambda: ...`` accessors. ``serving`` is optional;
    when it is None, consumers that gate table-only reads keep the legacy values.
    ``activity_rows`` is optional; without it the activities stay on the snapshot.
    """

    database_manager: Callable[[], Any]
    observation_reader: Callable[[], ObservationReader]
    serving: Callable[[], CanonicalTableServing] | None = None
    activity_rows: Callable[[], ActivityRowReader] | None = None

    def activity_row_reader(self) -> ActivityRowReader | None:
        """Return the configured raw activity row reader, if any."""
        return None if self.activity_rows is None else self.activity_rows()


def snapshot_with_inputs(
    source: CanonicalPerformanceSource | None,
    read_snapshot: Callable[[], Any],
) -> tuple[Any, CanonicalPerformanceInputs | None]:
    """Read a snapshot and its canonical load inputs in one unit of work.

    Without a canonical source the snapshot is read exactly as before.
    """
    if source is None:
        return read_snapshot(), None
    with source.database_manager().unit_of_work() as db:
        snapshot = read_snapshot()
        return snapshot, read_performance_inputs(
            source.observation_reader(),
            db,
            snapshot,
            activity_reader=source.activity_row_reader(),
        )


def activity_rows_for(
    source: CanonicalPerformanceSource | None,
) -> tuple[dict[str, Any], ...] | None:
    """Read the raw activity rows in their own unit of work.

    None without a source or an activity row reader, so the caller keeps reading
    the activities from its snapshot.
    """
    reader = None if source is None else source.activity_row_reader()
    if source is None or reader is None:
        return None
    with source.database_manager().unit_of_work() as db:
        return tuple(reader.activity_rows(db))


def inputs_for_snapshot(
    source: CanonicalPerformanceSource | None, db: Any, snapshot: Any
) -> CanonicalPerformanceInputs | None:
    """Read canonical load inputs inside the caller's snapshot transaction."""
    if source is None:
        return None
    return read_performance_inputs(
        source.observation_reader(),
        db,
        snapshot,
        activity_reader=source.activity_row_reader(),
    )


def resolve_reader(reader: ObservationReader, db: Any) -> ObservationReader:
    """Choose the serving source once for a unit of work when the reader selects."""
    if isinstance(reader, ObservationSourceSelector):
        return reader.reader_for(db)
    return reader


def load_performance_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    latest_wellness_day: date,
    start: date,
    end: date,
) -> CanonicalPerformanceInputs:
    """Read CTL and ATL once each, selected for ``latest_wellness_day``.

    A selecting reader chooses its source once, so both reads use the same source.
    """
    return _load_resolved(
        resolve_reader(reader, db),
        db,
        latest_wellness_day=latest_wellness_day,
        start=start,
        end=end,
    )


def _load_resolved(
    reader: ObservationReader,
    db: Any,
    *,
    latest_wellness_day: date,
    start: date,
    end: date,
) -> CanonicalPerformanceInputs:
    """Read CTL and ATL from an already-resolved reader."""
    return CanonicalPerformanceInputs(
        wellness_day=latest_wellness_day,
        ctl=_current_value(
            reader,
            db,
            MetricKind.CTL,
            latest_wellness_day=latest_wellness_day,
            start=start,
            end=end,
        ),
        atl=_current_value(
            reader,
            db,
            MetricKind.ATL,
            latest_wellness_day=latest_wellness_day,
            start=start,
            end=end,
        ),
    )


def performance_options(
    canonical: CanonicalPerformanceInputs | None,
) -> dict[str, CanonicalPerformanceInputs]:
    """Keyword arguments for ``current_performance_context``.

    Empty when there are no canonical inputs, so the legacy call shape is kept.
    """
    return {} if canonical is None else {"canonical": canonical}


class _ReadOnceReader:
    """Serve the reads of one snapshot unit from one unbounded read per kind.

    The wellness rows, the current metrics, the recovery inputs and the recovery
    averages all ask for overlapping observations, so each kind reaches the
    database once per call and the bounds are applied in memory.
    """

    def __init__(self, reader: ObservationReader) -> None:
        self._reader = reader
        self._rows: dict[MetricKind, tuple[Observation, ...]] = {}

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        if kind not in self._rows:
            self._rows[kind] = tuple(self._reader.observations(db, kind))
        return tuple(
            observation
            for observation in self._rows[kind]
            if (start is None or observation.observed_on >= start)
            and (end is None or observation.observed_on <= end)
            and (sport is None or observation.sport is sport)
        )


@dataclass(frozen=True, slots=True)
class _CarriedRows:
    """The activity and wellness rows every canonical performance input carries."""

    activity_rows: tuple[dict[str, Any], ...] | None
    activities: tuple[dict[str, Any], ...] | None
    wellness_rows: tuple[dict[str, Any], ...]
    history_wellness_rows: tuple[dict[str, Any], ...]

    def inputs(
        self,
        *,
        wellness_day: date | None,
        ctl: float | None,
        atl: float | None,
        current: CanonicalCurrentInputs | None = None,
        recovery: CanonicalRecoveryInputs | None = None,
        personal_recovery: CanonicalPersonalRecoveryInputs | None = None,
        recovery_averages: CanonicalRecoveryAverageInputs | None = None,
    ) -> CanonicalPerformanceInputs:
        return CanonicalPerformanceInputs(
            wellness_day=wellness_day,
            ctl=ctl,
            atl=atl,
            current=current,
            recovery=recovery,
            personal_recovery=personal_recovery,
            recovery_averages=recovery_averages,
            activity_rows=self.activity_rows,
            activities=self.activities,
            wellness_rows=self.wellness_rows,
            history_wellness_rows=self.history_wellness_rows,
        )


def read_performance_inputs(
    reader: ObservationReader,
    db: Any,
    snapshot: Mapping[str, Any] | None,
    *,
    activity_reader: ActivityRowReader | None = None,
) -> CanonicalPerformanceInputs | None:
    """Read the canonical activities, wellness rows and load inputs of a snapshot.

    The snapshot only carries the wellness fields that have no observation (see
    ``canonical_sections``); activities and wellness values come from the readers.
    None means there is no activity reader and no wellness row, so the caller keeps
    the legacy values. A latest row (the row the legacy reader picks) whose id is
    not a strict ``YYYY-MM-DD`` date yields inputs without a wellness day. A
    selecting reader chooses its source once for all reads.
    """
    reader = _ReadOnceReader(resolve_reader(reader, db))
    observed = canonical_sections.read_wellness_observations(reader, db)
    compact = _snapshot_rows(snapshot, "recent_wellness")
    rows = canonical_sections.wellness_rows(compact, observed)
    history = canonical_sections.wellness_rows(
        [*_raw_wellness_rows(snapshot), *compact], observed
    )
    activity_rows = (
        None if activity_reader is None else tuple(activity_reader.activity_rows(db))
    )
    if activity_rows is None and not rows:
        return None
    activities = (
        None
        if activity_rows is None
        else tuple(canonical_sections.compact_activity_rows(activity_rows))
    )
    carried = _CarriedRows(
        activity_rows=activity_rows,
        activities=activities,
        wellness_rows=tuple(rows),
        history_wellness_rows=tuple(history),
    )
    latest_day = (
        canonical_sections.row_day(max(rows, key=_row_id_text)) if rows else None
    )
    if latest_day is None:
        return carried.inputs(wellness_day=None, ctl=None, atl=None)
    start = min(day for day in map(canonical_sections.row_day, rows) if day is not None)
    loaded = _load_resolved(
        reader, db, latest_wellness_day=latest_day, start=start, end=latest_day
    )
    return carried.inputs(
        wellness_day=loaded.wellness_day,
        ctl=loaded.ctl,
        atl=loaded.atl,
        current=read_current_inputs(reader, db, latest_wellness_day=latest_day),
        recovery=read_recovery_inputs(
            reader, db, latest_wellness_day=latest_day, start=start
        ),
        personal_recovery=read_personal_recovery_inputs(
            reader, db, start=latest_day - timedelta(days=83)
        ),
        recovery_averages=read_recovery_average_inputs(reader, db, start=start),
    )


def _current_value(
    reader: ObservationReader,
    db: Any,
    kind: MetricKind,
    *,
    latest_wellness_day: date,
    start: date,
    end: date,
) -> float | None:
    observations = reader.observations(db, kind, start=start, end=end)
    observation = select_current(
        observations, kind, latest_wellness_day=latest_wellness_day
    )
    return None if observation is None else observation.value.value


def _snapshot_rows(
    snapshot: Mapping[str, Any] | None, key: str
) -> list[dict[str, Any]]:
    raw = snapshot.get(key) if snapshot else None
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _raw_wellness_rows(snapshot: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    raw = snapshot.get("raw_provider_data") if snapshot else None
    if not isinstance(raw, dict):
        return []
    return _snapshot_rows(raw, "wellness")


def _row_id_text(row: Mapping[str, Any]) -> str:
    """Order rows as the legacy latest-row selection does."""
    return str(row.get("id") or "")
