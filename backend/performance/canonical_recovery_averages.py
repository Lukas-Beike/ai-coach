"""Canonical 7-day recovery averages: resting HR and readiness.

The legacy averages average the per-day values of the seven days ending on the
performance day. The resting HR average comes from Garmin when the legacy current
resting HR is a Garmin value, and from Intervals wellness rows otherwise. The
readiness average always comes from Intervals wellness rows.

This module offers the canonical per-day observations of the same provider for the
same window. The canonical average replaces the legacy average only when it covers
exactly the same days and equals it after the legacy rounding. Otherwise the legacy
average is returned. Sleep and HRV averages do not come through here.

The observations are read from the snapshot's earliest wellness day without an end
bound. Days of the window that were not read make the day sets differ, so the
legacy average is kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.recovery import AVERAGE_DAYS, rounded_average
from backend.runtime.ports import ObservationReader


@dataclass(frozen=True, slots=True)
class CanonicalRecoveryAverageInputs:
    """Canonical resting HR and readiness observations of all providers from one start."""

    resting_hr: tuple[Observation, ...]
    readiness: tuple[Observation, ...]


def read_recovery_average_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    start: date,
) -> CanonicalRecoveryAverageInputs:
    """Read both kinds once from ``start``; ``reader`` must already be resolved."""
    return CanonicalRecoveryAverageInputs(
        resting_hr=tuple(reader.observations(db, MetricKind.RESTING_HR, start=start)),
        readiness=tuple(reader.observations(db, MetricKind.READINESS, start=start)),
    )


def prefer_canonical_average(
    legacy_values: Sequence[tuple[date, float]],
    observations: Sequence[Observation] | None,
    provider: ProviderId,
    end: date,
) -> float | None:
    """Return the 7-day average, canonical only when it matches the legacy window.

    ``legacy_values`` are the dated numbers the legacy average was taken from.
    ``observations`` of None means the canonical inputs were not read.
    """
    legacy_average = rounded_average([value for _, value in legacy_values])
    if observations is None:
        return legacy_average
    canonical_values = _window_values(observations, provider, end)
    if {day for day, _ in canonical_values} != {day for day, _ in legacy_values}:
        return legacy_average
    canonical_average = rounded_average([value for _, value in canonical_values])
    if canonical_average != legacy_average:
        return legacy_average
    return canonical_average


def _window_values(
    observations: Sequence[Observation], provider: ProviderId, end: date
) -> list[tuple[date, float]]:
    """Return the first observation of each day of one provider in the window."""
    cutoff = end - timedelta(days=AVERAGE_DAYS - 1)
    first_by_day: dict[date, Observation] = {}
    for observation in observations:
        if observation.provenance.provider is provider:
            first_by_day.setdefault(observation.observed_on, observation)
    return [
        (day, float(observation.value.value))
        for day, observation in sorted(first_by_day.items())
        if cutoff <= day <= end
    ]
