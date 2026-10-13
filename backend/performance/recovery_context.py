"""Pure recovery context projections."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from backend.canonical.decimal_text import comma_decimal_float
from backend.canonical.records import Observation
from backend.canonical.vocabulary import ProviderId
from backend.performance import garmin_metrics, recovery, wellness
from backend.performance.canonical_recovery import (
    CanonicalRecoveryInputs,
    prefer_canonical,
)
from backend.performance.canonical_recovery_averages import (
    CanonicalRecoveryAverageInputs,
    prefer_canonical_average,
)
from backend.providers import garmin_performance_fields as garmin_perf_fields
from backend.providers.garmin_fields import GARMIN_RESTING_HR_ALIASES

INTERVALS_WELLNESS_SOURCE = "Intervals.icu Wellness"


def _first_present(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return None
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_number(value: Any) -> float | int | None:
    try:
        number = comma_decimal_float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _garmin_sleep_recovery(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    today: date,
    sleep_observed: Observation | None = None,
) -> dict[str, Any] | None:
    sleep_seconds, _ = recovery.garmin_recovery_metric(
        garmin, "sleep", garmin_perf_fields.SLEEP_DURATION_ALIASES
    )
    sleep_score, sleep_score_date = recovery.garmin_recovery_metric(
        garmin,
        "sleep",
        ("sleepScore", "overallSleepScore"),
        lambda value: garmin_metrics.garmin_bounded_metric(value, 0, 100),
    )
    sleep_hours, sleep_date = recovery.garmin_recovery_metric(
        garmin, "sleep", ("sleep_hours",), _as_number
    )
    if sleep_hours is None and sleep_seconds is not None:
        sleep_hours = round(float(sleep_seconds) / 3600, 1)
    if sleep_hours is None:
        return None
    sleep_average = recovery.garmin_recovery_average(
        garmin,
        "sleep",
        garmin_perf_fields.SLEEP_DURATION_ALIASES,
        7,
        today,
        lambda value: (
            round(float(value) / 3600, 1) if _as_number(value) is not None else None
        ),
    )
    if sleep_average is None:
        sleep_average = recovery.garmin_recovery_average(
            garmin, "sleep", ("sleep_hours",), 7, today
        )
    resolved_score = (
        prefer_canonical(
            sleep_observed, sleep_score, ProviderId.GARMIN, sleep_score_date
        )
        if sleep_score is not None
        else prefer_canonical(
            sleep_observed,
            _first_present(latest_wellness, ("sleepScore",)),
            ProviderId.INTERVALS,
            latest_wellness.get("id"),
        )
    )
    if sleep_score is not None:
        sleep_score_source = garmin_metrics.GARMIN_PERFORMANCE_SOURCE
    elif resolved_score is not None:
        sleep_score_source = INTERVALS_WELLNESS_SOURCE
    else:
        sleep_score_source = None
    return {
        "sleep_hours": sleep_hours,
        "sleep_source": garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
        "sleep_average": sleep_average,
        "sleep_score": resolved_score,
        "sleep_score_source": sleep_score_source,
        "sleep_date": sleep_date,
    }


def _intervals_sleep_recovery(
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    today: date,
    sleep_observed: Observation | None = None,
) -> dict[str, Any]:
    sleep_seconds = _first_present(latest_wellness, ("sleepSecs",))
    try:
        sleep_hours = (
            round(float(sleep_seconds) / 3600, 1) if sleep_seconds is not None else None
        )
    except TypeError, ValueError:
        sleep_hours = None
    sleep_average = wellness.wellness_average(
        wellness_rows, ("sleepSecs", "sleep_seconds"), 7, today, 3600
    )
    if sleep_average is None:
        sleep_average = wellness.wellness_average(
            wellness_rows, ("sleep_hours",), 7, today
        )
    sleep_score = prefer_canonical(
        sleep_observed,
        _first_present(latest_wellness, ("sleepScore",)),
        ProviderId.INTERVALS,
        latest_wellness.get("id"),
    )
    return {
        "sleep_hours": sleep_hours,
        "sleep_source": (
            INTERVALS_WELLNESS_SOURCE if sleep_hours is not None else None
        ),
        "sleep_average": sleep_average,
        "sleep_score": sleep_score,
        "sleep_score_source": (
            INTERVALS_WELLNESS_SOURCE if sleep_score is not None else None
        ),
        "sleep_date": None,
    }


def _performance_sleep_recovery(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    today: date,
    sleep_observed: Observation | None = None,
) -> dict[str, Any]:
    garmin_recovery = _garmin_sleep_recovery(
        garmin, latest_wellness, today, sleep_observed
    )
    if garmin_recovery is not None:
        return garmin_recovery
    return _intervals_sleep_recovery(
        latest_wellness, wellness_rows, today, sleep_observed
    )


def _performance_recovery_metric(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    section: str,
    keys: tuple[str, ...],
    fallback_keys: tuple[str, ...],
    transform: Callable[[Any], Any],
    today: date,
    observed: Observation | None = None,
    average_observations: Sequence[Observation] | None = None,
) -> tuple[Any, str | None, Any, str | None]:
    current, observed_date = recovery.garmin_recovery_metric(
        garmin, section, keys, transform
    )
    if current is not None:
        average = prefer_canonical_average(
            recovery.garmin_recovery_window_values(
                garmin, section, keys, recovery.AVERAGE_DAYS, today, transform
            ),
            average_observations,
            ProviderId.GARMIN,
            today,
        )
        return (
            prefer_canonical(observed, current, ProviderId.GARMIN, observed_date),
            garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
            average,
            observed_date,
        )
    fallback = _first_present(latest_wellness, fallback_keys)
    average = prefer_canonical_average(
        wellness.wellness_window_values(
            wellness_rows, fallback_keys, recovery.AVERAGE_DAYS, today
        ),
        average_observations,
        ProviderId.INTERVALS,
        today,
    )
    source = INTERVALS_WELLNESS_SOURCE if fallback is not None else None
    fallback = prefer_canonical(
        observed, fallback, ProviderId.INTERVALS, latest_wellness.get("id")
    )
    return fallback, source, average, None


def _performance_readiness(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    today: date,
    observed: Observation | None = None,
    average_observations: Sequence[Observation] | None = None,
) -> tuple[Any, str | None, Any]:
    readiness_keys = (
        "readiness",
        "readinessScore",
        "readiness_score",
        "trainingReadiness",
        "training_readiness",
    )
    current = wellness.readiness_score_value(
        _first_present(latest_wellness, readiness_keys)
    )
    source = INTERVALS_WELLNESS_SOURCE if current is not None else None
    if current is not None:
        current = prefer_canonical(
            observed, current, ProviderId.INTERVALS, latest_wellness.get("id")
        )
    if current is None:
        current = wellness.readiness_score_value(garmin.get("readiness"))
        source = (
            garmin_metrics.GARMIN_PERFORMANCE_SOURCE if current is not None else None
        )
        current = prefer_canonical(observed, current, ProviderId.GARMIN)
    average = prefer_canonical_average(
        wellness.wellness_window_values(
            wellness_rows, readiness_keys, recovery.AVERAGE_DAYS, today
        ),
        average_observations,
        ProviderId.INTERVALS,
        today,
    )
    return current, source, average


def performance_recovery_context(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    today: date,
    *,
    canonical: CanonicalRecoveryInputs | None = None,
    averages: CanonicalRecoveryAverageInputs | None = None,
) -> dict[str, Any]:
    """Recovery context for the snapshot; ``canonical`` replaces matching values.

    Without ``canonical`` the legacy readers run unchanged. With it, the sleep score,
    resting HR and readiness take the canonical value only when it is the record the
    legacy reader picked. ``averages`` lets the resting HR and readiness 7-day averages
    come from canonical days only when they match the legacy window exactly.
    Everything else stays legacy.
    """
    sleep = _performance_sleep_recovery(
        garmin,
        latest_wellness,
        wellness_rows,
        today,
        None if canonical is None else canonical.sleep_score,
    )
    resting_hr, resting_hr_source, resting_hr_average, resting_hr_date = (
        _performance_recovery_metric(
            garmin,
            latest_wellness,
            wellness_rows,
            "resting_hr",
            GARMIN_RESTING_HR_ALIASES,
            ("restingHR", "resting_hr"),
            lambda value: garmin_metrics.garmin_bounded_metric(value, 30, 230),
            today,
            None if canonical is None else canonical.resting_hr,
            None if averages is None else averages.resting_hr,
        )
    )
    hrv, hrv_source, hrv_average, hrv_date = _performance_recovery_metric(
        garmin,
        latest_wellness,
        wellness_rows,
        "hrv",
        (*garmin_perf_fields.HRV_WITH_WEEKLY_ALIASES, "hrv", "hrv_ms"),
        ("hrv", "hrv_ms"),
        lambda value: garmin_metrics.garmin_bounded_metric(value, 1, 300),
        today,
    )
    readiness, readiness_source, readiness_average = _performance_readiness(
        garmin,
        latest_wellness,
        wellness_rows,
        today,
        None if canonical is None else canonical.readiness,
        None if averages is None else averages.readiness,
    )
    return {
        **sleep,
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
