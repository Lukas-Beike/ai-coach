"""Open-Meteo historical forecast provider for the weather during one activity.

The Historical Forecast API serves the stored forecasts of past model runs (about
2 km in Germany, no delay, data from 2022). Only the coordinates rounded to
``COORDINATE_DECIMALS`` and the UTC days of the activity leave the server.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Final
from urllib.parse import urlencode

HISTORICAL_FORECAST_URL: Final = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast?"
)
SERVICE: Final = "open-meteo-historical-forecast"
# About 1 km: the position of a home or a start is not sent more exactly.
COORDINATE_DECIMALS: Final = 2
HOURLY_FIELDS: Final = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "wind_speed_10m",
    "precipitation",
)


def rounded_coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    """The coordinates as they are sent to Open-Meteo."""
    return round(latitude, COORDINATE_DECIMALS), round(longitude, COORDINATE_DECIMALS)


def activity_weather_params(
    latitude: float, longitude: float, first_day: date, last_day: date
) -> dict[str, Any]:
    """The query for the hourly values of the UTC days ``first_day`` to ``last_day``."""
    rounded_latitude, rounded_longitude = rounded_coordinates(latitude, longitude)
    return {
        "latitude": rounded_latitude,
        "longitude": rounded_longitude,
        "start_date": first_day.isoformat(),
        "end_date": last_day.isoformat(),
        "hourly": ",".join(HOURLY_FIELDS),
        "timezone": "GMT",
        "wind_speed_unit": "ms",
    }


class ActivityWeatherClient:
    """Fetch the hourly historical forecast of one position and day range."""

    def __init__(self, request: Callable[..., Any]) -> None:
        self._request = request

    def fetch(
        self, latitude: float, longitude: float, first_day: date, last_day: date
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            HISTORICAL_FORECAST_URL
            + urlencode(
                activity_weather_params(latitude, longitude, first_day, last_day)
            ),
            timeout=10,
            service=SERVICE,
        )
        hourly = response.get("hourly") if isinstance(response, dict) else None
        if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
            raise TypeError("Open-Meteo historical forecast has no hourly data")
        return {"hourly": hourly}
