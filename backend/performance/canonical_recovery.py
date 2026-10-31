"""Canonical recovery observations: the only input of the recovery reads.

The current recovery context (``recovery_context``) and the personal recovery
baselines (``personal_recovery``) read sleep, resting HR, HRV and readiness from
these observations only; neither reads raw provider views for them.

All recovery kinds are read once per unit of work, from all providers, from
``RECOVERY_HISTORY_DAYS - 1`` days before ``as_of`` without an end bound, because
Garmin records may be newer than the latest wellness row. The latest wellness day
pins the Intervals values of ``select_current`` to the newest wellness row, as
the legacy readers did; it is None when there is no usable wellness day, and
Garmin values are still selected then.

Sleep periods for the sleep timing variability are read when the serving source
stores them (``SleepPeriodReader``), one day before the window so a period dated
in another zone is not missed; the timing variability applies its own window. A
source without them leaves ``sleep_periods`` None, and the timing variability has
no data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.domain_records import SleepPeriod
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.source_policy import select_current, within_current_bounds
from backend.runtime.ports import ObservationReader, SleepPeriodReader

# The personal baselines keep 84 days of history; the current context needs 7.
RECOVERY_HISTORY_DAYS: Final = 84

RECOVERY_KINDS: Final = (
    MetricKind.SLEEP_DURATION,
    MetricKind.SLEEP_SCORE,
    MetricKind.RESTING_HR,
    MetricKind.HRV_RMSSD,
    MetricKind.HRV_SDNN,
    MetricKind.HRV_WEEKLY_AVERAGE,
    MetricKind.READINESS,
)


@dataclass(frozen=True, slots=True)
class CanonicalRecoveryInputs:
    """Recovery observations of all providers by kind, and the latest wellness day.

    ``sleep_periods`` is None when the serving source stores no sleep periods.
    """

    observations: Mapping[MetricKind, tuple[Observation, ...]]
    latest_wellness_day: date | None
    sleep_periods: tuple[SleepPeriod, ...] | None = None

    def of(self, kind: MetricKind) -> tuple[Observation, ...]:
        """Return the observations of ``kind``; empty when it was not read."""
        return self.observations.get(kind, ())

    def current(self, kind: MetricKind) -> Observation | None:
        """Return the current observation of ``kind`` under its source rule."""
        return select_current(
            self.of(kind), kind, latest_wellness_day=self.latest_wellness_day
        )

    def daily(
        self, kind: MetricKind, provider: ProviderId, *, bounded: bool = False
    ) -> dict[date, float]:
        """Return one value per day of ``provider``; the first input record wins.

        ``bounded`` skips values outside the kind's current-rule bounds first.
        """
        return first_per_day(
            observation
            for observation in self.of(kind)
            if observation.provenance.provider is provider
            and (not bounded or within_current_bounds(observation))
        )


def read_recovery_inputs(
    reader: ObservationReader,
    db: Any,
    *,
    as_of: date,
    latest_wellness_day: date | None,
) -> CanonicalRecoveryInputs:
    """Read every recovery kind once; ``reader`` must already be resolved."""
    start = as_of - timedelta(days=RECOVERY_HISTORY_DAYS - 1)
    return CanonicalRecoveryInputs(
        observations={
            kind: tuple(reader.observations(db, kind, start=start))
            for kind in RECOVERY_KINDS
        },
        latest_wellness_day=latest_wellness_day,
        sleep_periods=(
            reader.sleep_periods(db, start=start - timedelta(days=1))
            if isinstance(reader, SleepPeriodReader)
            else None
        ),
    )


def first_per_day(observations: Iterable[Observation]) -> dict[date, float]:
    """Return the value of the first observation of each day."""
    values: dict[date, float] = {}
    for observation in observations:
        values.setdefault(observation.observed_on, float(observation.value.value))
    return values
