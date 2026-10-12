"""Canonical current metrics: Intervals sport thresholds and VO2max from one sync.

The Intervals snapshot is projected into canonical observations dated on the
athlete-local sync day and stamped with the snapshot's sync instant. The read
therefore keeps only Intervals rows whose ``retrieved_at`` equals the snapshot's
``synced_at`` instant, within the UTC sync day and one day either side (the
athlete-local day always lies inside that window). Rows from older syncs stay in
the tables and never change the current values.

Sport-scoped values keep every candidate of this sync for that sport, because the
legacy reader takes the first matching sport setting and the caller must match that
value rather than a canonical pick. The athlete-wide threshold heart rate has no
sport and comes from the single athlete ``lthr`` field, so this sync stores at most
one such row and it is taken directly.

Weight is read for the snapshot's latest wellness row (the row the legacy reader
picks) and for the athlete record of the same sync. Garmin weight stays on the
legacy path.

A snapshot without an aware ``synced_at`` yields None, and the caller keeps the
legacy values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.runtime.ports import ObservationReader

_SYNCED_AT: Final = "synced_at"


@dataclass(frozen=True, slots=True)
class CanonicalCurrentInputs:
    """The Intervals observations of one sync.

    Sport-scoped fields hold every observation of this sync for that sport, so the
    caller can match the legacy-selected sport setting by value. The athlete-wide
    and weight fields hold one observation or None.
    """

    bike_threshold_hr: tuple[Observation, ...]
    run_threshold_hr: tuple[Observation, ...]
    athlete_threshold_hr: Observation | None
    cycling_vo2max: tuple[Observation, ...]
    running_vo2max: tuple[Observation, ...]
    wellness_weight: Observation | None
    athlete_weight: Observation | None


def read_current_inputs(
    reader: ObservationReader,
    db: Any,
    snapshot: Mapping[str, Any] | None,
    *,
    latest_wellness_day: date | None = None,
) -> CanonicalCurrentInputs | None:
    """Read the current sport thresholds, VO2max and weight for a stored snapshot.

    ``latest_wellness_day`` is the snapshot's latest wellness row. Without it no
    wellness-row weight is selected, and the caller keeps the legacy value.
    """
    synced = _synced_instant(snapshot)
    if synced is None:
        return None
    try:
        day = synced.astimezone(UTC).date()
        start, end = day - timedelta(days=1), day + timedelta(days=1)
        weight_start, weight_end = start, end
        if latest_wellness_day is not None:
            weight_start = min(start, latest_wellness_day)
            weight_end = max(end, latest_wellness_day)
    except OverflowError:
        return None
    thresholds = _sync_observations(
        reader, db, MetricKind.THRESHOLD_HR, synced, start=start, end=end
    )
    vo2max = _sync_observations(
        reader, db, MetricKind.VO2MAX, synced, start=start, end=end
    )
    weights = _sync_observations(
        reader, db, MetricKind.WEIGHT, synced, start=weight_start, end=weight_end
    )
    inputs = CanonicalCurrentInputs(
        bike_threshold_hr=_sport_candidates(thresholds, Sport.RIDE),
        run_threshold_hr=_sport_candidates(thresholds, Sport.RUN),
        athlete_threshold_hr=_athlete_observation(thresholds),
        cycling_vo2max=_sport_candidates(vo2max, Sport.RIDE),
        running_vo2max=_sport_candidates(vo2max, Sport.RUN),
        wellness_weight=_wellness_weight(weights, latest_wellness_day),
        athlete_weight=_athlete_weight(weights),
    )
    values = (
        *inputs.bike_threshold_hr,
        *inputs.run_threshold_hr,
        inputs.athlete_threshold_hr,
        *inputs.cycling_vo2max,
        *inputs.running_vo2max,
        inputs.wellness_weight,
        inputs.athlete_weight,
    )
    if all(value is None for value in values):
        return None
    return inputs


def _sport_candidates(
    observations: tuple[Observation, ...], sport: Sport
) -> tuple[Observation, ...]:
    """Return every observation of this sync for ``sport``, in reader order."""
    return tuple(
        observation for observation in observations if observation.sport is sport
    )


def _wellness_weight(
    observations: tuple[Observation, ...], day: date | None
) -> Observation | None:
    """Return the weight of this sync's wellness row for ``day``, if stored."""
    if day is None:
        return None
    record_id = day.isoformat()
    return next(
        (
            observation
            for observation in observations
            if observation.observed_on == day
            and observation.provenance.source_record_id == record_id
        ),
        None,
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


def _synced_instant(snapshot: Mapping[str, Any] | None) -> datetime | None:
    """Return the snapshot's sync instant when it is an aware ISO timestamp."""
    if not snapshot:
        return None
    text = snapshot.get(_SYNCED_AT)
    if not isinstance(text, str):
        return None
    try:
        instant = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return instant if instant.utcoffset() is not None else None
