"""Composition for the structured Coach tool dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.library_plan_tools import CoachLibraryPlanToolService
from backend.coach.plan_artifact_tools import CoachPlanArtifactToolService
from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.planning_change_tools import CoachPlanningChangeToolService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.read_tools import CoachReadToolService
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.training_template_tools import TrainingTemplateToolService
from backend.db.manager import DatabaseManager
from backend.history.undo_service import HistoryUndoService
from backend.planning.training_plans import TrainingPlanService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService
from backend.planning.replacement_service import StructuredTrainingPlanReplacementService
from backend.planning import changes as planning_changes
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.coach.proposals import CoachProposalCreationService


class CoachToolDispatchAssembly:
    """Create fresh routing services while retaining deferred tool factories."""

    def __init__(
        self,
        *,
        read_tools: Callable[[], CoachReadToolService],
        profile_update: Callable[[], CoachProfileUpdateService],
        athlete_records: Callable[[], CoachAthleteRecordToolService],
        training_plan_artifacts: Callable[[], TrainingPlanArtifactService],
        training_plan_replacement: Callable[[], StructuredTrainingPlanReplacementService],
        training_changes: Callable[[], planning_changes.StructuredTrainingChangeService],
        database_manager: Callable[[], DatabaseManager],
        database_lock: Any,
        workout_library_service: Callable[[], WorkoutLibraryService],
        library_plan_tools: Callable[[], CoachLibraryPlanToolService],
        sync_tools: Callable[[], CoachSyncToolService],
        adaptive_preview: Callable[[], AdaptiveReplanPreviewService],
        adaptive_apply: Callable[[], CoachAdaptiveApplyService],
        training_plan_service: Callable[[], TrainingPlanService],
        history_undo: Callable[[], HistoryUndoService],
        proposal_creation: Callable[[], CoachProposalCreationService],
    ) -> None:
        self._read_tools = read_tools
        self._profile_update = profile_update
        self._athlete_records = athlete_records
        self._training_plan_artifacts = training_plan_artifacts
        self._training_plan_replacement = training_plan_replacement
        self._training_changes = training_changes
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._workout_library_service = workout_library_service
        self._library_plan_tools = library_plan_tools
        self._sync_tools = sync_tools
        self._adaptive_preview = adaptive_preview
        self._adaptive_apply = adaptive_apply
        self._training_plan_service = training_plan_service
        self._history_undo = history_undo
        self._proposal_creation = proposal_creation

    def service(self) -> CoachToolDispatchService:
        return CoachToolDispatchService(
            self._read_tools,
            self._profile_update,
            self._athlete_records,
            CoachPlanArtifactToolService(self._training_plan_artifacts),
            CoachPlanningChangeToolService(
                self._training_plan_replacement, self._training_changes
            ),
            TrainingTemplateToolService(
                self._database_manager, self._database_lock, self._workout_library_service
            ),
            self._library_plan_tools,
            self._sync_tools,
            CoachPlanningActionToolService(
                self._adaptive_preview,
                self._adaptive_apply,
                self._training_plan_service,
                self._history_undo,
                self._proposal_creation,
            ),
        )
