"""Provider-neutral daily wellness observations for performance readers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.runtime.ports import ObservationReader

WELLNESS_WINDOW_DAYS: Final = 90
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
    MetricKind.CTL,
    MetricKind.ATL,
    MetricKind.SUBJECTIVE_FATIGUE,
    MetricKind.SUBJECTIVE_SORENESS,
    MetricKind.SUBJECTIVE_STRESS,
    MetricKind.SUBJECTIVE_MOOD,
    MetricKind.FORM,
)


@dataclass(frozen=True, slots=True)
class WellnessDay:
    """A calendar day and its source-preserving canonical observations."""

    day: date
    observations: Mapping[MetricKind, Observation]

    def value(self, kind: MetricKind) -> float | None:
        observation = self.observations.get(kind)
        return None if observation is None else observation.value.value


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


def current_window(days: Sequence[WellnessDay]) -> tuple[WellnessDay, ...]:
    """Keep the 90 calendar days ending on the latest stored day."""
    if not days:
        return ()
    end = max(day.day for day in days)
    start = end - timedelta(days=WELLNESS_WINDOW_DAYS - 1)
    return tuple(day for day in days if start <= day.day <= end)


def latest(days: Sequence[WellnessDay]) -> WellnessDay | None:
    """Return the latest day, or None for an empty view."""
    return max(days, key=lambda item: item.day, default=None)


def series(days: Iterable[WellnessDay], kind: MetricKind) -> dict[date, float]:
    """Return observed values of one kind by day, preserving sparse dates."""
    return {day.day: value for day in days if (value := day.value(kind)) is not None}


def wellness_day_values(
    observations: Iterable[Observation], *, sport: Sport | None = None
) -> dict[date, float]:
    """Read one sport scope of Intervals wellness-day observations by date."""
    return {
        observation.observed_on: observation.value.value
        for observation in observations
        if observation.sport is sport and _is_wellness_record(observation)
    }
