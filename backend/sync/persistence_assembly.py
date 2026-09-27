"""Composition for provider synchronization persistence."""

from __future__ import annotations

from collections.abc import Callable

from backend.athlete.clock import AthleteLocalClock
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.sync.daily import DailySyncMarkerService
from backend.sync.state import SyncStateRepository


class SyncPersistenceAssembly:
    """Create fresh persistence services over the active database manager."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        key_values: KeyValueRepository,
        snapshots: SnapshotRepository,
        utc_now: Callable[[], str],
        athlete_clock: Callable[[], AthleteLocalClock],
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._snapshots = snapshots
        self._utc_now = utc_now
        self._athlete_clock = athlete_clock

    def state_repository(self) -> SyncStateRepository:
        """Create sync persistence bound to the current manager."""
        return SyncStateRepository(
            self._database_manager(), self._key_values, self._snapshots, self._utc_now
        )

    def daily_markers(self) -> DailySyncMarkerService:
        """Create daily markers bound to the current manager and athlete clock."""
        return DailySyncMarkerService(
            self._database_manager(), self._key_values, self._athlete_clock().now
        )
