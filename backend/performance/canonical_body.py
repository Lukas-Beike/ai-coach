"""Canonical body-fat history inputs read through the observation port.

Only body fat is read here. Weight stays on the legacy readers because the
consumer parity ledger records a comma-decimal Intervals weight ("80,4") that the
canonical mapper does not produce. Reading canonical weight would drop that day
from the chart, so ``body_weight_kg_series`` is not switched.

``body_history`` overrides only the days this module returns; days it lacks keep
the legacy value, so a value the mapper does not store is never dropped.

Reads are served only while the canonical tables serve reads (see
``CanonicalTableServing``). Otherwise ``read_body_inputs`` returns None and the
caller keeps the legacy values. The legacy projection holds only the compact
wellness rows, so switching without this gate would drop older raw-only days.

Per provider and day, the last observation inside the legacy plausibility bounds
wins, as the consumer parity ledger does. Intervals athlete-record observations,
whose record id is not the observation's own ISO day, are excluded because the
legacy body history reads wellness rows only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.canonical.ordering import observation_order
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.runtime.ports import CanonicalTableServing, ObservationReader

WINDOW_DAYS = 84
READ_DAYS = WINDOW_DAYS - 1
BODY_FAT_BOUNDS = (2.0, 70.0)


@dataclass(frozen=True, slots=True)
class CanonicalBodyInputs:
    """Per-day body-fat values for each provider, bounded and rounded."""

    intervals_body_fat_pct: dict[date, float]
    garmin_body_fat_pct: dict[date, float]


def read_body_inputs(
    reader: ObservationReader,
    serving: CanonicalTableServing,
    db: Any,
    today: date,
) -> CanonicalBodyInputs | None:
    """Read body-fat values up to ``today``, or None while legacy serves reads."""
    if not serving.serves_tables(db):
        return None
    observations = reader.observations(
        db,
        MetricKind.BODY_FAT,
        start=today - timedelta(days=READ_DAYS),
        end=today,
    )
    return CanonicalBodyInputs(
        intervals_body_fat_pct=_daily(observations, ProviderId.INTERVALS, today),
        garmin_body_fat_pct=_daily(observations, ProviderId.GARMIN, today),
    )


def _daily(
    observations: Sequence[Observation], provider: ProviderId, today: date
) -> dict[date, float]:
    lower, upper = BODY_FAT_BOUNDS
    days: dict[date, float] = {}
    for observation in sorted(observations, key=observation_order):
        if observation.provenance.provider is not provider:
            continue
        if observation.observed_on > today or _athlete_level(observation):
            continue
        value = float(observation.value.value)
        if lower <= value <= upper:
            days[observation.observed_on] = round(value, 2)
    return days


def _athlete_level(observation: Observation) -> bool:
    """Return True for Intervals athlete-record values, which body history skips."""
    if observation.provenance.provider is not ProviderId.INTERVALS:
        return False
    return (
        observation.provenance.source_record_id != observation.observed_on.isoformat()
    )
