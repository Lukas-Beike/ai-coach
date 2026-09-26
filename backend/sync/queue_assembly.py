"""Composition for persistent sync-job queue services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from threading import Event
from typing import Any

from backend.db.manager import DatabaseManager
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import job_outcomes, jobs, queue
from backend.sync.daily import DailySyncMarkerService


class SyncJobQueueAssembly:
    """Build job stores and queue projections over shared process resources."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        now: Callable[[], str],
        current_time: Callable[[], datetime],
        uuid_factory: Callable[[], str],
        event_buffer: StateEventBuffer,
        maintenance_gate: MaintenanceGate,
        wake_event: Callable[[], Event],
        all_sync_days: int,
        daily_sync_marker_service: Callable[[], DailySyncMarkerService],
        redact_text: Callable[[str], str],
        logger: Any,
        retry_base_seconds: int,
        retry_max_seconds: int,
    ) -> None:
        self._database_manager = database_manager
        self._now = now
        self._current_time = current_time
        self._uuid_factory = uuid_factory
        self._event_buffer = event_buffer
        self._maintenance_gate = maintenance_gate
        self._wake_event = wake_event
        self._all_sync_days = all_sync_days
        self._daily_sync_marker_service = daily_sync_marker_service
        self._redact_text = redact_text
        self._logger = logger
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    def store(self) -> jobs.SyncJobStore:
        """Create a store bound to the active database manager."""
        return jobs.SyncJobStore(
            self._database_manager(), self._now, self._uuid_factory
        )

    def service(self) -> queue.SyncJobQueueService:
        """Create queue operations over the shared event and wake owners."""
        return queue.SyncJobQueueService(
            self.store(),
            self._event_buffer,
            self._maintenance_gate,
            self._wake_event(),
            self._all_sync_days,
            self._daily_sync_marker_service(),
        )

    def outcome_service(self) -> job_outcomes.SyncJobOutcomeService:
        """Create outcome handling over the same store and wake owners."""
        return job_outcomes.SyncJobOutcomeService(
            self.store(),
            self._event_buffer,
            self._wake_event(),
            self._redact_text,
            self._logger,
            self._current_time,
            self._retry_base_seconds,
            self._retry_max_seconds,
        )
