"""Composition for external-calendar reads and synchronization."""

from __future__ import annotations

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


class ExternalCalendarAssembly:
    """Create external-calendar services with current runtime dependencies."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        database_manager: Callable[[], DatabaseManager],
        key_values: KeyValueRepository,
        daily_markers: Callable[[], DailySyncMarkerService],
        operation_observer: Callable[[], SyncOperationObserver],
        adaptive_preview_service: Callable[[], Any],
        event_buffer: StateEventBuffer,
        logger: logging.Logger,
        redact_text: Callable[[str], str],
        athlete_clock: Callable[[], AthleteLocalClock],
        local_date: Callable[[], date],
        utc_now: Callable[[], str],
        app_version: str,
        sync_lock: Callable[[], threading.Lock],
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._key_values = key_values
        self._daily_markers = daily_markers
        self._operation_observer = operation_observer
        self._adaptive_preview_service = adaptive_preview_service
        self._event_buffer = event_buffer
        self._logger = logger
        self._redact_text = redact_text
        self._athlete_clock = athlete_clock
        self._local_date = local_date
        self._utc_now = utc_now
        self._app_version = app_version
        self._sync_lock = sync_lock

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
