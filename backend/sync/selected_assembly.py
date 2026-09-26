"""Composition for explicitly selected workout synchronization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.sync.gates import ProviderResyncGate
from backend.sync.selected import SelectedWorkoutSyncService


class SelectedWorkoutSyncAssembly:
    """Create selected-workout sync from its three cohesive sync owners."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        database_manager: Callable[[], DatabaseManager],
        workout_library_sync_service: Callable[[], Any],
        planned_calendar_sync_service: Callable[[], Any],
        planned_calendar_repair_service: Callable[[], Any],
        redactor: Callable[[str], str],
        lock: Any,
        wait_seconds: float,
        provider_resync_gate: ProviderResyncGate,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._workout_library_sync_service = workout_library_sync_service
        self._planned_calendar_sync_service = planned_calendar_sync_service
        self._planned_calendar_repair_service = planned_calendar_repair_service
        self._redactor = redactor
        self._lock = lock
        self._wait_seconds = wait_seconds
        self._provider_resync_gate = provider_resync_gate

    def service(self) -> SelectedWorkoutSyncService:
        """Create a fresh selected-workout synchronization use case."""
        return SelectedWorkoutSyncService(
            self._config(),
            self._database_manager(),
            self._workout_library_sync_service(),
            self._planned_calendar_sync_service(),
            self._planned_calendar_repair_service(),
            self._redactor,
            lock=self._lock,
            wait_seconds=self._wait_seconds,
            provider_resync_gate=self._provider_resync_gate,
        )
