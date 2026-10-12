"""Canonical current metrics: Intervals sport thresholds and VO2max from one sync.

The Intervals snapshot is projected into canonical observations dated on the
athlete-local sync day and stamped with the snapshot's sync instant. The read
therefore keeps only Intervals rows whose ``retrieved_at`` equals the snapshot's
``synced_at`` instant, within the UTC sync day and one day either side (the
athlete-local day always lies inside that window). Rows from older syncs stay in
the tables and never change the current values.

``select_current`` requires a sport for sport-scoped kinds, so the athlete-wide
threshold heart rate, which carries no sport, is taken directly from this sync's
sport-less rows.

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
from backend.performance.source_policy import select_current
from backend.runtime.ports import ObservationReader

_SYNCED_AT: Final = "synced_at"


@dataclass(frozen=True, slots=True)
class CanonicalCurrentInputs:
    """The Intervals observations of one sync; None where that sync stored none."""

    bike_threshold_hr: Observation | None
    run_threshold_hr: Observation | None
    athlete_threshold_hr: Observation | None
    cycling_vo2max: Observation | None
    running_vo2max: Observation | None
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
        bike_threshold_hr=select_current(
            thresholds, MetricKind.THRESHOLD_HR, sport=Sport.RIDE
        ),
        run_threshold_hr=select_current(
            thresholds, MetricKind.THRESHOLD_HR, sport=Sport.RUN
        ),
        athlete_threshold_hr=_athlete_observation(thresholds),
        cycling_vo2max=select_current(vo2max, MetricKind.VO2MAX, sport=Sport.RIDE),
        running_vo2max=select_current(vo2max, MetricKind.VO2MAX, sport=Sport.RUN),
        wellness_weight=_wellness_weight(weights, latest_wellness_day),
        athlete_weight=_athlete_weight(weights),
    )
    values = (
        inputs.bike_threshold_hr,
        inputs.run_threshold_hr,
        inputs.athlete_threshold_hr,
        inputs.cycling_vo2max,
        inputs.running_vo2max,
        inputs.wellness_weight,
        inputs.athlete_weight,
    )
    if all(value is None for value in values):
        return None
    return inputs


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
