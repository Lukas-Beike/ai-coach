"""Pure daily planning context projections."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

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
    "no_intensity",
    "short_only",
)
PLANNED_FIELDS = (
    "id",
    "local_id",
    "remote_id",
    "name",
    "type",
    "category",
    "start_date_local",
    "moving_time",
    "duration_minutes",
    "is_local",
    "is_remote",
)
FEEDBACK_FIELDS = ("activity_id", "activity_name", "activity_date", "notes")


def selected(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {key: item[key] for key in fields if key in item and item[key] is not None}


SPORT_SETTING_FIELDS = (
    "id",
    "types",
    "ftp",
    "indoor_ftp",
    "eftp",
    "eFTP",
    "w_prime",
    "p_max",
    "lthr",
    "max_hr",
    "maxHR",
    "maxHeartRate",
    "threshold_pace",
    "zone2_pace",
    "zone_2_pace",
    "z2_pace",
    "pace_zone2",
    "paceZone2",
    "zone2Pace",
    "pace_units",
    "vo2max",
    "vo2_max",
    "running_vo2max",
    "cycling_vo2max",
)
WELLNESS_SPORT_INFO_FIELDS = (
    "id",
    "type",
    "types",
    "sport",
    "sport_type",
    "ftp",
    "eftp",
    "eFTP",
    "wPrime",
    "w_prime",
    "pMax",
    "p_max",
    "lthr",
    "max_hr",
    "maxHR",
    "maxHeartRate",
    "threshold_pace",
    "zone2_pace",
    "zone_2_pace",
    "z2_pace",
    "pace_zone2",
    "paceZone2",
    "zone2Pace",
    "pace_units",
    "vo2max",
    "vo2_max",
    "running_vo2max",
    "cycling_vo2max",
)
ACTIVITY_FIELDS = (
    "id",
    "start_date_local",
    "name",
    "type",
    "moving_time",
    "distance",
    "total_elevation_gain",
    "elapsed_time",
    "icu_training_load",
    "icu_intensity",
    "icu_ctl",
    "icu_atl",
    "icu_ftp",
    "icu_eftp",
    "average_heartrate",
    "max_heartrate",
    "average_watts",
    "weighted_average_watts",
    "icu_weighted_avg_watts",
    "normalized_power",
    "average_speed",
    "max_speed",
    "icu_weighted_avg_speed",
    "icu_pace",
    "vo2max",
    "vo2_max",
    "vO2MaxValue",
    "vo2MaxValue",
    "icu_vo2max",
    "feel",
    "icu_rpe",
    "paired_event_id",
    "source",
    "device_name",
    "external_id",
    "file_type",
)
WELLNESS_FIELDS = (
    "id",
    "ctl",
    "ctLoad",
    "atl",
    "atlLoad",
    "tsb",
    "form",
    "rampRate",
    "weight",
    "bodyFat",
    "body_fat",
    "restingHR",
    "hrv",
    "sleepSecs",
    "sleepScore",
    "fatigue",
    "soreness",
    "stress",
    "mood",
    "readiness",
    "readinessScore",
    "readiness_score",
    "trainingReadiness",
    "training_readiness",
)
EVENT_FIELDS = (
    "id",
    "start_date_local",
    "category",
    "name",
    "description",
    "type",
    "moving_time",
    "elapsed_time",
    "distance",
    "icu_training_load",
    "icu_intensity",
    "target",
    "external_id",
)
ATHLETE_FIELDS = (
    "id",
    "name",
    "sex",
    "weight",
    "height",
    "height_cm",
    "bodyFat",
    "body_fat",
    "dob",
    "icu_ftp",
    "icu_w_prime",
    "max_hr",
    "maxHR",
    "maxHeartRate",
    "lthr",
    "vo2max",
    "vo2_max",
    "running_vo2max",
    "cycling_vo2max",
)


def compact_sport_settings(athlete: Any) -> list[dict[str, Any]]:
    if not isinstance(athlete, dict):
        return []
    raw_settings = athlete.get("sportSettings") or athlete.get("sport_settings") or []
    if not isinstance(raw_settings, list):
        return []
    compacted = []
    for item in raw_settings[:30]:
        if not isinstance(item, dict):
            continue
        setting = selected(item, SPORT_SETTING_FIELDS)
        mmp_model = item.get("mmp_model")
        if isinstance(mmp_model, dict):
            setting["mmp_model"] = selected(mmp_model, ("ftp", "eftp", "eFTP"))
        compacted.append(setting)
    return compacted


def compact_wellness_sport_info(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        selected(item, WELLNESS_SPORT_INFO_FIELDS)
        for item in [candidate for candidate in value if isinstance(candidate, dict)][
            :30
        ]
    ]


def compact_snapshot(
    athlete: Any,
    activities: Any,
    wellness: Any,
    events: Any,
    history_days: int = 42,
    *,
    all_sync_days: int,
    synced_at: str,
) -> dict[str, Any]:
    compact_activities = [
        selected(item, ACTIVITY_FIELDS) for item in (activities or [])
    ]
    compact_wellness = [
        {
            **selected(item, WELLNESS_FIELDS),
            "sport_info": compact_wellness_sport_info(item.get("sportInfo")),
        }
        for item in (wellness or [])
        if isinstance(item, dict)
    ]
    if history_days != all_sync_days:
        compact_activities = compact_activities[:500]
        compact_wellness = compact_wellness[-(max(42, history_days) + 1) :]
    return {
        "synced_at": synced_at,
        "athlete": {
            **selected(athlete, ATHLETE_FIELDS),
            "sport_settings": compact_sport_settings(athlete),
        },
        "recent_activities": compact_activities,
        "recent_wellness": compact_wellness,
        "upcoming_calendar": [selected(item, EVENT_FIELDS) for item in (events or [])][
            :200
        ],
    }


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
        except (TypeError, ValueError):
            continue
        if isinstance(entry, dict) and entry.get("source") in {
            "coach",
            "library",
            "intervals",
        }:
            entries.append({**entry, "local_id": local_id})
    return entries


def planning_date(value: Any) -> str:
    raw = str(value or "").replace("Z", UTC_OFFSET_SUFFIX)[:10]
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
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
    except (ValueError, KeyError):
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
        value = planning_date(event.get("start_date_local") or event.get("date"))
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
            _day(days, value)["checkin"] = selected(checkin, CHECKIN_FIELDS)


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
        for value in external_calendar_event_dates(
            event, today=today, window_days=calendar_window_days
        ):
            _day(days, value)["appointments"].append(
                selected(event, APPOINTMENT_FIELDS)
            )


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
                event.get("start_date_local") or event.get("date") or ""
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
        for key in ("checkin", "recovery", "health", "weather"):
            if not value.get(key):
                value.pop(key, None)
        for key in ("planned", "appointments", "activity_feedback"):
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
