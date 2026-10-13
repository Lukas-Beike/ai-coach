"""Canonical body weight and body-fat inputs read through the observation port.

The ``body_weight_kg_series`` and ``body_fat_pct_series`` consumers can switch to
the tables, so both series are read here.

Reads are served only while the canonical tables serve reads (see
``CanonicalTableServing``). Otherwise ``read_body_inputs`` returns None and the
caller keeps the legacy values. The legacy projection holds only the compact
wellness rows, so switching without this gate would drop older raw-only days.

``body_history`` overrides only the days this module returns. Days it lacks keep
the legacy value, so a value the canonical mapper does not store is never dropped.

Per provider and day, the last observation inside the legacy plausibility bounds
wins, as the legacy body history does. Intervals athlete-record observations,
whose record id is not the observation's own ISO day, are excluded because the
legacy body history reads wellness rows only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from typing import Any

from backend.canonical.ordering import observation_order
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.runtime.ports import CanonicalTableServing, ObservationReader

WINDOW_DAYS = 84
BODY_FAT_READ_DAYS = WINDOW_DAYS - 1
# The weight quotient looks back 7 days before the chart window.
WEIGHT_READ_DAYS = BODY_FAT_READ_DAYS + 7
WEIGHT_BOUNDS = (30.0, 300.0)
BODY_FAT_BOUNDS = (2.0, 70.0)


@dataclass(frozen=True, slots=True)
class CanonicalBodyInputs:
    """Per-day weight and body-fat values for each provider, bounded and rounded."""

    intervals_weight_kg: dict[date, float]
    intervals_body_fat_pct: dict[date, float]
    garmin_weight_kg: dict[date, float]
    garmin_body_fat_pct: dict[date, float]


def read_body_inputs(
    reader: ObservationReader,
    serving: CanonicalTableServing,
    db: Any,
    today: date,
) -> CanonicalBodyInputs | None:
    """Read weight and body fat up to ``today``, or None while legacy serves reads."""
    if not serving.serves_tables(db):
        return None
    weights = reader.observations(
        db,
        MetricKind.WEIGHT,
        start=today - timedelta(days=WEIGHT_READ_DAYS),
        end=today,
    )
    body_fat = reader.observations(
        db,
        MetricKind.BODY_FAT,
        start=today - timedelta(days=BODY_FAT_READ_DAYS),
        end=today,
    )
    return CanonicalBodyInputs(
        intervals_weight_kg=_daily(weights, ProviderId.INTERVALS, today, WEIGHT_BOUNDS),
        intervals_body_fat_pct=_daily(
            body_fat, ProviderId.INTERVALS, today, BODY_FAT_BOUNDS
        ),
        garmin_weight_kg=_daily(weights, ProviderId.GARMIN, today, WEIGHT_BOUNDS),
        garmin_body_fat_pct=_daily(body_fat, ProviderId.GARMIN, today, BODY_FAT_BOUNDS),
    )


def _daily(
    observations: Sequence[Observation],
    provider: ProviderId,
    today: date,
    bounds: tuple[float, float],
) -> dict[date, float]:
    lower, upper = bounds
    days: dict[date, float] = {}
    for observation in sorted(observations, key=_recency_key):
        if observation.provenance.provider is not provider:
            continue
        if observation.observed_on > today or _athlete_level(observation):
            continue
        value = float(observation.value.value)
        if lower <= value <= upper:
            days[observation.observed_on] = round(value, 2)
    return days


def _recency_key(observation: Observation) -> tuple[Any, ...]:
    """Order readings of one day as the legacy Garmin reader does.

    Untimed readings sort before timed ones. Timed readings compare by UTC instant,
    so mixed offsets order by the moment they describe, not by their text. A naive
    timestamp is read as UTC, as the legacy reader does. Ties keep the canonical
    order.
    """
    at = observation.observed_at
    if at is None:
        return (observation.observed_on, False, 0.0, observation_order(observation))
    aware = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    return (
        observation.observed_on,
        True,
        aware.timestamp(),
        observation_order(observation),
    )


def _athlete_level(observation: Observation) -> bool:
    """Return True for Intervals athlete-record values, which body history skips."""
    if observation.provenance.provider is not ProviderId.INTERVALS:
        return False
    return (
        observation.provenance.source_record_id != observation.observed_on.isoformat()
    )
