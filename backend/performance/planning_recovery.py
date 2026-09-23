"""Date-indexed recovery values used by the planning context."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from backend.performance import recovery as performance_recovery
from backend.performance import wellness as performance_wellness

GARMIN_SOURCE = "Garmin Connect"
INTERVALS_WELLNESS_SOURCE = "Intervals.icu Wellness"
UTC_OFFSET_SUFFIX = "+00:00"


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


def _planning_context_date(value: Any) -> str:
    raw = str(value or "").replace("Z", UTC_OFFSET_SUFFIX)[:10]
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return ""


def _add_planning_recovery_value(
    recovery: dict[str, Any],
    metric_name: str,
    value: Any,
    source: str,
    *,
    overwrite: bool = False,
) -> None:
    if value in (None, "") or (metric_name in recovery and not overwrite):
        return
    recovery[metric_name] = value
    recovery.setdefault("sources", {})[metric_name] = source


def _planning_sleep_hours(
    record: dict[str, Any], seconds_fields: tuple[str, ...]
) -> float | None:
    sleep_hours = _as_number(record.get("sleep_hours"))
    sleep_seconds = _first_present(record, seconds_fields)
    if sleep_hours is not None or sleep_seconds in (None, ""):
        return sleep_hours
    try:
        return round(float(sleep_seconds) / 3600, 1)
    except (TypeError, ValueError):
        return None


def _add_intervals_planning_recovery(
    recovery_by_date: dict[str, dict[str, Any]], rows: Any
) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        record_date = _planning_context_date(
            _first_present(row, ("id", "date", "calendarDate"))
        )
        if not record_date:
            continue
        recovery = recovery_by_date.setdefault(record_date, {})
        _add_planning_recovery_value(
            recovery,
            "sleep_hours",
            _planning_sleep_hours(row, ("sleepSecs", "sleep_seconds")),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "sleep_score",
            _first_present(row, ("sleepScore", "overallSleepScore")),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "hrv",
            _first_present(row, ("hrv", "hrv_ms")),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "readiness",
            performance_wellness.readiness_score_value(
                _first_present(
                    row,
                    (
                        "readiness",
                        "readinessScore",
                        "readiness_score",
                        "trainingReadiness",
                        "training_readiness",
                    ),
                )
            ),
            INTERVALS_WELLNESS_SOURCE,
        )
        _add_planning_recovery_value(
            recovery,
            "resting_hr",
            _first_present(row, ("restingHR", "resting_hr")),
            INTERVALS_WELLNESS_SOURCE,
        )
        for metric_name, keys in (
            ("ctl", ("ctl", "ctLoad")),
            ("atl", ("atl", "atlLoad")),
            ("tsb", ("tsb", "form")),
        ):
            _add_planning_recovery_value(
                recovery,
                metric_name,
                _first_present(row, keys),
                INTERVALS_WELLNESS_SOURCE,
            )


def _add_garmin_planning_recovery_record(
    recovery: dict[str, Any], section: str, record: dict[str, Any]
) -> None:
    if section == "sleep":
        _add_planning_recovery_value(
            recovery,
            "sleep_hours",
            _planning_sleep_hours(record, ("sleepTimeSeconds", "sleepDuration")),
            GARMIN_SOURCE,
            overwrite=True,
        )
        _add_planning_recovery_value(
            recovery,
            "sleep_score",
            _first_present(record, ("sleepScore", "overallSleepScore")),
            GARMIN_SOURCE,
            overwrite=True,
        )
    elif section == "hrv":
        _add_planning_recovery_value(
            recovery,
            "hrv",
            _first_present(
                record, ("hrvLastNight", "lastNightAvg", "hrvWeeklyAvg", "weeklyAvg")
            ),
            GARMIN_SOURCE,
            overwrite=True,
        )
    elif section == "resting_hr":
        _add_planning_recovery_value(
            recovery,
            "resting_hr",
            _first_present(
                record, ("restingHeartRate", "restingHR", "resting_heart_rate")
            ),
            GARMIN_SOURCE,
            overwrite=True,
        )
    else:
        _add_planning_recovery_value(
            recovery,
            "readiness",
            performance_wellness.readiness_score_value(
                _first_present(
                    record,
                    (
                        "trainingReadinessScore",
                        "overallReadinessScore",
                        "readinessScore",
                        "score",
                        "trainingReadiness",
                    ),
                )
            ),
            GARMIN_SOURCE,
        )


def _add_garmin_planning_recovery(
    recovery_by_date: dict[str, dict[str, Any]], garmin: Any
) -> None:
    if not isinstance(garmin, dict):
        return
    for section in ("sleep", "hrv", "resting_hr", "readiness"):
        for record_date, record in performance_recovery.dated_garmin_recovery_records(
            garmin.get(section)
        ):
            _add_garmin_planning_recovery_record(
                recovery_by_date.setdefault(record_date, {}), section, record
            )


def _add_morning_battery_recovery(
    recovery_by_date: dict[str, dict[str, Any]],
    morning_battery_history: Any,
    morning_body_battery: Any,
) -> None:
    if isinstance(morning_battery_history, dict):
        for day, value in morning_battery_history.items():
            record_date = _planning_context_date(day)
            if record_date and _as_number(value) is not None:
                _add_planning_recovery_value(
                    recovery_by_date.setdefault(record_date, {}),
                    "body_battery",
                    value,
                    GARMIN_SOURCE,
                )
    if (
        isinstance(morning_body_battery, dict)
        and morning_body_battery.get("status") == "ready"
    ):
        record_date = _planning_context_date(morning_body_battery.get("sleep_date"))
        morning = morning_body_battery.get("morning")
        if record_date and isinstance(morning, dict):
            _add_planning_recovery_value(
                recovery_by_date.setdefault(record_date, {}),
                "body_battery",
                morning.get("value"),
                GARMIN_SOURCE,
                overwrite=True,
            )


def planning_recovery_by_date(
    wellness_rows: Any,
    garmin: Any,
    morning_battery_history: Any,
    morning_body_battery: Any,
) -> dict[str, dict[str, Any]]:
    """Build a date-indexed recovery view from already loaded provider data."""
    recovery_by_date: dict[str, dict[str, Any]] = {}
    _add_intervals_planning_recovery(recovery_by_date, wellness_rows)
    _add_garmin_planning_recovery(recovery_by_date, garmin)
    _add_morning_battery_recovery(
        recovery_by_date, morning_battery_history, morning_body_battery
    )
    return recovery_by_date
