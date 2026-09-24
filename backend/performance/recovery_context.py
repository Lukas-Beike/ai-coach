"""Pure recovery context projections."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.performance import garmin_metrics, recovery, wellness

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
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _garmin_sleep_recovery(
    garmin: dict[str, Any], latest_wellness: dict[str, Any], today: date
) -> dict[str, Any] | None:
    sleep_seconds, _ = recovery.garmin_recovery_metric(
        garmin, "sleep", ("sleepTimeSeconds", "sleepDuration")
    )
    sleep_score, _ = recovery.garmin_recovery_metric(
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
        ("sleepTimeSeconds", "sleepDuration"),
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
        sleep_score
        if sleep_score is not None
        else _first_present(latest_wellness, ("sleepScore",))
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
) -> dict[str, Any]:
    sleep_seconds = _first_present(latest_wellness, ("sleepSecs",))
    try:
        sleep_hours = (
            round(float(sleep_seconds) / 3600, 1) if sleep_seconds is not None else None
        )
    except (TypeError, ValueError):
        sleep_hours = None
    sleep_average = wellness.wellness_average(
        wellness_rows, ("sleepSecs", "sleep_seconds"), 7, today, 3600
    )
    if sleep_average is None:
        sleep_average = wellness.wellness_average(
            wellness_rows, ("sleep_hours",), 7, today
        )
    sleep_score = _first_present(latest_wellness, ("sleepScore",))
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
) -> dict[str, Any]:
    garmin_recovery = _garmin_sleep_recovery(garmin, latest_wellness, today)
    if garmin_recovery is not None:
        return garmin_recovery
    return _intervals_sleep_recovery(latest_wellness, wellness_rows, today)


def _performance_recovery_metric(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    section: str,
    keys: tuple[str, ...],
    fallback_keys: tuple[str, ...],
    transform: Callable[[Any], Any],
    today: date,
) -> tuple[Any, str | None, Any, str | None]:
    current, observed_date = recovery.garmin_recovery_metric(
        garmin, section, keys, transform
    )
    if current is not None:
        average = recovery.garmin_recovery_average(
            garmin, section, keys, 7, today, transform
        )
        return (
            current,
            garmin_metrics.GARMIN_PERFORMANCE_SOURCE,
            average,
            observed_date,
        )
    fallback = _first_present(latest_wellness, fallback_keys)
    average = wellness.wellness_average(wellness_rows, fallback_keys, 7, today)
    source = INTERVALS_WELLNESS_SOURCE if fallback is not None else None
    return fallback, source, average, None


def _performance_readiness(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    today: date,
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
    if current is None:
        current = wellness.readiness_score_value(garmin.get("readiness"))
        source = (
            garmin_metrics.GARMIN_PERFORMANCE_SOURCE if current is not None else None
        )
    average = wellness.wellness_average(wellness_rows, readiness_keys, 7, today)
    return current, source, average


def performance_recovery_context(
    garmin: dict[str, Any],
    latest_wellness: dict[str, Any],
    wellness_rows: list[dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    sleep = _performance_sleep_recovery(garmin, latest_wellness, wellness_rows, today)
    resting_hr, resting_hr_source, resting_hr_average, resting_hr_date = (
        _performance_recovery_metric(
            garmin,
            latest_wellness,
            wellness_rows,
            "resting_hr",
            ("restingHeartRate", "restingHR", "resting_heart_rate"),
            ("restingHR", "resting_hr"),
            lambda value: garmin_metrics.garmin_bounded_metric(value, 30, 230),
            today,
        )
    )
    hrv, hrv_source, hrv_average, hrv_date = _performance_recovery_metric(
        garmin,
        latest_wellness,
        wellness_rows,
        "hrv",
        ("hrvLastNight", "lastNightAvg", "hrvWeeklyAvg", "weeklyAvg", "hrv", "hrv_ms"),
        ("hrv", "hrv_ms"),
        lambda value: garmin_metrics.garmin_bounded_metric(value, 1, 300),
        today,
    )
    readiness, readiness_source, readiness_average = _performance_readiness(
        garmin, latest_wellness, wellness_rows, today
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
