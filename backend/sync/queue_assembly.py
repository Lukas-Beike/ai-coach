"""Composition for persistent sync-job queue services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Any

from backend.db.manager import DatabaseManager
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import job_outcomes, jobs, queue
from backend.sync.daily import DailySyncMarkerService


@dataclass(frozen=True)
class SyncQueuePersistence:
    database_manager: Callable[[], DatabaseManager]
    now: Callable[[], str]
    current_time: Callable[[], datetime]
    uuid_factory: Callable[[], str]


@dataclass(frozen=True)
class SyncQueueWorker:
    event_buffer: StateEventBuffer
    maintenance_gate: MaintenanceGate
    wake_event: Callable[[], Event]
    daily_sync_marker_service: Callable[[], DailySyncMarkerService]


@dataclass(frozen=True)
class SyncQueuePolicy:
    all_sync_days: int
    redact_text: Callable[[str], str]
    logger: Any
    retry_base_seconds: int
    retry_max_seconds: int


class SyncJobQueueAssembly:
    """Build job stores and queue projections over shared process resources."""

    @dataclass(frozen=True)
    class Inputs:
        persistence: SyncQueuePersistence
        worker: SyncQueueWorker
        policy: SyncQueuePolicy

    def __init__(
        self,
        *,
        dependencies: "SyncJobQueueAssembly.Inputs",
    ) -> None:
        persistence = dependencies.persistence
        worker = dependencies.worker
        policy = dependencies.policy
        self._database_manager = persistence.database_manager
        self._now = persistence.now
        self._current_time = persistence.current_time
        self._uuid_factory = persistence.uuid_factory
        self._event_buffer = worker.event_buffer
        self._maintenance_gate = worker.maintenance_gate
        self._wake_event = worker.wake_event
        self._daily_sync_marker_service = worker.daily_sync_marker_service
        self._all_sync_days = policy.all_sync_days
        self._redact_text = policy.redact_text
        self._logger = policy.logger
        self._retry_base_seconds = policy.retry_base_seconds
        self._retry_max_seconds = policy.retry_max_seconds

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
