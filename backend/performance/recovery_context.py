"""Current recovery values from canonical observations.

Each value is the ``select_current`` observation of its kind: Garmin before
Intervals.icu for sleep, resting HR and HRV, Intervals.icu before Garmin for
readiness, with the source rules' bounds and latest-wellness-row restriction. The
7-day averages use only the selected provider's daily values within the same
bounds; a metric without a selected value averages the Intervals.icu days. Garmin values carry their
observation day; Intervals.icu values carry none, as the recovery id then falls
back to the latest wellness row.

A Garmin weekly HRV average is shown only when no last-night RMSSD is selected,
with its own source label and without an average.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance import garmin_metrics
from backend.performance.canonical_recovery import CanonicalRecoveryInputs
from backend.performance.recovery import AVERAGE_DAYS, rounded_average

INTERVALS_WELLNESS_SOURCE = "Intervals.icu Wellness"
GARMIN_WEEKLY_HRV_SOURCE: Final = (
    f"{garmin_metrics.GARMIN_PERFORMANCE_SOURCE} (Wochenmittel)"
)
_SECONDS_PER_HOUR: Final = 3600

_SOURCES: Final = {
    ProviderId.GARMIN: garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
    ProviderId.INTERVALS: INTERVALS_WELLNESS_SOURCE,
}


def _number(observation: Observation, scale: float = 1) -> float | int:
    """Return the stored value, as an int when it is whole and unscaled."""
    value = observation.value.value
    if scale != 1:
        return value / scale
    return int(value) if float(value).is_integer() else value


def _source(observation: Observation | None) -> str | None:
    if observation is None:
        return None
    provider = observation.provenance.provider
    return None if provider is None else _SOURCES.get(provider)


def _date(observation: Observation | None) -> str | None:
    """Return the Garmin observation day; Intervals values carry no own date."""
    if observation is None or observation.provenance.provider is not ProviderId.GARMIN:
        return None
    return observation.observed_on.isoformat()


def _average(
    recovery: CanonicalRecoveryInputs,
    kind: MetricKind,
    selected: Observation | None,
    today: date,
    scale: float = 1,
) -> float | None:
    """Average the selected provider's (else Intervals') days ending on ``today``."""
    provider = (
        ProviderId.INTERVALS
        if selected is None or selected.provenance.provider is None
        else selected.provenance.provider
    )
    cutoff = today - timedelta(days=AVERAGE_DAYS - 1)
    return rounded_average(
        [
            value / scale
            for day, value in recovery.daily(kind, provider, bounded=True).items()
            if cutoff <= day <= today
        ]
    )


def _metric(
    recovery: CanonicalRecoveryInputs, kind: MetricKind, today: date
) -> tuple[Any, str | None, float | None, str | None]:
    """Return the current value, source, 7-day average and Garmin day of ``kind``."""
    current = recovery.current(kind)
    return (
        None if current is None else _number(current),
        _source(current),
        _average(recovery, kind, current, today),
        _date(current),
    )


def _sleep(recovery: CanonicalRecoveryInputs, today: date) -> dict[str, Any]:
    duration = recovery.current(MetricKind.SLEEP_DURATION)
    score, score_source, _, _ = _metric(recovery, MetricKind.SLEEP_SCORE, today)
    return {
        "sleep_hours": (
            None if duration is None else round(_number(duration, _SECONDS_PER_HOUR), 1)
        ),
        "sleep_source": _source(duration),
        "sleep_average": _average(
            recovery, MetricKind.SLEEP_DURATION, duration, today, _SECONDS_PER_HOUR
        ),
        "sleep_score": score,
        "sleep_score_source": score_source,
        "sleep_date": _date(duration),
    }


def _hrv(
    recovery: CanonicalRecoveryInputs, today: date
) -> tuple[Any, str | None, float | None, str | None]:
    """Return last-night RMSSD, else Garmin's weekly average without an average."""
    rmssd = _metric(recovery, MetricKind.HRV_RMSSD, today)
    if rmssd[0] is not None:
        return rmssd
    weekly = recovery.current(MetricKind.HRV_WEEKLY_AVERAGE)
    if weekly is None:
        return rmssd
    return _number(weekly), GARMIN_WEEKLY_HRV_SOURCE, None, _date(weekly)


def performance_recovery_context(
    recovery: CanonicalRecoveryInputs | None, today: date
) -> dict[str, Any]:
    """Return the current recovery values; all None without canonical inputs."""
    if recovery is None:
        recovery = CanonicalRecoveryInputs(observations={}, latest_wellness_day=None)
    resting_hr, resting_hr_source, resting_hr_average, resting_hr_date = _metric(
        recovery, MetricKind.RESTING_HR, today
    )
    hrv, hrv_source, hrv_average, hrv_date = _hrv(recovery, today)
    readiness, readiness_source, readiness_average, _ = _metric(
        recovery, MetricKind.READINESS, today
    )
    return {
        **_sleep(recovery, today),
        "resting_hr": resting_hr,
        "resting_hr_source": resting_hr_source,
        "resting_hr_average": resting_hr_average,
        "resting_hr_date": resting_hr_date,
        "hrv": hrv,
        "hrv_source": hrv_source,
        "hrv_average": hrv_average,
        "hrv_date": hrv_date,
        "readiness": readiness,
        "readiness_source": readiness_source,
        "readiness_average": readiness_average,
    }
