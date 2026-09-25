"""Route structured Coach tools to their concrete use-case owners."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.library_plan_tools import CoachLibraryPlanToolService
from backend.coach.plan_artifact_tools import CoachPlanArtifactToolService
from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.planning_change_tools import CoachPlanningChangeToolService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.read_tools import CoachReadToolService
from backend.coach.sync_tools import COACH_SYNC_TOOL_NAMES, CoachSyncToolService
from backend.coach.training_template_tools import TrainingTemplateToolService
from backend.errors import AppError


class CoachToolDispatchService:
    """Own routing and unknown-tool projection; domain services own effects."""

    def __init__(
        self,
        read_tools: Callable[[], CoachReadToolService],
        profile_update: Callable[[], CoachProfileUpdateService],
        athlete_records: Callable[[], CoachAthleteRecordToolService],
        plan_artifacts: CoachPlanArtifactToolService,
        planning_changes: CoachPlanningChangeToolService,
        training_templates: TrainingTemplateToolService,
        library_plans: Callable[[], CoachLibraryPlanToolService],
        sync_tools: Callable[[], CoachSyncToolService],
        planning_actions: CoachPlanningActionToolService,
    ) -> None:
        self._read_tools = read_tools
        self._profile_update = profile_update
        self._athlete_records = athlete_records
        self._plan_artifacts = plan_artifacts
        self._planning_changes = planning_changes
        self._training_templates = training_templates
        self._library_plans = library_plans
        self._sync_tools = sync_tools
        self._planning_actions = planning_actions

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        intent: dict[str, Any],
        conversation_id: str,
        client_turn_id: str,
        session_csrf_hash: str,
        sync_job_ids: list[str],
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        read_result = self._read_tools().execute(name, arguments)
        if read_result is not None:
            return read_result
        if name == "update_profile":
            return self._profile_update().apply(arguments, intent)
        athlete_result = self._athlete_records().execute(name, arguments, intent)
        if athlete_result is not None:
            return athlete_result
        if name in {"stage_training_plan", "commit_training_plan"}:
            result = self._plan_artifacts.execute(
                name, arguments, intent, conversation_id, client_turn_id
            )
            if result is not None:
                return result
        if name in {"replace_training_plan", "apply_training_changes"}:
            result = self._planning_changes.execute(name, arguments, intent)
            if result is not None:
                return result
        if name == "manage_training_templates":
            return self._training_templates.execute(arguments, intent)
        if name == "apply_workout_library_plan":
            return self._library_plans().execute(arguments, intent)
        if name in COACH_SYNC_TOOL_NAMES:
            sync_result = self._sync_tools().execute(
                name,
                arguments,
                intent=intent,
                sync_job_ids=sync_job_ids,
                cancel_event=cancel_event,
            )
            if sync_result is not None:
                return sync_result
        planning_result = self._planning_actions.execute(
            name, arguments, intent, client_turn_id, session_csrf_hash
        )
        if planning_result is not None:
            return planning_result
        raise AppError(400, "Unbekanntes Coach-Werkzeug.", reason="unknown_coach_tool")
