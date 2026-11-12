"""Build the weather refresh service from the application context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.context import AppContext
from backend.providers import air_quality, dwd_pollen
from backend.providers import weather as weather_provider
from backend.runtime import clock as runtime_clock
from backend.weather import service as weather
from backend.weather.projection import WEATHER_FORECAST_DAYS


@dataclass(frozen=True)
class WeatherServices:
    service: Callable[[], weather.WeatherService]


def build_weather(ctx: AppContext) -> WeatherServices:
    """The weather service, cached per database manager."""

    def client() -> weather_provider.WeatherClient:
        request = ctx.provider_transport.json_http_client().request
        return weather_provider.WeatherClient(
            request,
            runtime_clock.utc_now,
            ctx.logger,
            forecast_days=WEATHER_FORECAST_DAYS,
            air_quality_client=air_quality.AirQualityClient(
                ctx.provider_transport.json_http_client().request
            ),
            pollen_client=dwd_pollen.DwdPollenClient(
                ctx.provider_transport.json_http_client().request
            ),
        )

    def service() -> weather.WeatherService:
        manager = ctx.database()
        return weather.WEATHER_SERVICE_CACHE.get(
            manager,
            weather.WeatherCacheStore(manager, ctx.key_values, ctx.athlete.profile()),
            client,
            weather.WeatherRefreshJournal(
                ctx.provider_sync.refresh_tracker(),
                ctx.operation_context,
                ctx.ids,
                ctx.logger,
            ),
            ctx.maintenance,
            lambda: datetime.now(UTC),
            lambda: ctx.clock.now().date(),
        )

    return WeatherServices(service)
