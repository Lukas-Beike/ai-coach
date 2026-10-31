from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any, Protocol, runtime_checkable

from backend.canonical.activity_summary import ActivitySummary
from backend.canonical.coverage import MetricWindow, ProviderCoverage
from backend.canonical.domain_records import (
    CategoricalObservation,
    PowerCurve,
    SleepPeriod,
)
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.vocabulary import (
    CategoricalDomain,
    MetricKind,
    ProviderId,
    Sport,
)


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


# One canonical session: its local id and its active records of every provider.
type SessionRecords = tuple[str, tuple[ActivityRecord, ...]]


class ActivitySessionReader(Protocol):
    """Reads canonical activity sessions with all their active records.

    Bounds are as in ``ActivityReader``. Deleted sessions are never returned; a
    merged duplicate's records are listed under the session it was merged into.
    ``newest`` lets a source skip days older than at least that many newest
    sessions; it never drops one of them.
    """

    def activity_sessions(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        newest: int | None = None,
    ) -> tuple[SessionRecords, ...]: ...


class ActivitySummaryReader(Protocol):
    """Reads provider-neutral activity summaries, one per canonical session.

    Newest first. Bounds are as in ``ActivityReader``; ``limit`` keeps only the
    newest summaries. See ``backend.activities.activity_summary``.
    """

    def activity_summaries(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[ActivitySummary, ...]: ...


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


class ActivityRowAndSummaryReader(ActivityRowReader, ActivitySummaryReader, Protocol):
    """Raw activity rows for provider-side reads and summaries for consumers."""


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


@runtime_checkable
class SleepPeriodReader(Protocol):
    """Reads canonical sleep periods by inclusive wake date, oldest first.

    Only a source that stores sleep periods implements it; a reader without it
    means the periods are not available from the serving source.
    """

    def sleep_periods(
        self, db: Any, *, start: date | None = None, end: date | None = None
    ) -> tuple[SleepPeriod, ...]: ...


@runtime_checkable
class PowerCurveReader(Protocol):
    """Reads the stored power curve: each provider's latest fetch and best efforts.

    Fetches are ordered by provider and source record, points by provider and
    duration. Only a source that stores the power curve implements it; a reader
    without it means no power curve is available from the serving source.
    """

    def power_curve(self, db: Any) -> PowerCurve: ...


class CategoricalObservationReader(Protocol):
    """Reads canonical provider status codes of one domain by inclusive day.

    Oldest first. Only a source that stores them implements it.
    """

    def categorical_observations(
        self,
        db: Any,
        domain: CategoricalDomain,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[CategoricalObservation, ...]: ...


@runtime_checkable
class ActivityMaxHrReader(Protocol):
    """Reads each sport's highest stored activity max heart rate of one provider.

    Each entry is the sport, its highest max heart rate within ``low``..``high``
    bpm, and the newest athlete-local start day with that value. Only active
    records of sessions that are not deleted count.
    """

    def activity_max_hr(
        self, db: Any, provider: ProviderId, *, low: float, high: float
    ) -> tuple[tuple[Sport, float, date], ...]: ...


class CanonicalReader(
    ActivityReader,
    ActivityMaxHrReader,
    ActivityRowReader,
    ActivitySessionReader,
    ObservationReader,
    Protocol,
):
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


class CanonicalReadStatus(CanonicalTableServing, Protocol):
    """Reports the read state a consumer marks: pending, or an activity gap.

    ``activities_need_refresh`` is True while a compact activity row of the stored
    Intervals.icu snapshot has no raw counterpart; such rows never reach the tables.
    """

    def activities_need_refresh(self, db: Any) -> bool: ...


ProviderOperation = Callable[[], AbstractContextManager[None]]
