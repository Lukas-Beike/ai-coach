"""Composition for the weather refresh and sync use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from backend.runtime.maintenance import MaintenanceGate
from backend.weather import service as weather
from backend.weather.projection import WEATHER_FORECAST_DAYS


class WeatherSyncWorkflow(Protocol):
    def sync(
        self,
        reason: str = "background",
        force: bool = False,
        operation_id: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WeatherStateOwners:
    database_manager: Callable[[], Any]
    key_values: Any
    profile_service: Callable[[], Any]


@dataclass(frozen=True)
class WeatherProviderRuntime:
    client_factory: Callable[[int], Any]
    refresh_tracker: Callable[[], Any]
    operation_context: Any
    operation_id_factory: Callable[[], str]


@dataclass(frozen=True)
class WeatherSyncRuntime:
    maintenance_gate: MaintenanceGate
    now: Callable[[], datetime]
    today: Callable[[], date]
    adaptive_preview_service: Callable[[], Any]
    observer: Callable[[], Any]
    logger: Any
    service_factory: Callable[
        [Any, weather.WeatherService, Any, Any, Any], WeatherSyncWorkflow
    ]


class WeatherAssembly:
    """Resolve weather services while retaining their existing lazy edges."""

    @dataclass(frozen=True)
    class Inputs:
        state: WeatherStateOwners
        provider: WeatherProviderRuntime
        sync: WeatherSyncRuntime

    def __init__(
        self,
        *,
        dependencies: WeatherAssembly.Inputs,
    ) -> None:
        state = dependencies.state
        provider = dependencies.provider
        sync = dependencies.sync
        self._database_manager = state.database_manager
        self._key_values = state.key_values
        self._profile_service = state.profile_service
        self._client_factory = lambda: provider.client_factory(WEATHER_FORECAST_DAYS)
        self._refresh_tracker = provider.refresh_tracker
        self._operation_context = provider.operation_context
        self._operation_id_factory = provider.operation_id_factory
        self._maintenance_gate = sync.maintenance_gate
        self._now = sync.now
        self._today = sync.today
        self._adaptive_preview_service = sync.adaptive_preview_service
        self._observer = sync.observer
        self._logger = sync.logger
        self._sync_service_factory = sync.service_factory

    def service(self) -> weather.WeatherService:
        """Return the weather service bound to the current database manager."""
        manager = self._database_manager()
        return weather.WEATHER_SERVICE_CACHE.get(
            manager,
            weather.WeatherCacheStore(
                manager, self._key_values, self._profile_service()
            ),
            self._client_factory,
            weather.WeatherRefreshJournal(
                self._refresh_tracker(),
                self._operation_context,
                self._operation_id_factory,
                self._logger,
            ),
            self._maintenance_gate,
            self._now,
            self._today,
        )

    def sync_service(self) -> WeatherSyncWorkflow:
        """Create the weather sync workflow over current domain services."""
        return self._sync_service_factory(
            self._profile_service(),
            self.service(),
            self._adaptive_preview_service(),
            self._observer(),
            self._logger,
        )
