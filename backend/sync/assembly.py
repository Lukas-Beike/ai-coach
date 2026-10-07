"""Composition for shared provider synchronization state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import freshness, observation, refresh


@dataclass(frozen=True)
class ProviderSyncPersistence:
    database_manager: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    event_buffer: StateEventBuffer


@dataclass(frozen=True)
class ProviderSyncRuntime:
    config: Callable[[], Config]
    maintenance_gate: MaintenanceGate
    logger: Any
    now: Callable[[], datetime]


@dataclass(frozen=True)
class ProviderRefreshRetryPolicy:
    uuid_factory: Callable[[], Any]
    retry_base_seconds: int
    retry_max_seconds: int


class ProviderSyncAssembly:
    """Resolve provider sync services from current application resources."""

    @dataclass(frozen=True)
    class Inputs:
        persistence: ProviderSyncPersistence
        runtime: ProviderSyncRuntime
        retry_policy: ProviderRefreshRetryPolicy

    def __init__(
        self,
        *,
        dependencies: ProviderSyncAssembly.Inputs,
    ) -> None:
        persistence = dependencies.persistence
        runtime = dependencies.runtime
        retry = dependencies.retry_policy
        self._database_manager = persistence.database_manager
        self._config = runtime.config
        self._key_values = persistence.key_values
        self._event_buffer = persistence.event_buffer
        self._maintenance_gate = runtime.maintenance_gate
        self._logger = runtime.logger
        self._now = runtime.now
        self._uuid_factory = retry.uuid_factory
        self._retry_base_seconds = retry.retry_base_seconds
        self._retry_max_seconds = retry.retry_max_seconds

    def refresh_tracker(self) -> refresh.ProviderRefreshTracker:
        """Return the cache-owned tracker bound to the current manager."""
        return refresh.PROVIDER_REFRESH_TRACKER_CACHE.get(
            self._database_manager(),
            self._event_buffer,
            self._now,
            self._uuid_factory,
            retention_days=freshness.PROVIDER_REFRESH_RETENTION_DAYS,
            max_rows=freshness.PROVIDER_REFRESH_MAX_ROWS,
            retry_base_seconds=self._retry_base_seconds,
            retry_max_seconds=self._retry_max_seconds,
        )

    def operation_observer(self) -> observation.SyncOperationObserver:
        """Create an observer over the shared tracker and maintenance gate."""
        return observation.SyncOperationObserver(
            self.refresh_tracker(), self._maintenance_gate, self._logger
        )

    def freshness_service(self) -> freshness.ProviderFreshnessService:
        """Create a freshness projection for the active config and manager."""
        return freshness.ProviderFreshnessService(
            self._config(), self._database_manager(), self._key_values, self._now
        )
