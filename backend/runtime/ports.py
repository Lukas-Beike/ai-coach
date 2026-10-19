from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any, Protocol, runtime_checkable

from backend.canonical.coverage import MetricWindow, ProviderCoverage
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import MetricKind, Sport


class ProviderSnapshotReader(Protocol):
    def latest_snapshot(self, db: Any) -> dict[str, Any] | None: ...


class ProviderStateReader(Protocol):
    def summary(self, provider: str) -> dict[str, Any]: ...


class AudioTranscriber(Protocol):
    def transcribe(self, audio: bytes, content_type: str) -> dict[str, str]: ...


class ActivityReader(Protocol):
    """Reads canonical activity records.

    ``start`` and ``end`` are inclusive bounds on the athlete-local date of each
    activity's start. Results contain validated canonical records only; mapping
    issues are not returned here and are exposed only as counts through
    ``ProviderCoverageReader``.
    """

    def activities(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[ActivityRecord, ...]: ...


class ActivityRowReader(Protocol):
    """Reads the raw Intervals.icu activity payloads behind the canonical records.

    Rows are provider dictionaries (device source, ``icu_*`` fields, laps, gear),
    untrusted data, before any de-duplication. ``start`` and ``end`` are inclusive
    bounds on the athlete-local date of each activity, as in ``ActivityReader``.
    Deleted or tombstoned activities are never returned. The legacy source keeps
    the snapshot order (newest first); the table source orders newest first by
    activity start, then id. ``limit`` keeps only the newest rows; the table
    source applies it before reading the payloads.
    """

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]: ...


class ObservationReader(Protocol):
    """Reads canonical observations of one metric kind.

    ``start`` and ``end`` are inclusive bounds on each observation's
    ``observed_on`` date. ``sport`` restricts results to one sport when given.
    Results contain validated canonical observations only; mapping issues are
    exposed only as counts through ``ProviderCoverageReader``.
    """

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]: ...


class CanonicalReader(ActivityReader, ActivityRowReader, ObservationReader, Protocol):
    """The reads a canonical source serves: activities, raw rows and observations.

    Every source also reports its per-metric windows, so the selector can delegate
    ``metric_windows`` to whichever source serves the current read.
    """

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]: ...


@runtime_checkable
class ObservationSourceSelector(ObservationReader, Protocol):
    """An observation reader that chooses its serving source for every read.

    ``reader_for`` makes that choice once and returns the chosen reader, so a
    caller with several reads in one unit of work does not repeat it per read.
    """

    def reader_for(self, db: Any) -> ObservationReader: ...


class ProviderCoverageReader(Protocol):
    """Reports per-provider coverage counts, including mapping issue counts only."""

    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]: ...

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        """Return the count and newest observed day of each provider metric.

        Counts and days only, never values. A source that keeps no per-metric data
        returns an empty tuple.
        """
        ...


class CanonicalTableServing(Protocol):
    """Reports whether reads are currently served from the canonical tables.

    True once the backfill has completed at least once, also while a mapper or
    time-zone change is re-projected. Callers read table-only data only while this
    holds.
    """

    def serves_tables(self, db: Any) -> bool: ...


ProviderOperation = Callable[[], AbstractContextManager[None]]
