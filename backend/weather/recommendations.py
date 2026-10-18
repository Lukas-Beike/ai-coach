"""Pure weather-based training recommendations."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

from backend.athlete.local_date import iso_date_prefix
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


def _known_average(values: list[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return sum(known) / len(known) if known else None


def _weather_rain_amount(item: dict[str, float | int | str]) -> float | None:
    rain = weather_projection.weather_number(item.get("rain"))
    showers = weather_projection.weather_number(item.get("showers"))
    if rain is None and showers is None:
        return None
    return (rain or 0) + (showers or 0)


def _round_optional(value: float | None) -> int | None:
    return round(value) if value is not None else None


def _weather_interval_summary(
    interval: list[dict[str, float | int | str]],
) -> dict[str, Any]:
    """Calculate forecast values used for one possible training window.

    Unknown measurements stay None; they are never reported as zero.
    """
    precipitation = [
        weather_projection.weather_number(item.get("precipitation_probability"))
        for item in interval
    ]
    rain = [_weather_rain_amount(item) for item in interval]
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
    air_quality = [
        weather_projection.weather_number(item.get("european_aqi")) for item in interval
    ]
    known_rain = [value for value in rain if value is not None]
    return {
        "precipitation_average": _known_average(precipitation),
        "rain_total": sum(known_rain) if known_rain else None,
        "temperature_average": _known_average(temperatures),
        "gust_maximum": max(
            (value for value in gusts if value is not None), default=None
        ),
        "wind_speed_average": _known_average(wind_speeds),
        "wind_direction_average": _known_average(directions),
        "air_quality_maximum": max(
            (value for value in air_quality if value is not None), default=None
        ),
        "weather_codes": [
            int(item["weather_code"])
            for item in interval
            if item.get("weather_code") is not None
        ],
    }


def _weather_window_score(event: dict[str, Any], summary: dict[str, Any]) -> float:
    """Score one valid window; lower scores are more suitable.

    Precipitation probability and apparent temperature are required by the
    candidate filter. Optional wind, rain, and air-quality terms add no penalty
    when unknown.
    """
    severe_weather = sum(25 for code in summary["weather_codes"] if code >= 95) + sum(
        8 for code in summary["weather_codes"] if 61 <= code <= 86
    )
    running = "run" in str(event.get("type") or "").casefold()
    wind_speed = summary["wind_speed_average"] or 0
    gust_maximum = summary["gust_maximum"] or 0
    rain_total = summary["rain_total"] or 0
    air_quality = summary["air_quality_maximum"] or 0
    return (
        summary["precipitation_average"] * 0.8
        + rain_total * 8
        + max(0, wind_speed - 20) * (0.5 if running else 1.4)
        + max(0, gust_maximum - 30)
        * (1.0 if is_outdoor_activity(event) and not running else 0.5)
        + max(0, 4 - summary["temperature_average"]) * 1.5
        + max(0, summary["temperature_average"] - 27) * 1.2
        + max(0, air_quality - 40) * 0.6
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
            if (
                summary["precipitation_average"] is None
                or summary["temperature_average"] is None
            ):
                continue
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
    event_date = iso_date_prefix(
        str(event.get("start_date_local") or event.get("date") or "")
    )
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
    gust_max = _round_optional(summary["gust_maximum"])
    wind_speed_avg = _round_optional(summary["wind_speed_average"])
    wind_direction = _round_optional(summary["wind_direction_average"])
    air_quality_max = _round_optional(summary["air_quality_maximum"])
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
    if air_quality_max is not None:
        recommendation["european_aqi"] = air_quality_max
    reason = f"ca. {temperature_avg} °C gefühlte Temperatur"
    if wind_speed_avg is not None:
        reason += f", {wind_speed_avg} km/h Wind"
    reason += f" und {precipitation_avg} % Regenwahrscheinlichkeit"
    if gust_max is not None:
        reason += f", Böen bis {gust_max} km/h"
    if air_quality_max is not None and air_quality_max >= 60:
        category = weather_projection.european_aqi_category(air_quality_max)
        reason += f", Luftqualität {category} (AQI {air_quality_max})"
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
        event_date = iso_date_prefix(
            str(event.get("start_date_local") or event.get("date") or "")
        )
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
