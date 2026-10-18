"""Pure weather forecast projections."""

from __future__ import annotations

import math
import re
from typing import Any

WEATHER_CONDITIONS = {
    0: "Klar",
    1: "Überwiegend klar",
    2: "Teilweise bewölkt",
    3: "Bedeckt",
    45: "Nebel",
    48: "Reifnebel",
    51: "Leichter Nieselregen",
    53: "Nieselregen",
    55: "Starker Nieselregen",
    56: "Leichter gefrierender Nieselregen",
    57: "Starker gefrierender Nieselregen",
    61: "Leichter Regen",
    63: "Regen",
    65: "Starker Regen",
    66: "Leichter gefrierender Regen",
    67: "Starker gefrierender Regen",
    71: "Leichter Schneefall",
    73: "Schneefall",
    75: "Starker Schneefall",
    77: "Schneegriesel",
    80: "Leichte Regenschauer",
    81: "Regenschauer",
    82: "Starke Regenschauer",
    85: "Leichte Schneeschauer",
    86: "Starke Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "Starkes Gewitter mit Hagel",
}
WEATHER_ICONS = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌦️",
    53: "🌦️",
    55: "🌧️",
    56: "🌧️",
    57: "🌧️",
    61: "🌧️",
    63: "🌧️",
    65: "🌧️",
    66: "🌧️",
    67: "🌧️",
    71: "🌨️",
    73: "🌨️",
    75: "❄️",
    77: "❄️",
    80: "🌦️",
    81: "🌧️",
    82: "🌧️",
    85: "🌨️",
    86: "🌨️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️",
}
WEATHER_FORECAST_DAYS = 14
_DATE_ONLY_PATTERN = r"\d{4}-\d{2}-\d{2}"
AIR_QUALITY_KEYS = (
    "european_aqi",
    "pm2_5",
    "pm10",
    "ozone",
    "nitrogen_dioxide",
    "uv_index",
)
CAMS_POLLEN_SPECIES = {
    "alder_pollen": "Erle",
    "birch_pollen": "Birke",
    "grass_pollen": "Gräser",
    "mugwort_pollen": "Beifuß",
    "olive_pollen": "Olive",
    "ragweed_pollen": "Ambrosia",
}
EUROPEAN_AQI_CATEGORIES = (
    (20, "gut"),
    (40, "ordentlich"),
    (60, "mäßig"),
    (80, "schlecht"),
    (100, "sehr schlecht"),
)


def weather_number(value: Any) -> float | None:
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def weather_icon(code: int | None) -> str:
    return WEATHER_ICONS.get(code, "🌤️") if code is not None else "🌡️"


def _weather_array_value(values: Any, index: int) -> float | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    return weather_number(values[index])


def _weather_daily_peak_time(forecast: dict[str, Any], target_date: str) -> str | None:
    hours = sorted(
        (
            row
            for row in hourly_rows(forecast, target_date)
            if row.get("precipitation_probability") is not None
            and 0 <= row["precipitation_probability"] <= 100
            and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(row["time"])[11:16])
        ),
        key=lambda row: row["time"],
    )
    peak = max(hours, key=lambda row: row["precipitation_probability"], default=None)
    if peak and any(
        row["precipitation_probability"] < peak["precipitation_probability"]
        for row in hours
    ):
        return str(peak["time"])[11:16]
    return None


def _weather_daily_sun_time(daily: dict[str, Any], key: str, index: int) -> str | None:
    values = daily.get(key)
    return (
        str(values[index]) if isinstance(values, list) and index < len(values) else None
    )


def european_aqi_category(value: float | None) -> str | None:
    """Return the German label of a European AQI value."""
    if value is None or value < 0:
        return None
    return next(
        (label for limit, label in EUROPEAN_AQI_CATEGORIES if value <= limit),
        "extrem schlecht",
    )


def _hourly_daily_max(
    forecast: dict[str, Any], target_date: str, keys: Any
) -> dict[str, float]:
    raw_hourly = forecast.get("hourly")
    hourly = raw_hourly if isinstance(raw_hourly, dict) else {}
    raw_times = hourly.get("time")
    times = raw_times if isinstance(raw_times, list) else []
    indexes = [
        index
        for index, value in enumerate(times)
        if str(value).startswith(target_date + "T")
    ]
    result: dict[str, float] = {}
    for key in keys:
        values = [
            value
            for index in indexes
            if (value := _weather_array_value(hourly.get(key), index)) is not None
            and value >= 0
        ]
        if values:
            result[key] = round(max(values), 1)
    return result


def _daily_air_quality(
    forecast: dict[str, Any], target_date: str
) -> dict[str, Any] | None:
    peaks = _hourly_daily_max(forecast, target_date, AIR_QUALITY_KEYS)
    if not peaks:
        return None
    result: dict[str, Any] = {f"{key}_max": value for key, value in peaks.items()}
    category = european_aqi_category(peaks.get("european_aqi"))
    if category:
        result["european_aqi_category"] = category
    return result


def _daily_pollen(
    forecast: dict[str, Any], target_date: str, pollen: Any
) -> dict[str, Any] | None:
    days = pollen.get("days") if isinstance(pollen, dict) else None
    levels = days.get(target_date) if isinstance(days, dict) else None
    if isinstance(levels, dict):
        return {
            "source": "DWD",
            "region": str(pollen.get("region") or "")[:100],
            "levels": {
                str(name)[:40]: str(level)[:3]
                for name, level in levels.items()
                if str(level) != "0"
            },
        }
    peaks = _hourly_daily_max(forecast, target_date, CAMS_POLLEN_SPECIES)
    if not peaks:
        return None
    return {
        "source": "Open-Meteo/CAMS",
        "unit": "Körner/m³",
        "concentrations": {
            CAMS_POLLEN_SPECIES[key]: round(value)
            for key, value in peaks.items()
            if value >= 1
        },
    }


def _weather_daily_row(
    daily: dict[str, Any],
    forecast: dict[str, Any],
    raw_date: Any,
    index: int,
    pollen: Any = None,
) -> dict[str, Any]:
    target_date = str(raw_date)
    code = _weather_array_value(daily.get("weather_code"), index)
    numeric_code = int(code) if code is not None else None
    row: dict[str, Any] = {
        "date": target_date,
        "weather_code": numeric_code,
        "condition": (
            WEATHER_CONDITIONS.get(numeric_code, "Unbekannte Wetterlage")
            if numeric_code is not None
            else "Keine Angabe"
        ),
        "icon": weather_icon(numeric_code),
        "temperature_min": _weather_array_value(daily.get("temperature_2m_min"), index),
        "temperature_max": _weather_array_value(daily.get("temperature_2m_max"), index),
        "apparent_temperature_min": _weather_array_value(
            daily.get("apparent_temperature_min"), index
        ),
        "apparent_temperature_max": _weather_array_value(
            daily.get("apparent_temperature_max"), index
        ),
        "precipitation_probability_max": _weather_array_value(
            daily.get("precipitation_probability_max"), index
        ),
        "rain_peak_time": _weather_daily_peak_time(forecast, target_date),
        "rain_sum": _weather_array_value(daily.get("rain_sum"), index),
        "showers_sum": _weather_array_value(daily.get("showers_sum"), index),
        "snowfall_sum": _weather_array_value(daily.get("snowfall_sum"), index),
        "wind_speed_max": _weather_array_value(daily.get("wind_speed_10m_max"), index),
        "wind_gusts_max": _weather_array_value(daily.get("wind_gusts_10m_max"), index),
        "wind_direction_dominant": _weather_array_value(
            daily.get("wind_direction_10m_dominant"), index
        ),
        "sunrise": _weather_daily_sun_time(daily, "sunrise", index),
        "sunset": _weather_daily_sun_time(daily, "sunset", index),
    }
    air_quality = _daily_air_quality(forecast, target_date)
    if air_quality:
        row["air_quality"] = air_quality
    daily_pollen = _daily_pollen(forecast, target_date, pollen)
    if daily_pollen:
        row["pollen"] = daily_pollen
    return row


def daily_summary(forecast: dict[str, Any], pollen: Any = None) -> list[dict[str, Any]]:
    """Project daily weather rows, optional air quality, and pollen levels.

    DWD pollen levels take precedence over the Open-Meteo/CAMS fallback.
    """
    raw_daily = forecast.get("daily")
    daily = raw_daily if isinstance(raw_daily, dict) else {}
    raw_dates = daily.get("time")
    dates = raw_dates if isinstance(raw_dates, list) else []
    return [
        _weather_daily_row(daily, forecast, raw_date, index, pollen)
        for index, raw_date in enumerate(dates[:WEATHER_FORECAST_DAYS])
        if re.fullmatch(_DATE_ONLY_PATTERN, str(raw_date))
    ]


def hourly_rows(
    forecast: dict[str, Any], target_date: str
) -> list[dict[str, float | int | str]]:
    raw_hourly = forecast.get("hourly")
    hourly = raw_hourly if isinstance(raw_hourly, dict) else {}
    raw_times = hourly.get("time")
    times = raw_times if isinstance(raw_times, list) else []
    rows: list[dict[str, float | int | str]] = []
    for index, raw_time in enumerate(times):
        timestamp = str(raw_time)
        if not timestamp.startswith(target_date + "T"):
            continue
        try:
            hour = int(timestamp[11:13])
        except ValueError, IndexError:
            continue
        row: dict[str, float | int | str] = {"time": timestamp, "hour": hour}
        for key in (
            "temperature_2m",
            "apparent_temperature",
            "precipitation_probability",
            "rain",
            "showers",
            "snowfall",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
            *AIR_QUALITY_KEYS,
        ):
            value = _weather_array_value(hourly.get(key), index)
            if value is not None:
                row[key] = value
        code = _weather_array_value(hourly.get("weather_code"), index)
        if code is not None:
            row["weather_code"] = int(code)
        rows.append(row)
    return rows
