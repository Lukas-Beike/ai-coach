"""Composition for planned-unit sync persistence and reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from backend.db import DatabaseManager
from backend.observability import Redactor
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.sync.planned_units import RemotePlannedUnitReconciler
from backend.sync.reconcile import PlannedUnitSyncStateWriter


@dataclass(frozen=True)
class PlannedUnitOwners:
    database_manager: Callable[[], DatabaseManager]
    planned_unit_service: Callable[[], PlannedUnitService]
    planning_revision_service: PlanningRevisionService


@dataclass(frozen=True)
class PlannedUnitRuntime:
    redactor: Redactor
    utc_now: Callable[[], str]
    today: Callable[[], date]


class PlannedUnitSyncAssembly:
    """Create the state writer and remote-unit reconciliation use case."""

    @dataclass(frozen=True)
    class Inputs:
        owners: PlannedUnitOwners
        runtime: PlannedUnitRuntime

    def __init__(
        self,
        *,
        dependencies: PlannedUnitSyncAssembly.Inputs,
    ) -> None:
        self._database_manager = dependencies.owners.database_manager
        self._planned_unit_service = dependencies.owners.planned_unit_service
        self._planning_revision_service = dependencies.owners.planning_revision_service
        self._redactor = dependencies.runtime.redactor
        self._utc_now = dependencies.runtime.utc_now
        self._today = dependencies.runtime.today

    def state_writer(self) -> PlannedUnitSyncStateWriter:
        """Create the writer for planned-unit synchronization state."""
        return PlannedUnitSyncStateWriter(
            self._planning_revision_service, self._redactor
        )

    def remote_reconciler(self) -> RemotePlannedUnitReconciler:
        """Create remote planned-unit reconciliation against current state."""
        return RemotePlannedUnitReconciler(
            self._database_manager(),
            self._planned_unit_service(),
            self._planning_revision_service,
            self._utc_now,
            self._today,
        )
