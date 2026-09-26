"""Composition for explicit sync and workout-plan commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.sync.authority import PlanningAuthorityService
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.adaptive import IllnessPauseSyncService


class SyncCommandAssembly:
    """Create fresh command services over the shared sync and planning owners."""

    def __init__(
        self,
        *,
        database_manager: Callable[[], Any],
        queue_service: Callable[[], Any],
        intervals_sync: Callable[[], Any],
        planned_unit_service: Callable[[], Any],
        competition_service: Callable[[], Any],
        workout_library_sync_state: Callable[[], Any],
        planning_revision: Any,
        utc_now: Callable[[], Any],
        training_change_limit: int,
        all_sync_days: int,
        config: Callable[[], Any],
        intervals_client: Callable[[], Any],
        adaptive_replan_apply: Callable[[], Any],
        adaptive_replan_preview: Callable[[], Any],
        redactor: Any,
        today: Callable[[], Any],
    ) -> None:
        self._database_manager = database_manager
        self._queue_service = queue_service
        self._intervals_sync = intervals_sync
        self._planned_unit_service = planned_unit_service
        self._competition_service = competition_service
        self._workout_library_sync_state = workout_library_sync_state
        self._planning_revision = planning_revision
        self._utc_now = utc_now
        self._training_change_limit = training_change_limit
        self._all_sync_days = all_sync_days
        self._config = config
        self._intervals_client = intervals_client
        self._adaptive_replan_apply = adaptive_replan_apply
        self._adaptive_replan_preview = adaptive_replan_preview
        self._redactor = redactor
        self._today = today

    def illness_pause(self) -> IllnessPauseSyncService:
        return IllnessPauseSyncService(
            self._config(), self._intervals_client(),
            adaptive_replan_apply_service=self._adaptive_replan_apply(),
            competition_service=self._competition_service(),
            adaptive_replan_preview_service=self._adaptive_replan_preview(),
            redactor=self._redactor,
            today=self._today,
        )

    def provider_refresh(self) -> ProviderRefreshCommandService:
        return ProviderRefreshCommandService(
            self._queue_service(), self._intervals_sync(), self._all_sync_days
        )

    def conflicts(self) -> SyncConflictCommandService:
        return SyncConflictCommandService(
            self._database_manager(), self._planned_unit_service(),
            self._competition_service(), self._queue_service(),
        )

    def plan_push(self) -> PlanPushCommandService:
        return PlanPushCommandService(self._queue_service())

    def authority(self) -> PlanningAuthorityService:
        return PlanningAuthorityService(
            self._database_manager(), self._workout_library_sync_state(),
            self._planning_revision, self._utc_now,
        )

    def structured_plan_sync(self) -> StructuredPlanSyncService:
        return StructuredPlanSyncService(
            self._database_manager(), self.authority(), self.plan_push(),
            self._training_change_limit,
        )

    def repair_manifest(self) -> PlanRepairManifestService:
        return PlanRepairManifestService(
            self._database_manager(), self.authority()
        )
