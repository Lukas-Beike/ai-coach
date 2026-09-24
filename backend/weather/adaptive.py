"""Pure weather-adaptive decisions for planned cycling workouts."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from backend.weather import projection as weather_projection
from backend.weather import recommendations as weather_recommendations

WEATHER_ADAPTIVE_DAYS = 3
WEATHER_ADAPTIVE_LONG_RIDE_MINUTES = 180


def _as_number(value: Any) -> float | int | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _weather_adaptive_duration_minutes(event: dict[str, Any]) -> float | int:
    if not isinstance(event, dict):
        return 0
    duration_minutes = _as_number(event.get("duration_minutes"))
    if duration_minutes is None:
        duration_minutes = (
            weather_projection.weather_number(event.get("moving_time")) or 0
        ) / 60
    return duration_minutes


def _weather_adaptive_forecast(
    event: dict[str, Any],
    weather_days: dict[str, dict[str, Any]],
    today: date,
) -> tuple[str, dict[str, Any]] | None:
    if (
        not isinstance(event, dict)
        or not isinstance(weather_days, dict)
        or not isinstance(today, date)
    ):
        return None
    event_date = str(event.get("date") or event.get("start_date_local") or "")[:10]
    try:
        target_date = date.fromisoformat(event_date)
    except (TypeError, ValueError):
        return None
    if not today <= target_date <= today + timedelta(days=WEATHER_ADAPTIVE_DAYS - 1):
        return None
    forecast = weather_days.get(event_date)
    if not isinstance(forecast, dict):
        return None
    return event_date, forecast


def _weather_adaptive_precipitation(
    forecast: dict[str, Any],
) -> tuple[bool, bool, float | int | None, float | int, float | int]:
    if not isinstance(forecast, dict):
        return False, False, None, 0, 0
    code = forecast.get("weather_code")
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    probability = weather_projection.weather_number(
        forecast.get("precipitation_probability_max")
    )
    rain_total = sum(
        value or 0
        for value in (
            weather_projection.weather_number(forecast.get("rain_sum")),
            weather_projection.weather_number(forecast.get("showers_sum")),
        )
    )
    snowfall = weather_projection.weather_number(forecast.get("snowfall_sum")) or 0
    rain_codes = {61, 63, 65, 80, 81, 82, 95, 96, 99}
    snow_codes = {71, 73, 75, 77, 85, 86}
    persistent_rain = code in rain_codes and (
        (probability is not None and probability >= 70 and rain_total >= 3)
        or rain_total >= 8
        or code in {63, 65, 81, 82, 95, 96, 99}
    )
    persistent_snow = code in snow_codes and (
        (probability is not None and probability >= 70) or snowfall >= 2
    )
    return persistent_rain, persistent_snow, probability, rain_total, snowfall


def _weather_adaptive_details(
    persistent_rain: bool,
    probability: float | None,
    rain_total: float,
    snowfall: float,
) -> str:
    details = []
    if probability is not None:
        details.append(f"bis zu {round(probability)} % Niederschlagswahrscheinlichkeit")
    if rain_total or snowfall:
        amount = rain_total if persistent_rain else snowfall
        unit = "mm Regen" if persistent_rain else "cm Schnee"
        details.append(f"ca. {amount:g} {unit}")
    return f" ({', '.join(details)})" if details else ""


def weather_adaptive_reason(
    event: dict[str, Any], weather_days: dict[str, dict[str, Any]], today: date
) -> str | None:
    """Return a reason when a long outdoor ride is not reasonable in the near forecast."""
    if not weather_recommendations.is_outdoor_activity(
        event
    ) or not weather_recommendations.is_cycling_activity(event):
        return None
    if _weather_adaptive_duration_minutes(event) < WEATHER_ADAPTIVE_LONG_RIDE_MINUTES:
        return None
    forecast_result = _weather_adaptive_forecast(event, weather_days, today)
    if not forecast_result:
        return None
    event_date, forecast = forecast_result
    persistent_rain, persistent_snow, probability, rain_total, snowfall = (
        _weather_adaptive_precipitation(forecast)
    )
    if not persistent_rain and not persistent_snow:
        return None
    condition = "anhaltenden Regen" if persistent_rain else "anhaltenden Schneefall"
    detail_text = _weather_adaptive_details(
        persistent_rain, probability, rain_total, snowfall
    )
    return f"Wetterprognose für {event_date}: {condition}{detail_text}; lange Outdoor-Ausfahrt nicht sinnvoll"
