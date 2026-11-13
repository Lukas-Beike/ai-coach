"""Composition for explicit sync and workout-plan commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.db.repositories import KeyValueRepository
from backend.sync.adaptive import IllnessPauseSyncService
from backend.sync.authority import PlanningAuthorityService
from backend.sync.commands import (
    GarminSynchronousRefresh,
    ProviderRefreshCommandService,
    SynchronousRefresh,
    WahooSynchronousRefresh,
)
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.execution_assembly import SyncJobExecutionAssembly
from backend.sync.garmin_personal_status import sdk_write_ready
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.plan_selection import StructuredPlanSyncService

_KEY_VALUES = KeyValueRepository(lambda: "")  # reads only


@dataclass(frozen=True)
class SyncCommandCore:
    database_manager: Callable[[], Any]
    queue_service: Callable[[], Any]
    competition_service: Callable[[], Any]
    workout_library_sync_state: Callable[[], Any]
    planning_revision: Any
    utc_now: Callable[[], Any]
    training_change_limit: int
    synchronous_refreshes: Callable[[], Mapping[str, SynchronousRefresh]] = dict
    after_refresh: Callable[[Mapping[str, Any]], None] = lambda _job: None


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
            self._illness_pause.config(),
            self._illness_pause.intervals_client(),
            adaptive_replan_apply_service=self._illness_pause.adaptive_replan_apply(),
            competition_service=self._core.competition_service(),
            adaptive_replan_preview_service=self._illness_pause.adaptive_replan_preview(),
            redactor=self._illness_pause.redactor,
            today=self._illness_pause.today,
        )

    def provider_refresh(self) -> ProviderRefreshCommandService:
        return ProviderRefreshCommandService(
            self._core.queue_service(),
            self._core.synchronous_refreshes(),
            self._core.after_refresh,
        )

    def conflicts(self) -> SyncConflictCommandService:
        return SyncConflictCommandService(
            self._core.competition_service(),
            self._core.queue_service(),
        )

    def plan_push(self) -> PlanPushCommandService:
        def garmin_writable() -> bool:
            with self._core.database_manager().reader() as db:
                return sdk_write_ready(
                    self._illness_pause.config(), lambda key: _KEY_VALUES.get(db, key)
                )

        return PlanPushCommandService(self._core.queue_service(), garmin_writable)

    def authority(self) -> PlanningAuthorityService:
        return PlanningAuthorityService(
            self._core.database_manager(),
            self._core.workout_library_sync_state(),
            self._core.planning_revision,
            self._core.utc_now,
            local_today=self._illness_pause.today,
        )

    def structured_plan_sync(self) -> StructuredPlanSyncService:
        return StructuredPlanSyncService(
            self._core.database_manager(),
            self.authority(),
            self.plan_push(),
            self._core.training_change_limit,
        )

    def repair_manifest(self) -> PlanRepairManifestService:
        return PlanRepairManifestService(
            self._core.database_manager(), self.authority()
        )


def coach_synchronous_refreshes(
    jobs: SyncJobExecutionAssembly.Inputs,
) -> dict[str, SynchronousRefresh]:
    """Return the inline refreshes a waiting Coach request runs (Garmin, Wahoo)."""
    historical = jobs.historical
    all_sync_days = historical.all_sync_days
    state = jobs.state.sync_state_repository()
    return {
        GARMIN_ID: GarminSynchronousRefresh(
            jobs.garmin.sync_service(),
            jobs.garmin.morning_body_battery_service(),
            all_sync_days,
        ),
        WAHOO_ID: WahooSynchronousRefresh(
            jobs.wahoo.sync_service(),
            all_sync_days,
            stored_days=lambda: state.sync_period(
                WAHOO_ID, historical.sync_period_defaults, all_sync_days
            ),
        ),
    }
