"""Read performance inputs through canonical observation and activity ports.

Wellness values come only from provider-neutral ``WellnessDay`` observations.
The current window covers 90 days ending on its latest day; history keeps every
stored day. Snapshot wellness sections do not affect these inputs. Activities
cover the year before ``as_of``, extended to the current window's first day.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final, cast

from backend.activities.sync_time import activities_synced_at
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.performance import canonical_sections, wellness_days
from backend.performance.canonical_current import (
    CanonicalCurrentInputs,
    read_current_inputs,
    read_wahoo_fallbacks,
)
from backend.performance.canonical_recovery import (
    CanonicalRecoveryInputs,
    read_recovery_inputs,
)
from backend.performance.daily_health import read_daily_health_by_date
from backend.performance.garmin_canonical import (
    GarminCanonicalMetrics,
    read_garmin_state,
)
from backend.performance.source_policy import select_current
from backend.performance.wellness_days import WellnessDay
from backend.runtime.ports import (
    ActivityReader,
    ActivityRowReader,
    CanonicalTableServing,
    ObservationReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
    SleepPeriodReader,
)


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceInputs:
    """CTL and ATL for the wellness day that the legacy load context reads.

    ``wellness_day`` is None when there is no usable wellness day. ``current`` holds
    the sport thresholds and VO2max of the latest sync, or None when they were not
    read. ``recovery`` holds the recovery observations of the current context and
    the personal baselines, or None when they were not read.

    ``activity_rows`` are raw activity rows and ``activities`` their compact
    projection. ``wellness_days`` is the current 90-day window;
    ``history_wellness_days`` keeps all stored days and their provenance.

    ``garmin`` holds the Garmin performance values and ``daily_health`` the daily
    totals of the last ``DAILY_HEALTH_DAYS`` days by ISO date; both are None when
    they were not read.

    ``form_by_day``, ``eftp_by_day`` and ``run_eftp_by_day`` are the
    Intervals.icu wellness-day form and sport-scoped eFTP series.
    ``ramp_rate`` is the latest wellness day's CTL minus the CTL of exactly seven
    days earlier, rounded to two decimals, or None when either day is missing.
    """

    wellness_day: date | None
    ctl: float | None
    atl: float | None
    current: CanonicalCurrentInputs | None = None
    recovery: CanonicalRecoveryInputs | None = None
    activity_rows: tuple[dict[str, Any], ...] | None = None
    activities: tuple[dict[str, Any], ...] | None = None
    wellness_days: tuple[WellnessDay, ...] | None = None
    history_wellness_days: tuple[WellnessDay, ...] | None = None
    garmin: GarminCanonicalMetrics | None = None
    daily_health: Mapping[str, Mapping[str, Any]] | None = None
    form_by_day: Mapping[date, float] | None = None
    eftp_by_day: Mapping[date, float] | None = None
    run_eftp_by_day: Mapping[date, float] | None = None
    ramp_rate: float | None = None


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceSource:
    """Lazy accessors a consumer uses to read canonical load inputs.

    Both callables are resolved at read time, as the other assemblies do, so the
    composition root can pass ``lambda: ...`` accessors. ``serving`` is optional;
    when it is None, consumers that gate table-only reads keep the legacy values.
    ``activity_rows`` is optional; without it a consumer reads no activity rows.
    ``coverage`` is optional; without it the activities' sync time is unknown.
    """

    database_manager: Callable[[], Any]
    observation_reader: Callable[[], ObservationReader]
    serving: Callable[[], CanonicalTableServing] | None = None
    activity_rows: Callable[[], ActivityRowReader] | None = None
    coverage: Callable[[], ProviderCoverageReader] | None = None

    def activity_row_reader(self) -> ActivityRowReader | None:
        """Return the configured raw activity row reader, if any."""
        return None if self.activity_rows is None else self.activity_rows()


# Activities older than this are not read for the performance inputs.
ACTIVITY_HISTORY_DAYS: Final = 365
# Daily totals of the days before ``as_of`` that the 7-day averages read.
DAILY_HEALTH_DAYS: Final = 7
# The ramp rate compares the CTL of the latest wellness day with this many days before.
RAMP_RATE_DAYS: Final = 7


def snapshot_with_inputs(
    source: CanonicalPerformanceSource | None,
    read_snapshot: Callable[[], Any],
    *,
    as_of: date,
) -> tuple[Any, CanonicalPerformanceInputs | None]:
    """Read a snapshot and its canonical load inputs in one read snapshot.

    Without a canonical source the snapshot is read exactly as before. The
    reads never wait for the writer.
    """
    if source is None:
        return read_snapshot(), None
    with source.database_manager().read_snapshot() as db:
        snapshot = read_snapshot()
        return snapshot, read_performance_inputs(
            source.observation_reader(),
            db,
            activity_reader=source.activity_row_reader(),
            as_of=as_of,
        )


def activity_rows_with_sync_time(
    source: CanonicalPerformanceSource,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    """Read the raw activity rows and their sync time in a read of their own.

    The sync time is the canonical coverage fetch time of the Intervals.icu
    activities, None when none is stored. The read never waits for the writer.
    """
    reader = source.activity_row_reader()
    if reader is None:
        raise RuntimeError("activity reads need the canonical activity row reader")
    with source.database_manager().reader() as db:
        coverage = None if source.coverage is None else source.coverage()
        return tuple(reader.activity_rows(db)), activities_synced_at(coverage, db)


def activity_rows_for(source: CanonicalPerformanceSource) -> tuple[dict[str, Any], ...]:
    """Read the raw activity rows in a read of their own, without the writer."""
    return activity_rows_with_sync_time(source)[0]


def inputs_for_snapshot(
    source: CanonicalPerformanceSource | None,
    db: Any,
    *,
    as_of: date,
) -> CanonicalPerformanceInputs | None:
    """Read canonical load inputs inside the caller's snapshot transaction."""
    if source is None:
        return None
    return read_performance_inputs(
        source.observation_reader(),
        db,
        activity_reader=source.activity_row_reader(),
        as_of=as_of,
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


class ReadOnceObservationReader:
    """Serve the reads of one snapshot unit from one unbounded read per kind.

    The wellness days, the current metrics and the recovery inputs all ask for
    overlapping observations, so each kind reaches the
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


class ReadOnceSleepPeriodReader(ReadOnceObservationReader):
    """A read-once reader that keeps the sleep periods of a source that stores them."""

    def __init__(self, reader: ObservationReader) -> None:
        super().__init__(reader)
        self._sleep_reader = cast(SleepPeriodReader, reader)

    def sleep_periods(
        self, db: Any, *, start: date | None = None, end: date | None = None
    ) -> tuple[Any, ...]:
        return self._sleep_reader.sleep_periods(db, start=start, end=end)


def read_once(reader: ObservationReader) -> ReadOnceObservationReader:
    """Wrap a reader for one snapshot unit, keeping its sleep-period reads when it has any."""
    if isinstance(reader, SleepPeriodReader):
        return ReadOnceSleepPeriodReader(reader)
    return ReadOnceObservationReader(reader)


@dataclass(frozen=True, slots=True)
class _CarriedRows:
    """The day views, activity rows and Garmin values carried by an input."""

    activity_rows: tuple[dict[str, Any], ...] | None
    activities: tuple[dict[str, Any], ...] | None
    wellness_days: tuple[WellnessDay, ...]
    history_wellness_days: tuple[WellnessDay, ...]
    garmin: GarminCanonicalMetrics
    daily_health: Mapping[str, Mapping[str, Any]]
    recovery: CanonicalRecoveryInputs
    form_by_day: Mapping[date, float]
    eftp_by_day: Mapping[date, float]
    run_eftp_by_day: Mapping[date, float]

    def inputs(
        self,
        *,
        wellness_day: date | None,
        ctl: float | None,
        atl: float | None,
        current: CanonicalCurrentInputs | None = None,
        ramp_rate: float | None = None,
    ) -> CanonicalPerformanceInputs:
        return CanonicalPerformanceInputs(
            wellness_day=wellness_day,
            ctl=ctl,
            atl=atl,
            current=current,
            recovery=self.recovery,
            activity_rows=self.activity_rows,
            activities=self.activities,
            wellness_days=self.wellness_days,
            history_wellness_days=self.history_wellness_days,
            garmin=self.garmin,
            daily_health=self.daily_health,
            form_by_day=self.form_by_day,
            eftp_by_day=self.eftp_by_day,
            run_eftp_by_day=self.run_eftp_by_day,
            ramp_rate=ramp_rate,
        )


def read_performance_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    activity_reader: ActivityRowReader | None = None,
    as_of: date,
) -> CanonicalPerformanceInputs | None:
    """Read canonical activity rows and wellness days in one selected unit.

    No snapshot section is read. None means no activity reader and
    no observed wellness day. ``as_of`` is the athlete-local day.
    """
    reader = resolve_reader(reader, db)
    if not isinstance(reader, ReadOnceObservationReader):
        reader = read_once(reader)
    history = wellness_days.read_wellness_days(reader, db)
    days = wellness_days.current_window(history)
    activity_rows = (
        None
        if activity_reader is None
        else tuple(
            activity_reader.activity_rows(db, start=_activity_start(days, as_of))
        )
    )
    if activity_rows is None and not days:
        return None
    activities = (
        None
        if activity_rows is None
        else tuple(canonical_sections.compact_activity_rows(activity_rows))
    )
    latest_view = wellness_days.latest(days)
    latest_day = None if latest_view is None else latest_view.day
    carried = _CarriedRows(
        activity_rows=activity_rows,
        activities=activities,
        wellness_days=days,
        history_wellness_days=history,
        garmin=read_garmin_state(
            reader,
            db,
            activities=activity_reader
            if isinstance(activity_reader, ActivityReader)
            else None,
        ).metrics,
        daily_health=read_daily_health_by_date(
            reader, db, start=as_of - timedelta(days=DAILY_HEALTH_DAYS), end=as_of
        ),
        recovery=read_recovery_inputs(
            reader, db, as_of=as_of, latest_wellness_day=latest_day
        ),
        form_by_day=wellness_days.series(history, MetricKind.FORM),
        eftp_by_day=wellness_days.wellness_day_values(
            reader.observations(db, MetricKind.EFTP, sport=Sport.RIDE),
            sport=Sport.RIDE,
        ),
        run_eftp_by_day=wellness_days.wellness_day_values(
            reader.observations(db, MetricKind.EFTP, sport=Sport.RUN),
            sport=Sport.RUN,
        ),
    )
    if latest_day is None:
        return carried.inputs(
            wellness_day=None,
            ctl=None,
            atl=None,
            current=read_wahoo_fallbacks(reader, db, as_of=as_of),
        )
    start = days[0].day
    loaded = _load_resolved(
        reader, db, latest_wellness_day=latest_day, start=start, end=latest_day
    )
    return carried.inputs(
        wellness_day=loaded.wellness_day,
        ctl=loaded.ctl,
        atl=loaded.atl,
        current=read_current_inputs(
            reader, db, latest_wellness_day=latest_day, as_of=as_of
        ),
        ramp_rate=_ramp_rate(
            wellness_days.series(days, MetricKind.CTL),
            latest_day,
        ),
    )


def _ramp_rate(ctl_by_day: Mapping[date, float], day: date) -> float | None:
    """Return the CTL change over ``RAMP_RATE_DAYS`` days; exact days only."""
    current = ctl_by_day.get(day)
    earlier = ctl_by_day.get(day - timedelta(days=RAMP_RATE_DAYS))
    if current is None or earlier is None:
        return None
    return round(current - earlier, 2)


def _activity_start(days: tuple[WellnessDay, ...], as_of: date) -> date:
    """Return the first day of activities the performance inputs read."""
    return (
        min(as_of - timedelta(days=ACTIVITY_HISTORY_DAYS - 1), days[0].day)
        if days
        else as_of - timedelta(days=ACTIVITY_HISTORY_DAYS - 1)
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
