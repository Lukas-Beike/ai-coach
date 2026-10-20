"""Lazy composition of the Wahoo read synchronization and plan export services."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.providers.wahoo_client import WahooClient
from backend.providers.wahoo_fit_download import download_wahoo_fit
from backend.sync.daily import DailySyncMarkerService
from backend.sync.gates import ProviderResyncGate
from backend.sync.observation import SyncOperationObserver
from backend.sync.provider_registry import ProviderRegistry
from backend.sync.wahoo_activity_details import WahooActivityDetailImport
from backend.sync.wahoo_connection import WahooConnectionService
from backend.sync.wahoo_plan_push import WahooPlanPushService
from backend.sync.wahoo_sync import (
    WahooSyncClock,
    WahooSyncService,
    WahooSyncStorage,
)
from backend.sync.wahoo_workout_export import WahooWorkoutExport


@dataclass(frozen=True)
class WahooSyncInputs:
    config: Callable[[], Config]
    connection: Callable[[], WahooConnectionService]
    json_request: Callable[[], Callable[..., Any]]
    database_manager: Callable[[], DatabaseManager]
    database_lock: AbstractContextManager[Any]
    key_values: KeyValueRepository
    daily_markers: Callable[[], DailySyncMarkerService]
    observer: Callable[[], SyncOperationObserver]
    registry: ProviderRegistry
    zone_provider: Callable[[], tzinfo | None]
    now: Callable[[], datetime]
    logger: logging.Logger
    redactor: Callable[[str], str]
    resync_gate: ProviderResyncGate


class WahooSyncAssembly:
    """Share one sync service so its run lock serializes every caller."""

    def __init__(self, inputs: WahooSyncInputs) -> None:
        self._inputs = inputs
        self._service: WahooSyncService | None = None
        self._plan_push: WahooPlanPushService | None = None
        self._details: WahooActivityDetailImport | None = None
        self._lock = threading.Lock()

    def client(self) -> WahooClient:
        """Create a transport bound to the stored, refreshable Wahoo token."""
        inputs = self._inputs
        connection = inputs.connection()
        return WahooClient(
            request=inputs.json_request(),
            access_token=connection.access_token,
            refresh_access_token=connection.refresh_access_token,
            invalidate_access_token=connection.invalidate_access_token,
        )

    def sync_service(self) -> WahooSyncService:
        with self._lock:
            if self._service is None:
                inputs = self._inputs
                self._service = WahooSyncService(
                    config=inputs.config,
                    connection=inputs.connection,
                    source=self.client,
                    storage=WahooSyncStorage(
                        database_manager=inputs.database_manager,
                        database_lock=inputs.database_lock,
                        key_values=inputs.key_values,
                    ),
                    daily_markers=inputs.daily_markers,
                    observer=inputs.observer,
                    registry=inputs.registry,
                    clock=WahooSyncClock(inputs.now, inputs.zone_provider),
                    logger=inputs.logger,
                    gate=inputs.resync_gate,
                    details=self.activity_detail_import,
                )
            return self._service

    def activity_detail_import(self) -> WahooActivityDetailImport:
        """Share one detail importer; it runs only after a sync has committed."""
        with self._lock:
            if self._details is None:
                inputs = self._inputs
                self._details = WahooActivityDetailImport(
                    database_manager=inputs.database_manager,
                    database_lock=inputs.database_lock,
                    key_values=inputs.key_values,
                    download=download_wahoo_fit,
                    monotonic=time.monotonic,
                    logger=inputs.logger,
                )
            return self._details

    def workout_export(self) -> WahooWorkoutExport:
        """Create the library export target; the client resolves per remote call."""
        return WahooWorkoutExport(self.client, now=self._inputs.now)

    def plan_push_service(self) -> WahooPlanPushService:
        """Share one plan-push service so its run lock serializes every caller."""
        configured = self.sync_service().configured
        with self._lock:
            if self._plan_push is None:
                inputs = self._inputs
                self._plan_push = WahooPlanPushService(
                    configured=configured,
                    database_manager=inputs.database_manager,
                    export=self.workout_export,
                    now=inputs.now,
                    redactor=inputs.redactor,
                    gate=inputs.resync_gate,
                )
            return self._plan_push
