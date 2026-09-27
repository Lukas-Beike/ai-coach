"""Composition for the weather refresh and sync use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from backend.runtime.maintenance import MaintenanceGate
from backend.sync.weather import WeatherSyncService
from backend.weather import service as weather


@dataclass(frozen=True)
class WeatherStateOwners:
    database_manager: Callable[[], Any]
    key_values: Any
    profile_service: Callable[[], Any]


@dataclass(frozen=True)
class WeatherProviderRuntime:
    client_factory: Callable[[], Any]
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
        dependencies: "WeatherAssembly.Inputs",
    ) -> None:
        state = dependencies.state
        provider = dependencies.provider
        sync = dependencies.sync
        self._database_manager = state.database_manager
        self._key_values = state.key_values
        self._profile_service = state.profile_service
        self._client_factory = provider.client_factory
        self._refresh_tracker = provider.refresh_tracker
        self._operation_context = provider.operation_context
        self._operation_id_factory = provider.operation_id_factory
        self._maintenance_gate = sync.maintenance_gate
        self._now = sync.now
        self._today = sync.today
        self._adaptive_preview_service = sync.adaptive_preview_service
        self._observer = sync.observer
        self._logger = sync.logger

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

    def sync_service(self) -> WeatherSyncService:
        """Create the weather sync workflow over current domain services."""
        return WeatherSyncService(
            self._profile_service(),
            self.service(),
            self._adaptive_preview_service(),
            self._observer(),
            self._logger,
        )
