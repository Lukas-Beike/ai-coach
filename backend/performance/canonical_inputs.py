"""Canonical performance inputs read through the observation port.

CTL and ATL: the reader decides which source serves the values. Each value is
selected by ``select_current`` pinned to the snapshot's latest wellness day, which
is the row the legacy load context reads. The read window spans the snapshot's own
wellness rows and never extends past its latest day, so older or newer canonical
history cannot change the current load.

Current sport thresholds and VO2max come from the same snapshot's sync, see
``backend.performance.canonical_current``.

A snapshot without a usable wellness day yields no inputs, and the caller keeps
the legacy values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from backend.canonical.vocabulary import MetricKind
from backend.performance.canonical_current import (
    CanonicalCurrentInputs,
    read_current_inputs,
)
from backend.performance.source_policy import select_current
from backend.runtime.ports import ObservationReader, ObservationSourceSelector


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceInputs:
    """CTL and ATL for the wellness day that the legacy load context reads.

    ``current`` holds the sport thresholds and VO2max of the same snapshot, or None
    when they were not read.
    """

    wellness_day: date
    ctl: float | None
    atl: float | None
    current: CanonicalCurrentInputs | None = None


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceSource:
    """Lazy accessors a consumer uses to read canonical load inputs.

    Both callables are resolved at read time, as the other assemblies do, so the
    composition root can pass ``lambda: ...`` accessors.
    """

    database_manager: Callable[[], Any]
    observation_reader: Callable[[], ObservationReader]


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
            source.observation_reader(), db, snapshot
        )


def inputs_for_snapshot(
    source: CanonicalPerformanceSource | None, db: Any, snapshot: Any
) -> CanonicalPerformanceInputs | None:
    """Read canonical load inputs inside the caller's snapshot transaction."""
    if source is None:
        return None
    return read_performance_inputs(source.observation_reader(), db, snapshot)


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
    if isinstance(reader, ObservationSourceSelector):
        reader = reader.reader_for(db)
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


def read_performance_inputs(
    reader: ObservationReader,
    db: Any,
    snapshot: Mapping[str, Any] | None,
) -> CanonicalPerformanceInputs | None:
    """Read CTL and ATL for a stored snapshot, or return None to keep legacy values.

    None means the snapshot has no wellness rows, or its latest row (the row the
    legacy reader picks) has an id that is not a strict ``YYYY-MM-DD`` date.
    """
    rows = _wellness_rows(snapshot)
    if not rows:
        return None
    latest_day = _row_day(max(rows, key=_row_id_text))
    if latest_day is None:
        return None
    days = [day for day in map(_row_day, rows) if day is not None]
    loaded = load_performance_inputs(
        reader,
        db,
        latest_wellness_day=latest_day,
        start=min(days),
        end=latest_day,
    )
    return replace(
        loaded,
        current=read_current_inputs(
            reader, db, snapshot, latest_wellness_day=latest_day
        ),
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


def _wellness_rows(snapshot: Mapping[str, Any] | None) -> Sequence[Mapping[str, Any]]:
    if not snapshot:
        return ()
    raw = snapshot.get("recent_wellness")
    if not isinstance(raw, list):
        return ()
    return [row for row in raw if isinstance(row, dict)]


def _row_id_text(row: Mapping[str, Any]) -> str:
    """Order rows as the legacy latest-row selection does."""
    return str(row.get("id") or "")


def _row_day(row: Mapping[str, Any]) -> date | None:
    """Return the row's day only for a strict ``YYYY-MM-DD`` id."""
    text = row.get("id")
    if not isinstance(text, str):
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return day if day.isoformat() == text else None
