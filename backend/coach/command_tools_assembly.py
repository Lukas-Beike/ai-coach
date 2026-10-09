"""Composition for the Coach commands delegated through tool dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.sync_tools import CoachSyncToolService


@dataclass(frozen=True)
class CoachSyncAuthorityTools:
    sync_job_queue: Callable[[], Any]
    planning_authority: Callable[[], Any]
    sync_conflict_commands: Callable[[], Any]
    structured_plan_sync: Callable[[], Any]


@dataclass(frozen=True)
class CoachSyncMutationTools:
    plan_repair_manifest: Callable[[], Any]
    plan_push_command: Callable[[], Any]
    provider_refresh_command: Callable[[], Any]
    duplicate_activity: Callable[[], Any]


@dataclass(frozen=True)
class CoachSyncProvider:
    intervals_client: Callable[[], Any]


@dataclass(frozen=True)
class CoachAthleteToolFactories:
    checkin_service: Callable[[], Any]
    activity_feedback_service: Callable[[], Any]
    competition_service: Callable[[], Any]
    nutrition_diary_service: Callable[[], Any]
    nutrition_meal_library_service: Callable[[], Any]
    equipment_service: Callable[[], Any] | None = None


@dataclass(frozen=True)
class CoachProfileToolDependencies:
    profile_service: Callable[[], Any]
    database_manager: Callable[[], Any]
    database_lock: Any


class CoachCommandToolsAssembly:
    """Create fresh Coach sync and athlete mutation tool services."""

    def __init__(
        self,
        *,
        sync_authority: CoachSyncAuthorityTools,
        sync_mutations: CoachSyncMutationTools,
        sync_provider: CoachSyncProvider,
        athlete_tools: CoachAthleteToolFactories,
        profile_tools: CoachProfileToolDependencies,
    ) -> None:
        self._sync_authority = sync_authority
        self._sync_mutations = sync_mutations
        self._sync_provider = sync_provider
        self._athlete_tools = athlete_tools
        self._profile_tools = profile_tools

    def sync_tool_service(self) -> CoachSyncToolService:
        return CoachSyncToolService(
            self._sync_authority.sync_job_queue(),
            self._sync_authority.planning_authority(),
            self._sync_authority.sync_conflict_commands(),
            self._sync_authority.structured_plan_sync(),
            self._sync_mutations.plan_repair_manifest(),
            self._sync_mutations.plan_push_command(),
            self._sync_mutations.provider_refresh_command(),
            duplicate_activity=self._sync_mutations.duplicate_activity(),
            intervals_client_factory=self._sync_provider.intervals_client,
            nutrition_diary=self._athlete_tools.nutrition_diary_service(),
        )

    def athlete_record_tool_service(self) -> CoachAthleteRecordToolService:
        return CoachAthleteRecordToolService(
            self._athlete_tools.checkin_service(),
            self._athlete_tools.activity_feedback_service(),
            self._athlete_tools.competition_service(),
            self._athlete_tools.nutrition_diary_service(),
            self._athlete_tools.nutrition_meal_library_service(),
            equipment=self._athlete_tools.equipment_service()
            if self._athlete_tools.equipment_service
            else None,
        )

    def profile_update_service(self) -> CoachProfileUpdateService:
        return CoachProfileUpdateService(
            self._profile_tools.profile_service(),
            self._profile_tools.database_manager(),
            self._profile_tools.database_lock,
        )
