"""Stored daily body observations of the body history and its charts.

They are history only; no current value or precedence reads them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.runtime.ports import ObservationReader

WELLNESS_KINDS: Final = (
    MetricKind.WEIGHT,
    MetricKind.BODY_FAT,
    MetricKind.RESTING_HR,
    MetricKind.HRV_RMSSD,
    MetricKind.HRV_SDNN,
    MetricKind.SLEEP_DURATION,
    MetricKind.SLEEP_SCORE,
    MetricKind.READINESS,
    MetricKind.VO2MAX,
)


@dataclass(frozen=True, slots=True)
class WellnessDay:
    """A calendar day and its source-preserving canonical observations."""

    day: date
    observations: Mapping[MetricKind, Observation]

    def value(self, kind: MetricKind) -> float | None:
        """Return the value, integral numbers as ``int`` like the former rows."""
        observation = self.observations.get(kind)
        if observation is None:
            return None
        number = float(observation.value.value)
        return int(number) if number.is_integer() else number


def _is_wellness_record(observation: Observation) -> bool:
    provenance = observation.provenance
    return (
        provenance.provider is ProviderId.INTERVALS
        and provenance.source_record_id == observation.observed_on.isoformat()
    )


def _is_wellness_day(observation: Observation) -> bool:
    return observation.sport is None and _is_wellness_record(observation)


def read_wellness_days(reader: ObservationReader, db: Any) -> tuple[WellnessDay, ...]:
    """Read each wellness kind once and group unscoped Intervals days in order."""
    by_day: dict[date, dict[MetricKind, Observation]] = {}
    for kind in WELLNESS_KINDS:
        for observation in reader.observations(db, kind):
            if _is_wellness_day(observation):
                by_day.setdefault(observation.observed_on, {})[kind] = observation
    return tuple(WellnessDay(day, by_day[day]) for day in sorted(by_day))
