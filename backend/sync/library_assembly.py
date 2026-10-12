"""Composition for workout-library provider synchronization."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.config import Config
from backend.db import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.observability import Redactor
from backend.planning.library_service import WorkoutLibraryService
from backend.runtime.events import StateEventBuffer
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from backend.sync.library import (
    WorkoutLibraryRefreshService,
    WorkoutLibraryRemoteReconciler,
    WorkoutLibrarySyncService,
    WorkoutLibrarySyncStateService,
)
from backend.sync.workout_export import WorkoutLibraryExportPort

# Intervals.icu is the only registered library export target for now; another
# provider registers its adapter here and is chosen by ``export_port(target)``.
DEFAULT_LIBRARY_EXPORT_TARGET = ProviderId.INTERVALS
_LIBRARY_EXPORT_TARGETS: dict[
    ProviderId, Callable[[Callable[[], Any]], WorkoutLibraryExportPort]
] = {ProviderId.INTERVALS: IntervalsWorkoutExport}


@dataclass(frozen=True)
class WorkoutLibraryProvider:
    config: Callable[[], Config]
    database_manager: Callable[[], DatabaseManager]
    intervals_client: Callable[[], Any]
    workout_library_service: Callable[[], WorkoutLibraryService]
    calendar_conflict_service: Callable[[], Any] | None = None


@dataclass(frozen=True)
class WorkoutLibraryState:
    key_values: KeyValueRepository
    event_buffer: StateEventBuffer
    redactor: Redactor
    utc_now: Callable[[], str]
    local_today: Callable[[], date] | None = None


class WorkoutLibrarySyncAssembly:
    """Create independent workout-library refresh and sync use cases."""

    @dataclass(frozen=True)
    class Inputs:
        provider: WorkoutLibraryProvider
        state: WorkoutLibraryState
        uuid_factory: Callable[[], uuid.UUID | str]

    def __init__(
        self,
        *,
        dependencies: "WorkoutLibrarySyncAssembly.Inputs",  # noqa: UP037
    ) -> None:
        provider = dependencies.provider
        state = dependencies.state
        self._config = provider.config
        self._database_manager = provider.database_manager
        self._intervals_client = provider.intervals_client
        self._workout_library_service = provider.workout_library_service
        self._calendar_conflict_service = provider.calendar_conflict_service
        self._key_values = state.key_values
        self._event_buffer = state.event_buffer
        self._redactor = state.redactor
        self._utc_now = state.utc_now
        self._local_today = state.local_today
        self._uuid_factory = dependencies.uuid_factory

    def export_port(
        self, target: ProviderId = DEFAULT_LIBRARY_EXPORT_TARGET
    ) -> WorkoutLibraryExportPort:
        """Select the library export target; the client resolves per call."""
        factory = _LIBRARY_EXPORT_TARGETS.get(target)
        port = factory(self._intervals_client) if factory is not None else None
        if port is None or not port.capabilities.library:
            raise ValueError(
                f"No workout-library export target is registered: {target}"
            )
        return port

    def sync_state_service(self) -> WorkoutLibrarySyncStateService:
        """Create local sync-state reads and writes."""
        return WorkoutLibrarySyncStateService(
            self._database_manager(),
            self._redactor,
            self._key_values,
            self._utc_now,
        )

    def remote_reconciler(self) -> WorkoutLibraryRemoteReconciler:
        """Create local reconciliation for an already-read remote library."""
        return WorkoutLibraryRemoteReconciler(
            self._database_manager(), self._utc_now, self._uuid_factory
        )

    def refresh_service(self) -> WorkoutLibraryRefreshService:
        """Create the read-only initial workout-library refresh use case."""
        return WorkoutLibraryRefreshService(
            self._config(),
            self._database_manager(),
            self.export_port(),
            self.remote_reconciler(),
            self._workout_library_service(),
            self.sync_state_service(),
            self._key_values,
            self._event_buffer,
            self._utc_now,
        )

    def sync_service(self) -> WorkoutLibrarySyncService:
        """Create explicit single-entry remote synchronization."""
        return WorkoutLibrarySyncService(
            self._config(),
            self.export_port(),
            self.sync_state_service(),
            self._calendar_conflict_service()
            if self._calendar_conflict_service
            else None,
            local_today=self._local_today,
        )
