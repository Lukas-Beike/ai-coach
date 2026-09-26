"""Composition for the Coach commands delegated through tool dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.sync_tools import CoachSyncToolService


class CoachCommandToolsAssembly:
    """Create fresh Coach sync and athlete mutation tool services."""

    def __init__(
        self,
        *,
        sync_job_queue: Callable[[], Any],
        planning_authority: Callable[[], Any],
        sync_conflict_commands: Callable[[], Any],
        structured_plan_sync: Callable[[], Any],
        plan_repair_manifest: Callable[[], Any],
        plan_push_command: Callable[[], Any],
        provider_refresh_command: Callable[[], Any],
        checkin_service: Callable[[], Any],
        activity_feedback_service: Callable[[], Any],
        competition_service: Callable[[], Any],
        nutrition_service: Callable[[], Any],
        profile_service: Callable[[], Any],
        database_manager: Callable[[], Any],
        database_lock: Any,
    ) -> None:
        self._sync_job_queue = sync_job_queue
        self._planning_authority = planning_authority
        self._sync_conflict_commands = sync_conflict_commands
        self._structured_plan_sync = structured_plan_sync
        self._plan_repair_manifest = plan_repair_manifest
        self._plan_push_command = plan_push_command
        self._provider_refresh_command = provider_refresh_command
        self._checkin_service = checkin_service
        self._activity_feedback_service = activity_feedback_service
        self._competition_service = competition_service
        self._nutrition_service = nutrition_service
        self._profile_service = profile_service
        self._database_manager = database_manager
        self._database_lock = database_lock

    def sync_tool_service(self) -> CoachSyncToolService:
        return CoachSyncToolService(
            self._sync_job_queue(),
            self._planning_authority(),
            self._sync_conflict_commands(),
            self._structured_plan_sync(),
            self._plan_repair_manifest(),
            self._plan_push_command(),
            self._provider_refresh_command(),
        )

    def athlete_record_tool_service(self) -> CoachAthleteRecordToolService:
        return CoachAthleteRecordToolService(
            self._checkin_service(),
            self._activity_feedback_service(),
            self._competition_service(),
            self._nutrition_service(),
        )

    def profile_update_service(self) -> CoachProfileUpdateService:
        return CoachProfileUpdateService(
            self._profile_service(), self._database_manager(), self._database_lock
        )
