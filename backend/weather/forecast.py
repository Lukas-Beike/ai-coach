"""Pure weather forecast merge and request-parameter helpers."""

from __future__ import annotations

import json
from typing import Any

_HOURLY_FIELDS = (
    "temperature_2m,apparent_temperature,precipitation_probability,rain,showers,"
    "snowfall,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
)
_DAILY_FIELDS = (
    "weather_code,temperature_2m_min,temperature_2m_max,apparent_temperature_min,"
    "apparent_temperature_max,precipitation_probability_max,rain_sum,showers_sum,"
    "snowfall_sum,wind_speed_10m_max,wind_gusts_10m_max,"
    "wind_direction_10m_dominant,sunrise,sunset"
)


def _overlay_weather_values(base: dict[str, Any], short: dict[str, Any]) -> None:
    base_times = base.get("time") if isinstance(base.get("time"), list) else []
    short_times = short.get("time") if isinstance(short.get("time"), list) else []
    positions = {str(value): index for index, value in enumerate(base_times)}
    for key, short_values in short.items():
        if key == "time" or not isinstance(short_values, list):
            continue
        base_values = base.get(key)
        if not isinstance(base_values, list) or len(base_values) != len(base_times):
            continue
        for short_index, timestamp in enumerate(short_times):
            base_index = positions.get(str(timestamp))
            if base_index is not None and short_index < len(short_values):
                base_values[base_index] = short_values[short_index]


def merge_weather_forecasts(
    long_forecast: dict[str, Any], short_forecast: dict[str, Any]
) -> dict[str, Any]:
    """Overlay the higher-resolution ICON-D2 range on the long forecast."""
    merged = json.loads(json.dumps(long_forecast))
    for section_name in ("hourly", "daily"):
        base = (
            merged.get(section_name)
            if isinstance(merged.get(section_name), dict)
            else {}
        )
        short = (
            short_forecast.get(section_name)
            if isinstance(short_forecast.get(section_name), dict)
            else {}
        )
        _overlay_weather_values(base, short)
    return merged


def weather_forecast_params(
    location: dict[str, Any], days: int, model: str
) -> dict[str, Any]:
    """Build the Open-Meteo forecast query parameters."""
    return {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "timezone": "auto",
        "forecast_days": days,
        "models": model,
        "hourly": _HOURLY_FIELDS,
        "daily": _DAILY_FIELDS,
    }


def weather_forecast_is_complete(forecast: Any) -> bool:
    """Return whether a provider response has both forecast sections."""
    return (
        isinstance(forecast, dict)
        and isinstance(forecast.get("daily"), dict)
        and isinstance(forecast.get("hourly"), dict)
    )
