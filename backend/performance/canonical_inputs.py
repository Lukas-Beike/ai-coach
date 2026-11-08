"""Read performance inputs through canonical observation and activity ports.

Activities cover the year before ``as_of``, extended to the current window's
first day. Provider snapshot sections do not affect these inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Final, cast

from backend.activities.activity_summary import ActivitySummary
from backend.activities.sync_time import activities_synced_at
from backend.canonical.domain_records import (
    ZoneConfiguration,
)
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
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
from backend.performance.current_thresholds import ZoneConfigurationSource
from backend.performance.daily_health import read_daily_health_by_date
from backend.performance.garmin_canonical import (
    GarminCanonicalMetrics,
    read_garmin_state,
)
from backend.performance.source_policy import (
    NO_PREFERENCES,
    SourcePreferences,
)
from backend.runtime.ports import (
    ActivityMaxHrReader,
    ActivityRowAndSummaryReader,
    ActivitySummaryReader,
    CanonicalReadStatus,
    LocalLoadDayReader,
    ObservationReader,
    ObservationSourceSelector,
    ProviderCoverageReader,
    SleepPeriodReader,
)


@dataclass(frozen=True, slots=True)
class CanonicalPerformanceInputs:
    """The canonical inputs of the performance and Coach reads.

    ``current`` holds the Wahoo fallbacks and the resolved thresholds; it is empty
    when they were not read. ``recovery`` holds the recovery observations of the current context and
    the personal baselines, or None when they were not read.

    ``activities`` are the neutral activity summaries, one per session.

    ``garmin`` holds the Garmin performance values and ``daily_health`` the daily
    totals of the last ``DAILY_HEALTH_DAYS`` days by ISO date; both are None when
    they were not read. ``body`` holds the Garmin weight and body fat of the body
    history window.

    ``local_load_days`` is the stored local session load (card M6) per local ISO
    day of the whole history, None when the reader does not store it.

    ``activities_synced_at`` is the fetch time of the activities alone: wellness
    or profile refreshes do not advance it.

    ``pending`` is True while the canonical source serves nothing yet (the first
    backfill has not completed); every value is then empty.
    """

    current: CanonicalCurrentInputs = NO_CURRENT_INPUTS
    recovery: CanonicalRecoveryInputs | None = None
    activities: tuple[ActivitySummary, ...] | None = None
    garmin: GarminCanonicalMetrics | None = None
    daily_health: Mapping[str, Mapping[str, Any]] | None = None
    local_load_days: Mapping[str, float] | None = None
    body: CanonicalBodyInputs = EMPTY_BODY_INPUTS
    pending: bool = False
    backfill_failed: bool = False
    activities_synced_at: str | None = None
    # The athlete's preferred source per metric group, read with these inputs.
    preferences: SourcePreferences = NO_PREFERENCES


# The inputs of a consumer without a canonical source: every value is unknown.
EMPTY_PERFORMANCE_INPUTS: Final = CanonicalPerformanceInputs()
# The inputs before the first completed backfill: no values, marked pending.
PENDING_PERFORMANCE_INPUTS: Final = CanonicalPerformanceInputs(pending=True)


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
    # Reads the athlete's preferred sources inside the caller's unit of work.
    source_preferences: Callable[[Any], SourcePreferences] | None = None

    def preferences_in(self, db: Any) -> SourcePreferences:
        """Return the athlete's preferred sources; none without an accessor."""
        if self.source_preferences is None:
            return NO_PREFERENCES
        return self.source_preferences(db)

    def activity_summary_reader(self) -> ActivityRowAndSummaryReader | None:
        """Return the configured activity summary reader, if any."""
        return None if self.activity_summaries is None else self.activity_summaries()


# Activities older than this are not read for the performance inputs.
ACTIVITY_HISTORY_DAYS: Final = 365
# Daily totals of the days before ``as_of`` that the 7-day averages read.
DAILY_HEALTH_DAYS: Final = 7


def with_read_status(
    source: CanonicalPerformanceSource,
    db: Any,
    inputs: CanonicalPerformanceInputs | None,
) -> CanonicalPerformanceInputs | None:
    """Mark the inputs with the canonical read state of ``source``, if it reports one.

    Before the first completed backfill the reads are empty and the inputs are
    ``PENDING_PERFORMANCE_INPUTS``; afterwards they are served unchanged. With a
    coverage reader the inputs carry the activity sync time of the active
    providers (``activities_synced_at``).
    """
    marked = _read_state(source, db, inputs)
    if marked is None or marked.pending or source.coverage is None:
        return marked
    coverage = source.coverage()
    activities = activities_synced_at(coverage, db)
    if activities is None:
        return marked
    return _changed(marked, activities_synced_at=activities)


def _changed(
    base: CanonicalPerformanceInputs, **changes: Any
) -> CanonicalPerformanceInputs:
    """Return a copy of ``base`` with ``changes`` applied."""
    return cast(CanonicalPerformanceInputs, replace(base, **changes))


def _read_state(
    source: CanonicalPerformanceSource,
    db: Any,
    inputs: CanonicalPerformanceInputs | None,
) -> CanonicalPerformanceInputs | None:
    if source.serving is None:
        return inputs
    status = source.serving()
    if not status.serves_tables(db):
        if status.backfill_failed(db):
            return _changed(PENDING_PERFORMANCE_INPUTS, backfill_failed=True)
        return PENDING_PERFORMANCE_INPUTS
    return inputs


def activity_summaries_with_sync_time(
    source: CanonicalPerformanceSource,
) -> tuple[tuple[ActivitySummary, ...], str | None]:
    """Read the activity summaries and their sync time in a read of their own.

    The sync time is the canonical coverage fetch time of the activities, None
    when none is stored. The read never waits for the writer.
    """
    summaries, synced_at, _loads = _read_summaries(source, load_days=False)
    return summaries, synced_at


def activity_summaries_with_load_days(
    source: CanonicalPerformanceSource,
) -> tuple[tuple[ActivitySummary, ...], str | None, Mapping[str, float]]:
    """Read the summaries, their sync time and the local load per day in one read.

    The load days are empty when the reader does not store the local load.
    """
    return _read_summaries(source, load_days=True)


def _read_summaries(
    source: CanonicalPerformanceSource, *, load_days: bool
) -> tuple[tuple[ActivitySummary, ...], str | None, Mapping[str, float]]:
    reader = source.activity_summary_reader()
    if reader is None:
        raise RuntimeError("activity reads need the canonical activity summary reader")
    with source.database_manager().reader() as db:
        coverage = None if source.coverage is None else source.coverage()
        loads = (
            reader.local_load_days(db)
            if load_days and isinstance(reader, LocalLoadDayReader)
            else {}
        )
        return reader.activity_summaries(db), activities_synced_at(coverage, db), loads


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
    """Read canonical load inputs inside the caller's snapshot transaction.

    The whole-history local load per day is always read: every snapshot
    consumer shows the local fitness (card M7).
    """
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
            include_local_load=True,
            preferences=source.preferences_in(db),
        ),
    )


def resolve_reader(reader: ObservationReader, db: Any) -> ObservationReader:
    """Choose the serving source once for a unit of work when the reader selects."""
    if isinstance(reader, ObservationSourceSelector):
        return reader.reader_for(db)
    return reader


class ReadOnceObservationReader:
    """Serve the reads of one snapshot unit from one unbounded read per kind.

    The current metrics and the recovery inputs all ask for
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

    def zone_configurations(self, db: Any) -> tuple[ZoneConfiguration, ...]:
        """Forward the zone configuration read; none for a source without it."""
        if not isinstance(self._reader, ZoneConfigurationSource):
            return ()
        return self._reader.zone_configurations(db)

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
    garmin: GarminCanonicalMetrics
    daily_health: Mapping[str, Mapping[str, Any]]
    body: CanonicalBodyInputs
    recovery: CanonicalRecoveryInputs
    local_load_days: Mapping[str, float] | None

    def inputs(
        self,
        *,
        current: CanonicalCurrentInputs,
        preferences: SourcePreferences = NO_PREFERENCES,
    ) -> CanonicalPerformanceInputs:
        return CanonicalPerformanceInputs(
            current=current,
            recovery=self.recovery,
            activities=self.activities,
            garmin=self.garmin,
            daily_health=self.daily_health,
            body=self.body,
            local_load_days=self.local_load_days,
            preferences=preferences,
        )


def read_performance_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    activity_reader: ActivitySummaryReader | None = None,
    as_of: date,
    include_local_load: bool = False,
    preferences: SourcePreferences = NO_PREFERENCES,
) -> CanonicalPerformanceInputs | None:
    """Read canonical activity summaries and provider values in one selected unit.

    ``preferences`` (the athlete's preferred sources) is applied by every
    selection over these inputs and carried with them.

    No snapshot section is read. None means no activity reader.
    ``as_of`` is the athlete-local day. ``include_local_load``
    also reads the whole-history local load per day (``local_load_days``);
    otherwise it stays None.
    """
    reader = resolve_reader(reader, db)
    if not isinstance(reader, ReadOnceObservationReader):
        reader = read_once(reader)
    activities = (
        None
        if activity_reader is None
        else activity_reader.activity_summaries(
            db, start=as_of - timedelta(days=ACTIVITY_HISTORY_DAYS - 1)
        )
    )
    if activities is None:
        return None
    carried = _CarriedRows(
        activities=activities,
        garmin=read_garmin_state(reader, db).metrics,
        daily_health=read_daily_health_by_date(
            reader, db, start=as_of - timedelta(days=DAILY_HEALTH_DAYS), end=as_of
        ),
        body=read_body_inputs(reader, db, as_of),
        recovery=read_recovery_inputs(reader, db, as_of=as_of, preferences=preferences),
        local_load_days=activity_reader.local_load_days(db)
        if include_local_load and isinstance(activity_reader, LocalLoadDayReader)
        else None,
    )
    return carried.inputs(
        current=read_current_inputs(reader, db, as_of=as_of, preferences=preferences),
        preferences=preferences,
    )
