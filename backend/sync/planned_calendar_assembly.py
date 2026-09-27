"""Composition for planned-calendar synchronization and repair."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.reconcile import PlannedUnitSyncStateWriter


@dataclass(frozen=True)
class PlannedCalendarProvider:
    config: Callable[[], Config]
    database_manager: Callable[[], DatabaseManager]
    intervals_client: Callable[[], Any]


@dataclass(frozen=True)
class PlannedCalendarLocalState:
    state_writer: Callable[[], PlannedUnitSyncStateWriter]
    utc_now: Callable[[], str]
    today: Callable[[], date]


class PlannedCalendarSyncAssembly:
    """Create normal planned-calendar sync and exact-identity repair services."""

    @dataclass(frozen=True)
    class Inputs:
        provider: PlannedCalendarProvider
        local_state: PlannedCalendarLocalState
        future_days: int

    def __init__(
        self,
        *,
        dependencies: "PlannedCalendarSyncAssembly.Inputs",
    ) -> None:
        provider = dependencies.provider
        local = dependencies.local_state
        self._config = provider.config
        self._database_manager = provider.database_manager
        self._intervals_client = provider.intervals_client
        self._state_writer = local.state_writer
        self._utc_now = local.utc_now
        self._today = local.today
        self._future_days = dependencies.future_days

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
