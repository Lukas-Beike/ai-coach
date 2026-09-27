"""Composition for explicit sync and workout-plan commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.sync.authority import PlanningAuthorityService
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.adaptive import IllnessPauseSyncService


@dataclass(frozen=True)
class SyncCommandCore:
    database_manager: Callable[[], Any]
    queue_service: Callable[[], Any]
    intervals_sync: Callable[[], Any]
    planned_unit_service: Callable[[], Any]
    competition_service: Callable[[], Any]
    workout_library_sync_state: Callable[[], Any]
    planning_revision: Any
    utc_now: Callable[[], Any]
    training_change_limit: int
    all_sync_days: int


@dataclass(frozen=True)
class IllnessPauseDependencies:
    config: Callable[[], Any]
    intervals_client: Callable[[], Any]
    adaptive_replan_apply: Callable[[], Any]
    adaptive_replan_preview: Callable[[], Any]
    redactor: Any
    today: Callable[[], Any]


class SyncCommandAssembly:
    """Create fresh command services over the shared sync and planning owners."""

    def __init__(
        self,
        *,
        core: SyncCommandCore,
        illness_pause: IllnessPauseDependencies,
    ) -> None:
        self._core = core
        self._illness_pause = illness_pause

    def illness_pause(self) -> IllnessPauseSyncService:
        return IllnessPauseSyncService(
            self._illness_pause.config(), self._illness_pause.intervals_client(),
            adaptive_replan_apply_service=self._illness_pause.adaptive_replan_apply(),
            competition_service=self._core.competition_service(),
            adaptive_replan_preview_service=self._illness_pause.adaptive_replan_preview(),
            redactor=self._illness_pause.redactor,
            today=self._illness_pause.today,
        )

    def provider_refresh(self) -> ProviderRefreshCommandService:
        return ProviderRefreshCommandService(
            self._core.queue_service(), self._core.intervals_sync(), self._core.all_sync_days
        )

    def conflicts(self) -> SyncConflictCommandService:
        return SyncConflictCommandService(
            self._core.database_manager(), self._core.planned_unit_service(),
            self._core.competition_service(), self._core.queue_service(),
        )

    def plan_push(self) -> PlanPushCommandService:
        return PlanPushCommandService(self._core.queue_service())

    def authority(self) -> PlanningAuthorityService:
        return PlanningAuthorityService(
            self._core.database_manager(), self._core.workout_library_sync_state(),
            self._core.planning_revision, self._core.utc_now,
        )

    def structured_plan_sync(self) -> StructuredPlanSyncService:
        return StructuredPlanSyncService(
            self._core.database_manager(), self.authority(), self.plan_push(),
            self._core.training_change_limit,
        )

    def repair_manifest(self) -> PlanRepairManifestService:
        return PlanRepairManifestService(
            self._core.database_manager(), self.authority()
        )
