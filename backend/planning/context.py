"""Pure daily planning context projections."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from backend.athlete.local_date import LocalDate
from backend.canonical.mapping import selected
from backend.canonical.vocabulary import ProviderId

UTC_OFFSET_SUFFIX = "+00:00"

CHECKIN_FIELDS = (
    "checkin_date",
    "soreness",
    "stress",
    "motivation",
    "session_rpe",
    "day_form",
    "illness",
    "pain",
    "available_minutes",
    "availability_notes",
    "notes",
)
WEATHER_FIELDS = (
    "date",
    "weather_code",
    "condition",
    "temperature_min",
    "temperature_max",
    "apparent_temperature_min",
    "apparent_temperature_max",
    "precipitation_probability_max",
    "rain_sum",
    "showers_sum",
    "snowfall_sum",
    "wind_speed_max",
    "wind_gusts_max",
    "wind_direction_dominant",
    "sunrise",
    "sunset",
    "forecast_saved_at",
    "forecast_location",
    "archived_forecast",
    "rain_peak_time",
    "air_quality",
    "pollen",
)
APPOINTMENT_FIELDS = (
    "id",
    "name",
    "event_date",
    "start_local",
    "end_local",
    "duration_minutes",
    "all_day",
    "training_relevant",
    "no_training",
    "no_intensity",
    "short_only",
)
MARKER_DAY_KEYS = ("no_training", "no_intensity", "short_only")
OPTIONAL_DAY_KEYS = (
    *MARKER_DAY_KEYS,
    "checkin",
    "recovery",
    "health",
    "weather",
    "planned",
    "appointments",
    "activity_feedback",
)
PLANNED_FIELDS = (
    "id",
    "local_id",
    "remote_id",
    "name",
    "type",
    "category",
    "starts_at_local",
    "planned_duration_s",
    "duration_minutes",
    "is_local",
    "is_remote",
)
FEEDBACK_FIELDS = ("activity_id", "activity_name", "activity_date", "notes")


def local_calendar_library_entries(
    rows: list[dict[str, Any]], excluded: set[str]
) -> list[dict[str, Any]]:
    entries = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        local_id = str(row.get("local_id") or "")
        if local_id in excluded:
            continue
        try:
            entry = json.loads(row.get("payload") or "{}")
        except TypeError, ValueError:
            continue
        if isinstance(entry, dict) and entry.get("source") in {
            "coach",
            "library",
            ProviderId.INTERVALS,
        }:
            entries.append({**entry, "local_id": local_id})
    return entries


def planning_date(value: Any) -> str:
    try:
        return LocalDate.parse(value).isoformat()
    except TypeError, ValueError:
        return ""


def external_calendar_event_dates(
    event: dict[str, Any], *, today: date, window_days: int
) -> list[str]:
    """Project the bounded local dates overlapped by an external event."""
    try:
        start = datetime.fromisoformat(
            str(event.get("start_local") or event["event_date"])
        )
        end = datetime.fromisoformat(str(event.get("end_local") or start.isoformat()))
    except ValueError, KeyError:
        return []
    first = start.date()
    last = (end - timedelta(microseconds=1)).date() if end > start else first
    first = max(first, today - timedelta(days=window_days))
    last = min(last, today + timedelta(days=window_days))
    return [
        (first + timedelta(days=offset)).isoformat()
        for offset in range(max(0, (last - first).days + 1))
    ]


def _day(days: dict[str, dict[str, Any]], value: str) -> dict[str, Any]:
    return days.setdefault(value, {"date": value, "planned": [], "appointments": []})


def _project_planned_days(
    days: dict[str, dict[str, Any]], planned: list[dict[str, Any]]
) -> None:
    for event in planned:
        value = planning_date(event.get("starts_at_local") or event.get("date"))
        if value:
            _day(days, value)["planned"].append(selected(event, PLANNED_FIELDS))


def _project_checkin_days(
    days: dict[str, dict[str, Any]], checkins: list[dict[str, Any]]
) -> None:
    for checkin in checkins:
        if not isinstance(checkin, dict):
            continue
        value = planning_date(checkin.get("checkin_date"))
        if value:
            day = _day(days, value)
            day["checkin"] = selected(checkin, CHECKIN_FIELDS)
            # "unknown" is the default and would only add prompt noise.
            if checkin.get("day_status") in ("rest", "pause"):
                day["day_status"] = checkin["day_status"]


def _project_calendar_days(
    days: dict[str, dict[str, Any]],
    calendar_events: list[dict[str, Any]],
    *,
    today: date,
    calendar_window_days: int,
) -> None:
    for event in calendar_events:
        if not isinstance(event, dict):
            continue
        active_markers = [key for key in MARKER_DAY_KEYS if event.get(key)]
        for value in external_calendar_event_dates(
            event, today=today, window_days=calendar_window_days
        ):
            day = _day(days, value)
            day["appointments"].append(selected(event, APPOINTMENT_FIELDS))
            for key in active_markers:
                day[key] = True


def _project_activity_feedback_days(
    days: dict[str, dict[str, Any]], activity_feedback: list[dict[str, Any]]
) -> None:
    for feedback in activity_feedback:
        if not isinstance(feedback, dict):
            continue
        value = planning_date(feedback.get("activity_date"))
        if value and feedback.get("notes"):
            _day(days, value).setdefault("activity_feedback", []).append(
                selected(feedback, FEEDBACK_FIELDS)
            )


def _project_weather_days(
    days: dict[str, dict[str, Any]], weather_days: list[dict[str, Any]]
) -> None:
    for weather_day in weather_days:
        if not isinstance(weather_day, dict):
            continue
        value = planning_date(weather_day.get("date"))
        if value:
            _day(days, value)["weather"] = selected(weather_day, WEATHER_FIELDS)


def _project_recovery_and_health_days(
    days: dict[str, dict[str, Any]],
    recovery_by_date: dict[str, dict[str, Any]],
    health_by_date: dict[str, dict[str, Any]],
) -> None:
    for value, recovery in recovery_by_date.items():
        _day(days, value)["recovery"] = recovery
    for value, health in health_by_date.items():
        _day(days, value)["health"] = health


def _sort_and_clean_daily_planning_days(
    days: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    for value in days.values():
        value["planned"].sort(
            key=lambda event: str(
                event.get("starts_at_local") or event.get("date") or ""
            )
        )
        value["appointments"].sort(
            key=lambda event: str(
                event.get("start_local") or event.get("event_date") or ""
            )
        )
        value.get("activity_feedback", []).sort(
            key=lambda item: str(item.get("activity_id") or "")
        )
        for key in OPTIONAL_DAY_KEYS:
            if not value.get(key):
                value.pop(key, None)
    return [days[key] for key in sorted(days)]


def build_daily_planning_context(
    *,
    planned: list[dict[str, Any]],
    checkins: list[dict[str, Any]],
    calendar_events: list[dict[str, Any]],
    weather_days: list[dict[str, Any]],
    recovery_by_date: dict[str, dict[str, Any]],
    health_by_date: dict[str, dict[str, Any]],
    activity_feedback: list[dict[str, Any]],
    today: date,
    calendar_window_days: int,
) -> list[dict[str, Any]]:
    """Combine already loaded date-specific signals without performing I/O."""
    days: dict[str, dict[str, Any]] = {}
    _project_planned_days(days, planned)
    _project_checkin_days(days, checkins)
    _project_calendar_days(
        days,
        calendar_events,
        today=today,
        calendar_window_days=calendar_window_days,
    )
    _project_activity_feedback_days(days, activity_feedback)
    _project_weather_days(days, weather_days)
    _project_recovery_and_health_days(days, recovery_by_date, health_by_date)
    return _sort_and_clean_daily_planning_days(days)
