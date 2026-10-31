"""Canonical current metrics: Intervals sport thresholds and VO2max from one sync.

The Intervals snapshot is projected into canonical observations dated on the
athlete-local sync day and stamped with the snapshot's sync instant. The current
sync is the latest ``retrieved_at`` among the Intervals threshold, VO2max and
weight observations, so no snapshot section anchors the read. The read keeps only
Intervals rows whose ``retrieved_at`` equals that instant, within the UTC sync day
and one day either side (the athlete-local day always lies inside that window).
Rows from older syncs stay in the tables and never change the current values.

Sport-scoped values keep every candidate of this sync for that sport, because the
legacy reader takes the first matching sport setting and the caller must match that
value rather than a canonical pick. The athlete-wide threshold heart rate has no
sport and comes from the single athlete ``lthr`` field, so this sync stores at most
one such row and it is taken directly.

Cycling eFTP: the ride eFTP of the latest sync's athlete record is read like the
athlete weight, and the ride eFTP of the latest wellness day like the wellness weight.
The sync instant is the latest of the threshold, VO2max, weight and athlete-record
observations, so an athlete record that stores only an eFTP still defines it. The
wellness-day eFTP needs a wellness day.

Weight is read for the latest wellness day, from the newest stored row of that
day, and for the athlete record of the sync. Garmin weight stays on the Garmin
path. Only athlete-record observations define the sync instant, so a later write
of wellness rows alone (a partial sync) never hides the athlete settings.

The athlete record's other settings (sport FTP, max heart rate, run threshold and
Zone-2 pace, body fat, height and W′) are kept as ``athlete_record``, the athlete
record observations of the same sync; they also define the sync instant. They are
read with or without a wellness day.

Wahoo cycling FTP and Wahoo weight are read separately, without an Intervals sync
instant, because each Wahoo row keeps its own fetch time. They are the caller's
fallbacks, so a Wahoo-only store still yields them when no Intervals sync exists.
The Intervals fields then stay empty.

A Wahoo value older than its age limit on the athlete-local ``as_of`` day is
not current. Its row stays stored and readable, so history keeps it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.source_policy import select_current
from backend.runtime.ports import ObservationReader

_SYNC_KINDS: Final = (MetricKind.THRESHOLD_HR, MetricKind.VO2MAX, MetricKind.WEIGHT)
# Athlete record settings kept as ``athlete_record``; eFTP has its own fields.
_ATHLETE_RECORD_KINDS: Final = (
    MetricKind.VO2MAX,
    MetricKind.FTP,
    MetricKind.MAX_HR,
    MetricKind.THRESHOLD_PACE,
    MetricKind.ZONE2_PACE,
    MetricKind.BODY_FAT,
    MetricKind.HEIGHT,
    MetricKind.W_PRIME,
)
# Kinds whose athlete-record rows define the sync instant, each read once.
_INSTANT_KINDS: Final = tuple(
    dict.fromkeys((*_SYNC_KINDS, MetricKind.EFTP, *_ATHLETE_RECORD_KINDS))
)
_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CanonicalCurrentInputs:
    """The Intervals observations of one sync, plus the stored Wahoo fallbacks.

    Sport-scoped fields hold the observations of this sync for that sport; the
    mapper stores at most one per sport and sync. The athlete-wide and weight
    fields hold one observation or None, and ``athlete_record`` the athlete
    record's other settings. ``wahoo_ftp`` is the newest cycling FTP and
    ``wahoo_weight`` the newest weight stored from Wahoo, or None. ``synced_at``
    is the sync instant of those Intervals observations, or None without a sync.
    """

    bike_threshold_hr: tuple[Observation, ...]
    run_threshold_hr: tuple[Observation, ...]
    athlete_threshold_hr: Observation | None
    cycling_vo2max: tuple[Observation, ...]
    running_vo2max: tuple[Observation, ...]
    wellness_weight: Observation | None
    athlete_weight: Observation | None
    wahoo_ftp: Observation | None = None
    wahoo_weight: Observation | None = None
    athlete_eftp: Observation | None = None
    wellness_eftp: Observation | None = None
    athlete_record: tuple[Observation, ...] = ()
    synced_at: datetime | None = None

    def athlete_value(
        self, kind: MetricKind, sport: Sport | None = None
    ) -> Observation | None:
        """Return this sync's athlete record observation of ``kind`` and ``sport``."""
        return next(
            (
                observation
                for observation in self.athlete_record
                if observation.kind is kind and observation.sport is sport
            ),
            None,
        )


NO_CURRENT_INPUTS: Final = CanonicalCurrentInputs(
    bike_threshold_hr=(),
    run_threshold_hr=(),
    athlete_threshold_hr=None,
    cycling_vo2max=(),
    running_vo2max=(),
    wellness_weight=None,
    athlete_weight=None,
)


def read_current_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    latest_wellness_day: date | None = None,
    as_of: date,
) -> CanonicalCurrentInputs:
    """Read the latest sync's athlete settings and weights, and the Wahoo fallbacks.

    ``latest_wellness_day`` is the latest wellness day. Without it no wellness-row
    weight or eFTP is selected. ``as_of`` is the athlete-local day the Wahoo values
    must be current on. Without anything stored every field is empty.
    """
    intervals = _intervals_current(reader, db) or _NO_SYNC
    wahoo_ftp, wahoo_weight = _wahoo_current(reader, db, as_of=as_of)
    return CanonicalCurrentInputs(
        bike_threshold_hr=intervals.bike_threshold_hr,
        run_threshold_hr=intervals.run_threshold_hr,
        athlete_threshold_hr=intervals.athlete_threshold_hr,
        cycling_vo2max=intervals.cycling_vo2max,
        running_vo2max=intervals.running_vo2max,
        wellness_weight=_wellness_weight(reader, db, latest_wellness_day),
        athlete_weight=intervals.athlete_weight,
        wahoo_ftp=wahoo_ftp,
        wahoo_weight=wahoo_weight,
        athlete_eftp=intervals.athlete_eftp,
        wellness_eftp=_wellness_eftp(reader, db, latest_wellness_day),
        athlete_record=intervals.athlete_record,
        synced_at=intervals.synced_at,
    )


@dataclass(frozen=True, slots=True)
class _SyncValues:
    """The athlete-record observations of one Intervals sync."""

    bike_threshold_hr: tuple[Observation, ...] = ()
    run_threshold_hr: tuple[Observation, ...] = ()
    athlete_threshold_hr: Observation | None = None
    cycling_vo2max: tuple[Observation, ...] = ()
    running_vo2max: tuple[Observation, ...] = ()
    athlete_weight: Observation | None = None
    athlete_eftp: Observation | None = None
    athlete_record: tuple[Observation, ...] = ()
    synced_at: datetime | None = None


_NO_SYNC: Final = _SyncValues()


def _intervals_current(reader: ObservationReader, db: Any) -> _SyncValues | None:
    """Return the Intervals observations of the latest sync; None without a sync."""
    synced = _latest_sync_instant(reader, db)
    if synced is None:
        return None
    try:
        day = synced.astimezone(UTC).date()
        start, end = day - timedelta(days=1), day + timedelta(days=1)
    except OverflowError:
        return None
    thresholds = _sync_observations(
        reader, db, MetricKind.THRESHOLD_HR, synced, start=start, end=end
    )
    vo2max = _sync_observations(
        reader, db, MetricKind.VO2MAX, synced, start=start, end=end
    )
    weights = _sync_observations(
        reader, db, MetricKind.WEIGHT, synced, start=start, end=end
    )
    eftps = _sync_observations(
        reader, db, MetricKind.EFTP, synced, start=start, end=end
    )
    athlete_record = tuple(
        observation
        for kind in _ATHLETE_RECORD_KINDS
        for observation in _sync_observations(
            reader, db, kind, synced, start=start, end=end
        )
        if _is_athlete_record(observation)
    )
    return _SyncValues(
        bike_threshold_hr=_sport_candidates(thresholds, Sport.RIDE),
        run_threshold_hr=_sport_candidates(thresholds, Sport.RUN),
        athlete_threshold_hr=_athlete_observation(thresholds),
        cycling_vo2max=_sport_candidates(vo2max, Sport.RIDE),
        running_vo2max=_sport_candidates(vo2max, Sport.RUN),
        athlete_weight=_athlete_weight(weights),
        athlete_eftp=_athlete_eftp(eftps),
        athlete_record=athlete_record,
        synced_at=synced,
    )


def _athlete_eftp(observations: tuple[Observation, ...]) -> Observation | None:
    """Return the ride eFTP of this sync's athlete record, if stored."""
    return next(
        (
            observation
            for observation in observations
            if observation.sport is Sport.RIDE and _is_athlete_record(observation)
        ),
        None,
    )


def _wellness_eftp(
    reader: ObservationReader, db: Any, day: date | None
) -> Observation | None:
    """Return the ride eFTP observation of the Intervals wellness day ``day``."""
    if day is None:
        return None
    record_id = day.isoformat()
    return next(
        (
            observation
            for observation in reader.observations(
                db, MetricKind.EFTP, start=day, end=day, sport=Sport.RIDE
            )
            if observation.provenance.provider is ProviderId.INTERVALS
            and observation.provenance.source_record_id == record_id
        ),
        None,
    )


def _wahoo_current(
    reader: ObservationReader, db: Any, *, as_of: date
) -> tuple[Observation | None, Observation | None]:
    """Return the current Wahoo cycling FTP and the current Wahoo weight, or None each.

    Sport-scoped ranking ignores days, so the cycling FTP is reduced first to the
    newest stored zone set, by observed day and then fetch time. The weight is
    ranked by ``select_current`` over every stored Wahoo weight. Both must be within
    their age limit on ``as_of``.
    """
    ftps = [
        observation
        for observation in reader.observations(db, MetricKind.FTP)
        if observation.provenance.provider is ProviderId.WAHOO
        and observation.sport is Sport.RIDE
    ]
    newest = max(ftps, key=_newest_first, default=None)
    ftp = (
        None
        if newest is None
        else select_current([newest], MetricKind.FTP, sport=Sport.RIDE, as_of=as_of)
    )
    weights = [
        observation
        for observation in reader.observations(db, MetricKind.WEIGHT)
        if observation.provenance.provider is ProviderId.WAHOO
    ]
    return ftp, select_current(weights, MetricKind.WEIGHT, as_of=as_of)


def _newest_first(observation: Observation) -> tuple[date, datetime]:
    """Order observations by observed day, then fetch time; a missing fetch time is oldest."""
    return observation.observed_on, observation.provenance.retrieved_at or _EARLIEST


def _sport_candidates(
    observations: tuple[Observation, ...], sport: Sport
) -> tuple[Observation, ...]:
    """Return every observation of this sync for ``sport``, in reader order."""
    return tuple(
        observation for observation in observations if observation.sport is sport
    )


def _wellness_weight(
    reader: ObservationReader, db: Any, day: date | None
) -> Observation | None:
    """Return the newest stored Intervals weight of the wellness row for ``day``."""
    if day is None:
        return None
    record_id = day.isoformat()
    return max(
        (
            observation
            for observation in reader.observations(
                db, MetricKind.WEIGHT, start=day, end=day
            )
            if observation.provenance.provider is ProviderId.INTERVALS
            and observation.provenance.source_record_id == record_id
        ),
        key=lambda observation: observation.provenance.retrieved_at or _EARLIEST,
        default=None,
    )


def _athlete_weight(observations: tuple[Observation, ...]) -> Observation | None:
    """Return the weight of this sync's athlete record, if stored."""
    return next(
        (
            observation
            for observation in observations
            if observation.provenance.source_record_id
            != observation.observed_on.isoformat()
        ),
        None,
    )


def _sync_observations(
    reader: ObservationReader,
    db: Any,
    kind: MetricKind,
    synced: datetime,
    *,
    start: date,
    end: date,
) -> tuple[Observation, ...]:
    """Return the Intervals observations of ``kind`` stored by this sync."""
    return tuple(
        observation
        for observation in reader.observations(db, kind, start=start, end=end)
        if observation.provenance.provider is ProviderId.INTERVALS
        and observation.provenance.retrieved_at == synced
    )


def _athlete_observation(observations: tuple[Observation, ...]) -> Observation | None:
    """Return the sport-less threshold heart rate of this sync, if stored."""
    return next(
        (observation for observation in observations if observation.sport is None),
        None,
    )


def _is_athlete_record(observation: Observation) -> bool:
    """Return True for a value of the athlete record, not of a wellness day."""
    return (
        observation.provenance.source_record_id != observation.observed_on.isoformat()
    )


def _latest_sync_instant(reader: ObservationReader, db: Any) -> datetime | None:
    """Return the latest Intervals sync instant that stored a current-metric kind."""
    instants = [
        observation.provenance.retrieved_at
        for kind in _INSTANT_KINDS
        for observation in reader.observations(db, kind)
        if observation.provenance.provider is ProviderId.INTERVALS
        and observation.provenance.retrieved_at is not None
        and _is_athlete_record(observation)
    ]
    return max(instants, default=None)
