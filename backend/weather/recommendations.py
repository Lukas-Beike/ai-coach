"""Pure weather-based training recommendations."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

from backend.weather import projection as weather_projection

WEATHER_RECOMMENDATION_DAYS = 5
WORKDAY_TIME_LABEL = "vor der Arbeit"
PLANNED_WORKOUT_LABEL = "Geplante Einheit"
DATE_ONLY_PATTERN = r"\d{4}-\d{2}-\d{2}"


def is_outdoor_activity(event: Any) -> bool:
    """Return whether an event is a run or outdoor cycling workout."""
    if not isinstance(event, dict):
        return False
    value = " ".join(
        str(event.get(key) or "") for key in ("type", "sport", "sport_type", "name")
    ).casefold()
    if re.search(
        r"indoor|virtual|trainer|zwift|treadmill|ergometer|smart.?bike", value
    ):
        return False
    return bool(
        re.search(
            r"ride|cycling|bike|bicycle|rad|velo|gravel|mtb|mountain.?bike|run|lauf|jog",
            value,
        )
    )


def is_cycling_activity(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    value = " ".join(
        str(event.get(key) or "") for key in ("type", "sport", "sport_type", "name")
    ).casefold()
    return bool(
        re.search(
            r"ride|cycling|bike|bicycle|rad|velo|gravel|mtb|mountain.?bike",
            value,
        )
    )


def _weather_training_windows(target_date: date) -> list[tuple[int, int, str]]:
    """Return preferred hourly training windows for a local calendar date."""
    weekday = target_date.weekday()
    if weekday <= 3:
        return [
            (5, 6, WORKDAY_TIME_LABEL),
            (12, 13, "Mittagspause"),
            (16, 22, "nach der Arbeit"),
        ]
    if weekday == 4:
        return [
            (5, 6, WORKDAY_TIME_LABEL),
            (12, 13, "Mittagspause"),
            (14, 22, "nach der Arbeit"),
        ]
    return [(6, 21, "Wochenende")]


def _weather_interval_summary(
    interval: list[dict[str, float | int | str]],
) -> dict[str, Any]:
    """Calculate forecast values used for one possible training window."""
    precipitation = [
        weather_projection.weather_number(item.get("precipitation_probability"))
        for item in interval
    ]
    rain = [
        (weather_projection.weather_number(item.get("rain")) or 0)
        + (weather_projection.weather_number(item.get("showers")) or 0)
        for item in interval
    ]
    temperatures = [
        weather_projection.weather_number(item.get("apparent_temperature"))
        for item in interval
    ]
    gusts = [
        weather_projection.weather_number(item.get("wind_gusts_10m"))
        for item in interval
    ]
    wind_speeds = [
        weather_projection.weather_number(item.get("wind_speed_10m"))
        for item in interval
    ]
    directions = [
        weather_projection.weather_number(item.get("wind_direction_10m"))
        for item in interval
    ]
    return {
        "precipitation_average": sum(
            value for value in precipitation if value is not None
        )
        / max(1, len([value for value in precipitation if value is not None])),
        "rain_total": sum(rain),
        "temperature_average": sum(value for value in temperatures if value is not None)
        / max(1, len([value for value in temperatures if value is not None])),
        "gust_maximum": max(gusts) if gusts else 0,
        "wind_speed_average": sum(value for value in wind_speeds if value is not None)
        / max(1, len([value for value in wind_speeds if value is not None])),
        "wind_direction_average": (
            sum(value for value in directions if value is not None)
            / max(1, len([value for value in directions if value is not None]))
            if any(value is not None for value in directions)
            else None
        ),
        "weather_codes": [
            int(item["weather_code"])
            for item in interval
            if item.get("weather_code") is not None
        ],
    }


def _weather_window_score(event: dict[str, Any], summary: dict[str, Any]) -> float:
    """Score one valid window; lower scores are more suitable."""
    severe_weather = sum(25 for code in summary["weather_codes"] if code >= 95) + sum(
        8 for code in summary["weather_codes"] if 61 <= code <= 86
    )
    running = "run" in str(event.get("type") or "").casefold()
    return (
        summary["precipitation_average"] * 0.8
        + summary["rain_total"] * 8
        + max(0, summary["wind_speed_average"] - 20) * (0.5 if running else 1.4)
        + max(0, summary["gust_maximum"] - 30)
        * (1.0 if is_outdoor_activity(event) and not running else 0.5)
        + max(0, 4 - summary["temperature_average"]) * 1.5
        + max(0, summary["temperature_average"] - 27) * 1.2
        + severe_weather
    )


def _weather_interval_is_usable(
    interval: list[dict[str, float | int | str]],
    duration_hours: int,
    window_start: int,
    window_end: int,
) -> bool:
    if len(interval) < duration_hours:
        return False
    start_hour = int(interval[0]["hour"])
    if start_hour < window_start or start_hour + duration_hours > window_end:
        return False
    return all(
        int(item["hour"]) == start_hour + offset for offset, item in enumerate(interval)
    )


def _weather_candidate_windows(
    event: dict[str, Any],
    rows: list[dict[str, float | int | str]],
    target_date: date,
    duration_hours: int,
) -> list[tuple[float, int, list[dict[str, float | int | str]], str]]:
    candidates: list[tuple[float, int, list[dict[str, float | int | str]], str]] = []
    for window_start, window_end, availability in _weather_training_windows(
        target_date
    ):
        for start in range(len(rows)):
            interval = rows[start : start + duration_hours]
            if not _weather_interval_is_usable(
                interval, duration_hours, window_start, window_end
            ):
                continue
            summary = _weather_interval_summary(interval)
            convenience_penalty = 2 if availability == WORKDAY_TIME_LABEL else 0
            candidates.append(
                (
                    _weather_window_score(event, summary) + convenience_penalty,
                    int(interval[0]["hour"]),
                    interval,
                    availability,
                )
            )
    return candidates


def weather_recommendation(
    event: dict[str, Any], forecast: dict[str, Any]
) -> dict[str, Any] | None:
    event_date = str(event.get("start_date_local") or event.get("date") or "")[:10]
    if not re.fullmatch(DATE_ONLY_PATTERN, event_date):
        return None
    try:
        target_date = date.fromisoformat(event_date)
    except ValueError:
        return None
    rows = weather_projection.hourly_rows(forecast, event_date)
    if not rows:
        return None
    duration_minutes = max(
        5,
        min(
            600,
            round(
                (weather_projection.weather_number(event.get("moving_time")) or 3600)
                / 60
            ),
        ),
    )
    duration_hours = max(1, math.ceil(duration_minutes / 60))
    candidates = _weather_candidate_windows(event, rows, target_date, duration_hours)
    if not candidates:
        return None
    _, start_hour, best, availability = min(
        candidates, key=lambda item: (item[0], item[1])
    )
    summary = _weather_interval_summary(best)
    precipitation_avg = round(summary["precipitation_average"])
    temperature_avg = round(summary["temperature_average"])
    gust_max = round(summary["gust_maximum"])
    wind_speed_avg = round(summary["wind_speed_average"])
    wind_direction = (
        round(summary["wind_direction_average"])
        if summary["wind_direction_average"] is not None
        else None
    )
    end_hour = start_hour + duration_hours
    best_code = summary["weather_codes"][0] if summary["weather_codes"] else None
    recommendation = {
        "date": event_date,
        "event_id": str(event.get("id")) if event.get("id") is not None else None,
        "event_name": str(event.get("name") or PLANNED_WORKOUT_LABEL)[:200],
        "suggested_time": f"{start_hour:02d}:00–{min(23, end_hour):02d}:00 Uhr",
        "availability": availability,
        "weather_code": best_code,
        "icon": weather_projection.weather_icon(best_code),
        "duration_minutes": duration_minutes,
        "precipitation_probability": precipitation_avg,
        "apparent_temperature": temperature_avg,
        "wind_speed": wind_speed_avg,
        "wind_direction": wind_direction,
        "wind_gusts": gust_max,
    }
    reason = (
        f"ca. {temperature_avg} °C gefühlte Temperatur, {wind_speed_avg} km/h Wind "
        f"und {precipitation_avg} % Regenwahrscheinlichkeit"
    )
    if gust_max is not None:
        reason += f", Böen bis {gust_max} km/h"
    recommendation["reason"] = reason + "."
    return recommendation


def weather_recommendations(
    planned: list[dict[str, Any]] | None,
    forecast: dict[str, Any],
    today: date,
) -> list[dict[str, Any]]:
    recommendations = []
    for event in planned or []:
        if not is_outdoor_activity(event):
            continue
        event_date = str(event.get("start_date_local") or event.get("date") or "")[:10]
        try:
            event_day = date.fromisoformat(event_date)
        except ValueError:
            continue
        if (
            not today
            <= event_day
            <= today + timedelta(days=WEATHER_RECOMMENDATION_DAYS - 1)
        ):
            continue
        recommendation = weather_recommendation(event, forecast)
        if recommendation:
            recommendations.append(recommendation)
    return recommendations
