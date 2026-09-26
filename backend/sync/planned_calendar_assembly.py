"""Composition for planned-calendar synchronization and repair."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.reconcile import PlannedUnitSyncStateWriter


class PlannedCalendarSyncAssembly:
    """Create normal planned-calendar sync and exact-identity repair services."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        database_manager: Callable[[], DatabaseManager],
        intervals_client: Callable[[], Any],
        state_writer: Callable[[], PlannedUnitSyncStateWriter],
        utc_now: Callable[[], str],
        today: Callable[[], date],
        future_days: int,
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._intervals_client = intervals_client
        self._state_writer = state_writer
        self._utc_now = utc_now
        self._today = today
        self._future_days = future_days

    def sync_service(self) -> PlannedCalendarSyncService:
        """Create the normal single-unit calendar push use case."""
        return PlannedCalendarSyncService(
            self._config(),
            self._database_manager(),
            self._intervals_client,
            self._state_writer(),
            self._utc_now,
            self._today,
        )

    def repair_service(self) -> PlannedCalendarRepairService:
        """Create the exact-identity planned-calendar repair use case."""
        return PlannedCalendarRepairService(
            self._config(),
            self._database_manager(),
            self._intervals_client,
            self._state_writer(),
            self._utc_now,
            self._today,
            self._future_days,
        )
