"""Composition for planned-calendar synchronization and repair."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.config import Config
from backend.db import DatabaseManager
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.reconcile import PlannedUnitSyncStateWriter
from backend.sync.workout_export import WorkoutExportPort


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
    # The run threshold HR in effect on a unit's date, which resolves a stored
    # heart-rate cap (percent) to the bpm range Garmin needs; and the key/value
    # store that remembers the range sent per unit.
    run_lthr_for: Callable[[Mapping[str, Any]], float | None] = lambda _unit: None
    key_values: Any = None


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
        dependencies: PlannedCalendarSyncAssembly.Inputs,
    ) -> None:
        provider = dependencies.provider
        local = dependencies.local_state
        self._config = provider.config
        self._database_manager = provider.database_manager
        self._intervals_client = provider.intervals_client
        self._state_writer = local.state_writer
        self._utc_now = local.utc_now
        self._today = local.today
        self._run_lthr_for = local.run_lthr_for
        self._key_values = local.key_values
        self._future_days = dependencies.future_days

    def sync_service(self) -> PlannedCalendarSyncService:
        """Create the normal single-unit calendar push use case."""
        return PlannedCalendarSyncService(
            self._config(),
            self._database_manager(),
            self._export_port(),
            self._state_writer(),
            self._utc_now,
            self._today,
            run_lthr_for=self._run_lthr_for,
            key_values=self._key_values,
        )

    def repair_service(self) -> PlannedCalendarRepairService:
        """Create the exact-identity planned-calendar repair use case."""
        return PlannedCalendarRepairService(
            self._database_manager(),
            self._export_port(),
            self._state_writer(),
            self._utc_now,
            self._today,
            self._future_days,
            run_lthr_for=self._run_lthr_for,
            key_values=self._key_values,
        )

    def _export_port(self) -> WorkoutExportPort:
        """Bind the Intervals.icu export target; the client resolves per call."""
        return IntervalsWorkoutExport(self._intervals_client)
