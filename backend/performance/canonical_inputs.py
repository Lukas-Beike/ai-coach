"""Read performance inputs through canonical observation and activity ports.

Wellness values come only from provider-neutral ``WellnessDay`` observations.
The current window covers 90 days ending on its latest day; history keeps every
stored day. Snapshot wellness sections do not affect these inputs. Activities
cover the year before ``as_of``, extended to the current window's first day.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import date, timedelta
from typing import Any, Final, cast

from backend.activities.activity_summary import ActivitySummary
from backend.activities.sync_time import activities_synced_at
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance import wellness_days
from backend.performance.canonical_body import (
    EMPTY_BODY_INPUTS,
    CanonicalBodyInputs,
    read_body_inputs,
)
from backend.performance.canonical_current import (
    NO_CURRENT_INPUTS,
    CanonicalCurrentInputs,
    read_current_inputs,
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
    ActivityMaxHrReader,
    ActivityRowAndSummaryReader,
    ActivitySummaryReader,
    CanonicalReadStatus,
    ObservationReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
    SleepPeriodReader,
)


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceInputs:
    """CTL and ATL for the wellness day that the legacy load context reads.

    ``wellness_day`` is None when there is no usable wellness day. ``current`` holds
    the athlete settings, weights and Wahoo fallbacks of the latest sync; it is
    empty when they were not read. ``recovery`` holds the recovery observations of the current context and
    the personal baselines, or None when they were not read.

    ``activities`` are the neutral activity summaries, one per session. ``wellness_days`` is the current 90-day window;
    ``history_wellness_days`` keeps all stored days and their provenance.

    ``garmin`` holds the Garmin performance values and ``daily_health`` the daily
    totals of the last ``DAILY_HEALTH_DAYS`` days by ISO date; both are None when
    they were not read. ``body`` holds the Garmin weight and body fat of the body
    history window.

    ``form_by_day``, ``eftp_by_day`` and ``run_eftp_by_day`` are the
    Intervals.icu wellness-day form and sport-scoped eFTP series.
    ``ramp_rate`` is the latest wellness day's CTL minus the CTL of exactly seven
    days earlier, rounded to two decimals, or None when either day is missing.

    ``pending`` is True while the canonical source serves nothing yet (the first
    backfill has not completed); every value is then empty.
    ``activities_need_refresh`` is True while stored compact Intervals.icu
    activities have no raw counterpart and are missing from the tables until the
    full Intervals.icu reload.
    """

    wellness_day: date | None
    ctl: float | None
    atl: float | None
    current: CanonicalCurrentInputs = NO_CURRENT_INPUTS
    recovery: CanonicalRecoveryInputs | None = None
    activities: tuple[ActivitySummary, ...] | None = None
    wellness_days: tuple[WellnessDay, ...] | None = None
    history_wellness_days: tuple[WellnessDay, ...] | None = None
    garmin: GarminCanonicalMetrics | None = None
    daily_health: Mapping[str, Mapping[str, Any]] | None = None
    form_by_day: Mapping[date, float] | None = None
    eftp_by_day: Mapping[date, float] | None = None
    run_eftp_by_day: Mapping[date, float] | None = None
    ramp_rate: float | None = None
    body: CanonicalBodyInputs = EMPTY_BODY_INPUTS
    pending: bool = False
    activities_need_refresh: bool = False


# The inputs of a consumer without a canonical source: every value is unknown.
EMPTY_PERFORMANCE_INPUTS: Final = CanonicalPerformanceInputs(
    wellness_day=None, ctl=None, atl=None
)
# The inputs before the first completed backfill: no values, marked pending.
PENDING_PERFORMANCE_INPUTS: Final = CanonicalPerformanceInputs(
    wellness_day=None, ctl=None, atl=None, pending=True
)


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceSource:
    """Lazy accessors a consumer uses to read canonical load inputs.

    Both callables are resolved at read time, as the other assemblies do, so the
    composition root can pass ``lambda: ...`` accessors. ``serving`` is optional;
    with it the inputs are marked pending before the first completed backfill and
    carry the compact-only activity gap (``with_read_status``).
    ``activity_summaries`` is optional; without it a consumer reads no activities.
    ``coverage`` is optional; without it the activities' sync time is unknown.
    """

    database_manager: Callable[[], Any]
    observation_reader: Callable[[], ObservationReader]
    serving: Callable[[], CanonicalReadStatus] | None = None
    activity_summaries: Callable[[], ActivityRowAndSummaryReader] | None = None
    coverage: Callable[[], ProviderCoverageReader] | None = None

    def activity_summary_reader(self) -> ActivityRowAndSummaryReader | None:
        """Return the configured activity summary reader, if any."""
        return None if self.activity_summaries is None else self.activity_summaries()


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
        return snapshot, inputs_for_snapshot(source, db, as_of=as_of)


def with_read_status(
    source: CanonicalPerformanceSource,
    db: Any,
    inputs: CanonicalPerformanceInputs | None,
) -> CanonicalPerformanceInputs | None:
    """Mark the inputs with the canonical read state of ``source``, if it reports one.

    Before the first completed backfill the reads are empty and the inputs are
    ``PENDING_PERFORMANCE_INPUTS``; afterwards a compact-only activity gap is
    carried as ``activities_need_refresh``.
    """
    if source.serving is None:
        return inputs
    status = source.serving()
    if not status.serves_tables(db):
        return PENDING_PERFORMANCE_INPUTS
    if status.activities_need_refresh(db):
        base = inputs or EMPTY_PERFORMANCE_INPUTS
        values = {field.name: getattr(base, field.name) for field in fields(base)}
        return CanonicalPerformanceInputs(**{**values, "activities_need_refresh": True})
    return inputs


def activity_summaries_with_sync_time(
    source: CanonicalPerformanceSource,
) -> tuple[tuple[ActivitySummary, ...], str | None]:
    """Read the activity summaries and their sync time in a read of their own.

    The sync time is the canonical coverage fetch time of the Intervals.icu
    activities, None when none is stored. The read never waits for the writer.
    """
    reader = source.activity_summary_reader()
    if reader is None:
        raise RuntimeError("activity reads need the canonical activity summary reader")
    with source.database_manager().reader() as db:
        coverage = None if source.coverage is None else source.coverage()
        return reader.activity_summaries(db), activities_synced_at(coverage, db)


def activity_summaries_and_rows(
    source: CanonicalPerformanceSource,
) -> tuple[tuple[ActivitySummary, ...], tuple[dict[str, Any], ...]]:
    """Read the summaries and the raw Intervals.icu rows in one read snapshot.

    Stored analyses fingerprint the raw row they were computed from, so the rows
    must belong to the same revision as the summaries.
    """
    reader = source.activity_summary_reader()
    if reader is None:
        raise RuntimeError("activity reads need the canonical activity summary reader")
    with source.database_manager().read_snapshot() as db:
        return reader.activity_summaries(db), reader.activity_rows(db)


def activity_summaries_for(
    source: CanonicalPerformanceSource,
) -> tuple[ActivitySummary, ...]:
    """Read the activity summaries in a read of their own, without the writer."""
    return activity_summaries_with_sync_time(source)[0]


def inputs_for_snapshot(
    source: CanonicalPerformanceSource | None,
    db: Any,
    *,
    as_of: date,
) -> CanonicalPerformanceInputs | None:
    """Read canonical load inputs inside the caller's snapshot transaction."""
    if source is None:
        return None
    return with_read_status(
        source,
        db,
        read_performance_inputs(
            source.observation_reader(),
            db,
            activity_reader=source.activity_summary_reader(),
            as_of=as_of,
        ),
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


class ReadOnceObservationReader:
    """Serve the reads of one snapshot unit from one unbounded read per kind.

    The wellness days, the current metrics and the recovery inputs all ask for
    overlapping observations, so each kind reaches the
    database once per call and the bounds are applied in memory.
    """

    def __init__(self, reader: ObservationReader) -> None:
        self._reader = reader
        self._rows: dict[MetricKind, tuple[Observation, ...]] = {}

    def activity_max_hr(
        self, db: Any, provider: ProviderId, *, low: float, high: float
    ) -> tuple[tuple[Sport, float, date], ...]:
        """Forward the activity max heart rate read; none for a source without it."""
        if not isinstance(self._reader, ActivityMaxHrReader):
            return ()
        return self._reader.activity_max_hr(db, provider, low=low, high=high)

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

    activities: tuple[ActivitySummary, ...] | None
    wellness_days: tuple[WellnessDay, ...]
    history_wellness_days: tuple[WellnessDay, ...]
    garmin: GarminCanonicalMetrics
    daily_health: Mapping[str, Mapping[str, Any]]
    body: CanonicalBodyInputs
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
        current: CanonicalCurrentInputs,
        ramp_rate: float | None = None,
    ) -> CanonicalPerformanceInputs:
        return CanonicalPerformanceInputs(
            wellness_day=wellness_day,
            ctl=ctl,
            atl=atl,
            current=current,
            recovery=self.recovery,
            activities=self.activities,
            wellness_days=self.wellness_days,
            history_wellness_days=self.history_wellness_days,
            garmin=self.garmin,
            daily_health=self.daily_health,
            body=self.body,
            form_by_day=self.form_by_day,
            eftp_by_day=self.eftp_by_day,
            run_eftp_by_day=self.run_eftp_by_day,
            ramp_rate=ramp_rate,
        )


def read_performance_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    activity_reader: ActivitySummaryReader | None = None,
    as_of: date,
) -> CanonicalPerformanceInputs | None:
    """Read canonical activity summaries and wellness days in one selected unit.

    No snapshot section is read. None means no activity reader and
    no observed wellness day. ``as_of`` is the athlete-local day.
    """
    reader = resolve_reader(reader, db)
    if not isinstance(reader, ReadOnceObservationReader):
        reader = read_once(reader)
    history = wellness_days.read_wellness_days(reader, db)
    days = wellness_days.current_window(history)
    activities = (
        None
        if activity_reader is None
        else activity_reader.activity_summaries(db, start=_activity_start(days, as_of))
    )
    if activities is None and not days:
        return None
    latest_view = wellness_days.latest(days)
    latest_day = None if latest_view is None else latest_view.day
    carried = _CarriedRows(
        activities=activities,
        wellness_days=days,
        history_wellness_days=history,
        garmin=read_garmin_state(reader, db).metrics,
        daily_health=read_daily_health_by_date(
            reader, db, start=as_of - timedelta(days=DAILY_HEALTH_DAYS), end=as_of
        ),
        body=read_body_inputs(reader, db, as_of),
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
            current=read_current_inputs(reader, db, as_of=as_of),
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
