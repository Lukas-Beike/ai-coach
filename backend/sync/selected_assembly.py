"""Composition for explicitly selected workout synchronization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.sync.gates import ProviderResyncGate
from backend.sync.selected import SelectedWorkoutSyncService


@dataclass(frozen=True)
class SelectedWorkoutProviders:
    config: Callable[[], Config]
    database_manager: Callable[[], DatabaseManager]
    workout_library_sync_service: Callable[[], Any]
    planned_calendar_sync_service: Callable[[], Any]
    planned_calendar_repair_service: Callable[[], Any]


@dataclass(frozen=True)
class SelectedWorkoutControls:
    redactor: Callable[[str], str]
    lock: Any
    wait_seconds: float
    provider_resync_gate: ProviderResyncGate


class SelectedWorkoutSyncAssembly:
    """Create selected-workout sync from its three cohesive sync owners."""

    @dataclass(frozen=True)
    class Inputs:
        providers: SelectedWorkoutProviders
        controls: SelectedWorkoutControls

    def __init__(
        self,
        *,
        dependencies: SelectedWorkoutSyncAssembly.Inputs,
    ) -> None:
        providers = dependencies.providers
        controls = dependencies.controls
        self._config = providers.config
        self._database_manager = providers.database_manager
        self._workout_library_sync_service = providers.workout_library_sync_service
        self._planned_calendar_sync_service = providers.planned_calendar_sync_service
        self._planned_calendar_repair_service = (
            providers.planned_calendar_repair_service
        )
        self._redactor = controls.redactor
        self._lock = controls.lock
        self._wait_seconds = controls.wait_seconds
        self._provider_resync_gate = controls.provider_resync_gate

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
