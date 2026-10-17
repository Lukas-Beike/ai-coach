"""Open-Meteo air-quality provider (CAMS Europe/global forecasts)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?"
AIR_QUALITY_DAYS = 5
AIR_QUALITY_HOURLY_FIELDS = (
    "european_aqi",
    "pm2_5",
    "pm10",
    "ozone",
    "nitrogen_dioxide",
    "uv_index",
    "alder_pollen",
    "birch_pollen",
    "grass_pollen",
    "mugwort_pollen",
    "olive_pollen",
    "ragweed_pollen",
)


def air_quality_params(location: dict[str, Any]) -> dict[str, Any]:
    """Build the Open-Meteo air-quality query for a geocoded location."""
    return {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "timezone": "auto",
        "forecast_days": AIR_QUALITY_DAYS,
        "domains": "auto",
        "hourly": ",".join(AIR_QUALITY_HOURLY_FIELDS),
    }


def merge_air_quality(forecast: dict[str, Any], air_quality: Any) -> dict[str, Any]:
    """Align hourly air-quality series to the forecast's hourly timestamps.

    Hours without air-quality data stay None; the weather series are unchanged.
    """
    merged = json.loads(json.dumps(forecast))
    _merge_hourly(merged, air_quality)
    return merged


def _merge_hourly(merged: dict[str, Any], air_quality: Any) -> None:
    hourly = merged.get("hourly")
    raw_source = air_quality.get("hourly") if isinstance(air_quality, dict) else None
    if not isinstance(hourly, dict) or not isinstance(raw_source, dict):
        return
    raw_times = hourly.get("time")
    times = raw_times if isinstance(raw_times, list) else []
    source_times = raw_source.get("time")
    if not isinstance(source_times, list):
        return
    positions = {str(value): index for index, value in enumerate(source_times)}
    for key in AIR_QUALITY_HOURLY_FIELDS:
        values = raw_source.get(key)
        if not isinstance(values, list) or len(values) != len(source_times):
            continue
        hourly[key] = [
            values[positions[str(timestamp)]] if str(timestamp) in positions else None
            for timestamp in times
        ]


class AirQualityClient:
    """Fetch the hourly Open-Meteo air-quality forecast for a location."""

    def __init__(self, request: Callable[..., Any]) -> None:
        self._request = request

    def fetch(self, location: dict[str, Any]) -> dict[str, Any]:
        response = self._request(
            "GET",
            AIR_QUALITY_URL + urlencode(air_quality_params(location)),
            timeout=10,
            service="open-meteo-air-quality",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("hourly"), dict
        ):
            raise TypeError("Open-Meteo air-quality response has no hourly data")
        return response
