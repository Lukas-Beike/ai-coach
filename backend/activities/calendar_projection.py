"""Pure projections for completed activities in the calendar."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from backend.activities.identity import activity_datetime
from backend.activities.matching import is_planned_workout_event, match_planned_workouts

CALENDAR_ACTIVITY_FIELDS = (
    "id",
    "external_id",
    "start_date_local",
    "name",
    "type",
    "moving_time",
    "elapsed_time",
    "distance",
    "total_elevation_gain",
    "icu_training_load",
    "icu_intensity",
    "average_heartrate",
    "max_heartrate",
    "average_watts",
    "weighted_average_watts",
    "icu_weighted_avg_watts",
    "normalized_power",
    "icu_weighted_avg_speed",
    "icu_pace",
    "icu_rpe",
    "feel",
    "source",
)


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


def _selected(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in fields if key in item and item[key] is not None}


def activity_metric(record: Any, keys: tuple[str, ...]) -> float | int | None:
    number = _as_number(_first_present(record, keys))
    return number if number is not None and number >= 0 else None


def _record_date(value: Any) -> str:
    parsed = activity_datetime(value)
    return parsed.date().isoformat() if parsed else str(value or "")[:10]


def calendar_activity_payload(activity: Any) -> dict[str, Any]:
    """Return the bounded completed-activity fields used by the calendar UI."""
    if not isinstance(activity, dict):
        return {}
    payload = _selected(activity, CALENDAR_ACTIVITY_FIELDS)
    activity_start = _first_present(
        activity, ("start_date_local", "start_date", "date")
    )
    payload.update(
        {
            "date": _record_date(activity_start),
            "start_date_local": activity_start,
            "category": "ACTIVITY",
            "calendar_entry_type": "completed_activity",
            "is_completed_activity": True,
        }
    )
    return payload


def calendar_activity_identity(activity: Any) -> tuple[Any, ...] | None:
    """Build a stable identity for matching calendar activity projections."""
    if not isinstance(activity, dict):
        return None
    activity_id = _first_present(activity, ("id", "activityId", "external_id"))
    if activity_id not in (None, ""):
        return ("id", str(activity_id), "", "", "")
    start = _first_present(activity, ("start_date_local", "start_date", "date"))
    if start in (None, ""):
        return None
    return (
        "fallback",
        str(start),
        str(activity.get("type") or activity.get("sport") or "").casefold(),
        activity_metric(activity, ("moving_time", "elapsed_time")),
        activity_metric(activity, ("distance",)),
    )


def _workout_duration(record: Any) -> float | int | None:
    return activity_metric(record, ("moving_time", "elapsed_time"))


def _workout_load(record: Any) -> float | int | None:
    return activity_metric(record, ("icu_training_load", "training_load", "tss"))


def _workout_compliance_basis(
    activity: dict[str, Any] | None,
    planned_load: float | None,
    actual_load: float | None,
    planned_duration: float | None,
    actual_duration: float | None,
) -> tuple[str | None, float | None, float | None]:
    if activity is None:
        return None, None, None
    if planned_load is not None and planned_load > 0 and actual_load is not None:
        return "training_load", planned_load, actual_load
    if (
        planned_duration is not None
        and planned_duration > 0
        and actual_duration is not None
    ):
        return "duration", planned_duration, actual_duration
    if planned_load is None and planned_duration is None:
        return "unavailable", None, None
    return None, None, None


def _workout_compliance_percentage(
    status: str,
    activity: dict[str, Any] | None,
    basis: str | None,
    planned_value: float | None,
    actual_value: float | None,
) -> int | None:
    if status == "missed":
        return 0
    if activity is not None and basis == "unavailable":
        return 100
    if planned_value is not None and actual_value is not None and planned_value > 0:
        return round(float(actual_value) * 100 / float(planned_value))
    return None


def workout_compliance(
    event: dict[str, Any], activity: dict[str, Any] | None, today: date
) -> dict[str, Any]:
    event_date = _record_date(
        _first_present(event, ("start_date_local", "date", "start"))
    )
    if activity is not None:
        status = "completed"
    elif event_date < today.isoformat():
        status = "missed"
    else:
        status = "planned"
    planned_load = _workout_load(event)
    actual_load = _workout_load(activity)
    planned_duration = _workout_duration(event)
    actual_duration = _workout_duration(activity)
    basis, planned_value, actual_value = _workout_compliance_basis(
        activity,
        planned_load,
        actual_load,
        planned_duration,
        actual_duration,
    )
    percentage = _workout_compliance_percentage(
        status, activity, basis, planned_value, actual_value
    )
    result: dict[str, Any] = {
        "status": status,
        "percentage": percentage,
        "basis": basis,
        "planned_value": planned_value,
        "actual_value": actual_value,
        "planned_duration": planned_duration,
        "actual_duration": actual_duration,
        "planned_load": planned_load,
        "actual_load": actual_load,
    }
    if activity is not None:
        result.update(
            {
                "activity_id": _first_present(activity, ("id", "activityId")),
                "activity_name": str(activity.get("name") or "Absolvierte Einheit")[
                    :200
                ],
                "activity_start": _first_present(
                    activity, ("start_date_local", "start_date", "start")
                ),
                "actual_activity": calendar_activity_payload(activity),
            }
        )
    return result


def _planning_compliance_rows(
    planned: list[dict[str, Any]],
    matches: dict[int, dict[str, Any]],
    today: date,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    enriched: list[dict[str, Any]] = []
    week_rows: dict[str, list[dict[str, Any]]] = {}
    for index, event in enumerate(planned):
        if not is_planned_workout_event(event):
            enriched.append(event)
            continue
        compliance = workout_compliance(event, matches.get(index), today)
        enriched.append({**event, "compliance": compliance})
        event_date = _record_date(
            _first_present(event, ("start_date_local", "date", "start"))
        )
        try:
            event_day = date.fromisoformat(event_date)
        except ValueError:
            continue
        week_start = event_day - timedelta(days=event_day.weekday())
        week_rows.setdefault(week_start.isoformat(), []).append(compliance)
    return enriched, week_rows


def _weekly_compliance_values(
    rows: list[dict[str, Any]],
) -> tuple[str | None, float | None, float | None]:
    all_have_load = all(
        compliance.get("planned_load") is not None and compliance["planned_load"] > 0
        for compliance in rows
    )
    load_available = all(
        compliance["status"] != "completed" or compliance.get("actual_load") is not None
        for compliance in rows
    )
    if all_have_load and load_available:
        return (
            "training_load",
            sum(float(compliance["planned_load"]) for compliance in rows),
            sum(float(compliance.get("actual_load") or 0) for compliance in rows),
        )
    all_have_duration = all(
        compliance.get("planned_duration") is not None
        and compliance["planned_duration"] > 0
        for compliance in rows
    )
    duration_available = all(
        compliance["status"] != "completed"
        or compliance.get("actual_duration") is not None
        for compliance in rows
    )
    if all_have_duration and duration_available:
        return (
            "duration",
            sum(float(compliance["planned_duration"]) for compliance in rows),
            sum(float(compliance.get("actual_duration") or 0) for compliance in rows),
        )
    return None, None, None


def _weekly_compliance_row(
    week_start: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    planned_count = len(rows)
    completed_count = sum(
        1 for compliance in rows if compliance["status"] == "completed"
    )
    basis, planned_value, actual_value = _weekly_compliance_values(rows)
    percentage = round(actual_value * 100 / planned_value) if planned_value else None
    return {
        "week_start": week_start,
        "week_end": (date.fromisoformat(week_start) + timedelta(days=6)).isoformat(),
        "planned_units": planned_count,
        "completed_units": completed_count,
        "unit_percentage": (
            round(completed_count * 100 / planned_count) if planned_count else None
        ),
        "percentage": percentage,
        "basis": basis,
        "planned_value": (
            round(planned_value, 2) if planned_value is not None else None
        ),
        "actual_value": round(actual_value, 2) if actual_value is not None else None,
    }


def planning_compliance_state(
    planned: list[Any], activities: list[Any], today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Add unit compliance and return aggregate weekly compliance metrics."""
    normalized_planned = [dict(item) for item in planned if isinstance(item, dict)]
    matches = match_planned_workouts(normalized_planned, activities)
    enriched, week_rows = _planning_compliance_rows(normalized_planned, matches, today)
    weekly = [
        _weekly_compliance_row(week_start, rows)
        for week_start, rows in sorted(week_rows.items())
    ]
    return enriched, weekly


def training_calendar_items(
    planned: list[Any], activities: list[Any]
) -> list[dict[str, Any]]:
    """Combine enriched plan entries with unmatched completed activities."""
    planned_rows = [dict(item) for item in planned if isinstance(item, dict)]
    activity_rows = [item for item in activities if isinstance(item, dict)]
    matched_activity_keys: set[tuple[Any, ...]] = set()
    for item in planned_rows:
        compliance = item.get("compliance")
        identity = (
            calendar_activity_identity(compliance.get("actual_activity"))
            if isinstance(compliance, dict)
            else None
        )
        if identity is not None:
            matched_activity_keys.add(identity)
    completed_rows = [
        calendar_activity_payload(activity)
        for activity in activity_rows
        if calendar_activity_identity(activity) not in matched_activity_keys
    ]
    combined = planned_rows + [item for item in completed_rows if item.get("date")]
    combined.sort(
        key=lambda item: (
            str(item.get("start_date_local") or item.get("date") or "9999-12-31"),
            str(item.get("name") or "").casefold(),
            str(
                item.get("id") or item.get("local_id") or item.get("external_id") or ""
            ),
        )
    )
    return combined
