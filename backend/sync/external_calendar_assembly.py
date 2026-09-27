"""Composition for external-calendar reads and synchronization."""

from __future__ import annotations

from dataclasses import dataclass

import logging
import threading
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.athlete.clock import AthleteLocalClock
from backend.calendar.external import ExternalCalendarReader
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.runtime.events import StateEventBuffer
from backend.sync.daily import DailySyncMarkerService
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.observation import SyncOperationObserver


@dataclass(frozen=True)
class ExternalCalendarSyncOwners:
    config: Callable[[], Config]
    database_manager: Callable[[], DatabaseManager]
    key_values: KeyValueRepository
    daily_markers: Callable[[], DailySyncMarkerService]
    adaptive_preview_service: Callable[[], Any]
    event_buffer: StateEventBuffer


@dataclass(frozen=True)
class ExternalCalendarSyncRuntime:
    operation_observer: Callable[[], SyncOperationObserver]
    logger: logging.Logger
    redact_text: Callable[[str], str]
    athlete_clock: Callable[[], AthleteLocalClock]
    local_date: Callable[[], date]
    utc_now: Callable[[], str]
    app_version: str
    sync_lock: Callable[[], threading.Lock]


class ExternalCalendarAssembly:
    """Create external-calendar services with current runtime dependencies."""

    @dataclass(frozen=True)
    class Inputs:
        owners: ExternalCalendarSyncOwners
        runtime: ExternalCalendarSyncRuntime

    def __init__(self, *, dependencies: "ExternalCalendarAssembly.Inputs") -> None:
        owners = dependencies.owners
        runtime = dependencies.runtime
        self._config = owners.config
        self._database_manager = owners.database_manager
        self._key_values = owners.key_values
        self._daily_markers = owners.daily_markers
        self._adaptive_preview_service = owners.adaptive_preview_service
        self._event_buffer = owners.event_buffer
        self._operation_observer = runtime.operation_observer
        self._logger = runtime.logger
        self._redact_text = runtime.redact_text
        self._athlete_clock = runtime.athlete_clock
        self._local_date = runtime.local_date
        self._utc_now = runtime.utc_now
        self._app_version = runtime.app_version
        self._sync_lock = runtime.sync_lock

    def reader(self) -> ExternalCalendarReader:
        """Create a local external-calendar reader for the active manager."""
        return ExternalCalendarReader(self._database_manager(), self._local_date)

    def sync_service(self) -> ExternalCalendarSyncService:
        """Create external-calendar synchronization with current config/clock."""
        return ExternalCalendarSyncService(
            self._config(),
            self._database_manager(),
            self._key_values,
            self._daily_markers(),
            self._operation_observer(),
            self._adaptive_preview_service(),
            self._event_buffer,
            self._logger,
            self._redact_text,
            self._athlete_clock().now,
            self._utc_now,
            self._app_version,
            lock=self._sync_lock(),
        )
