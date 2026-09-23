"""Open-Meteo weather forecast provider."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from backend.errors import AppError
from backend.weather import forecast as weather_forecast
from backend.weather import projection as weather_projection

WEATHER_ICON_D2_DAYS = 2
NRW_LATITUDE_BOUNDS = (50.3, 52.6)
NRW_LONGITUDE_BOUNDS = (5.5, 9.6)
LOGGER = logging.getLogger("intervals_coach")


class WeatherClient:
    """Fetch a geocoded Open-Meteo forecast with an optional ICON-D2 overlay."""

    def __init__(
        self,
        request: Callable[..., Any],
        now: Callable[[], str],
        logger: Any = None,
    ) -> None:
        self._request = request
        self._now = now
        self._logger = logger if logger is not None else LOGGER

    def fetch(self, query: str) -> dict[str, Any]:
        """Return the forecast for ``query`` without changing input data."""
        location = self._geocoded_location(query)
        forecast_params = weather_forecast.weather_forecast_params(
            location, weather_projection.WEATHER_FORECAST_DAYS, "ecmwf_ifs"
        )
        forecast_url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
            forecast_params
        )
        forecast = self._request(
            "GET",
            forecast_url,
            timeout=10,
            service="open-meteo-forecast-ecmwf",
        )
        if not weather_forecast.weather_forecast_is_complete(forecast):
            raise AppError(
                502, "Open-Meteo hat keine vollständige Wettervorhersage geliefert."
            )
        forecast, model = self._fetch_icon_d2(location, forecast_params, forecast)
        return {
            "query": query[:200],
            "location": location,
            "model": model,
            "forecast": forecast,
            "fetched_at": self._now(),
        }

    def _geocoded_location(self, query: str) -> dict[str, Any]:
        geocode_url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
            {
                "name": query[:200],
                "count": 1,
                "language": "de",
                "format": "json",
            }
        )
        geocode = self._request(
            "GET",
            geocode_url,
            timeout=10,
            service="open-meteo-geocoding",
        )
        results = geocode.get("results") if isinstance(geocode, dict) else None
        location_result = (
            results[0]
            if isinstance(results, list) and results and isinstance(results[0], dict)
            else None
        )
        latitude = (
            weather_projection.weather_number(location_result.get("latitude"))
            if location_result
            else None
        )
        longitude = (
            weather_projection.weather_number(location_result.get("longitude"))
            if location_result
            else None
        )
        if latitude is None or longitude is None:
            raise AppError(400, "Der Wetterort wurde nicht gefunden.")
        return {
            "name": str(location_result.get("name") or query)[:200],
            "country": str(location_result.get("country") or "")[:100],
            "country_code": str(location_result.get("country_code") or "").upper()[:2],
            "latitude": latitude,
            "longitude": longitude,
            "timezone": str(location_result.get("timezone") or "")[:80],
        }

    def _fetch_icon_d2(
        self,
        location: dict[str, Any],
        params: dict[str, Any],
        forecast: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if location["country_code"] != "DE" or not (
            NRW_LATITUDE_BOUNDS[0] <= location["latitude"] <= NRW_LATITUDE_BOUNDS[1]
            and NRW_LONGITUDE_BOUNDS[0]
            <= location["longitude"]
            <= NRW_LONGITUDE_BOUNDS[1]
        ):
            return forecast, "ECMWF IFS HRES (3–14 Tage)"

        short_params = dict(params)
        short_params["forecast_days"] = WEATHER_ICON_D2_DAYS
        short_params["models"] = "icon_d2"
        try:
            short_forecast = self._request(
                "GET",
                "https://api.open-meteo.com/v1/forecast?" + urlencode(short_params),
                timeout=10,
                service="open-meteo-forecast-icon-d2",
            )
            if weather_forecast.weather_forecast_is_complete(short_forecast):
                return (
                    weather_forecast.merge_weather_forecasts(forecast, short_forecast),
                    "ICON-D2 (0–2 Tage) + ECMWF IFS HRES (3–14 Tage)",
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "ICON-D2 weather synchronization failed; using ECMWF",
                extra={
                    "event": "weather_icon_d2_failed",
                    "context": {"error_type": type(exc).__name__},
                },
            )
        return forecast, "ECMWF IFS HRES (3–14 Tage)"
