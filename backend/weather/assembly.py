"""Composition for the weather refresh and sync use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from backend.runtime.maintenance import MaintenanceGate
from backend.sync.weather import WeatherSyncService
from backend.weather import service as weather


class WeatherAssembly:
    """Resolve weather services while retaining their existing lazy edges."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        key_values: Any,
        profile_service: Callable[[], Any],
        client_factory: Callable[[], Any],
        refresh_tracker: Callable[[], Any],
        operation_context: Any,
        operation_id_factory: Callable[[], str],
        maintenance_gate: MaintenanceGate,
        now: Callable[[], datetime],
        today: Callable[[], date],
        adaptive_preview_service: Callable[[], Any],
        observer: Callable[[], Any],
        logger: Any,
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._profile_service = profile_service
        self._client_factory = client_factory
        self._refresh_tracker = refresh_tracker
        self._operation_context = operation_context
        self._operation_id_factory = operation_id_factory
        self._maintenance_gate = maintenance_gate
        self._now = now
        self._today = today
        self._adaptive_preview_service = adaptive_preview_service
        self._observer = observer
        self._logger = logger

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
