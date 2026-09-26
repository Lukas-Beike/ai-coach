"""Composition for planned-unit sync persistence and reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from backend.db import DatabaseManager
from backend.observability import Redactor
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.sync.planned_units import RemotePlannedUnitReconciler
from backend.sync.reconcile import PlannedUnitSyncStateWriter


class PlannedUnitSyncAssembly:
    """Create the state writer and remote-unit reconciliation use case."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], DatabaseManager],
        planned_unit_service: Callable[[], PlannedUnitService],
        planning_revision_service: PlanningRevisionService,
        redactor: Redactor,
        utc_now: Callable[[], str],
        today: Callable[[], date],
    ) -> None:
        self._database_manager = database_manager
        self._planned_unit_service = planned_unit_service
        self._planning_revision_service = planning_revision_service
        self._redactor = redactor
        self._utc_now = utc_now
        self._today = today

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
