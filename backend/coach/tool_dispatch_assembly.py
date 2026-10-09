"""Composition for the structured Coach tool dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.library_plan_tools import CoachLibraryPlanToolService
from backend.coach.plan_artifact_tools import CoachPlanArtifactToolService
from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.planning_change_tools import CoachPlanningChangeToolService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.read_tools import CoachReadToolService
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.training_template_tools import TrainingTemplateToolService
from backend.db.manager import DatabaseManager
from backend.history.undo_service import HistoryUndoService
from backend.planning import changes as planning_changes
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.replacement_service import (
    StructuredTrainingPlanReplacementService,
)
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService
from backend.planning.training_plans import TrainingPlanService


@dataclass(frozen=True)
class CoachReadToolOwners:
    read_tools: Callable[[], CoachReadToolService]
    profile_update: Callable[[], CoachProfileUpdateService]
    athlete_records: Callable[[], CoachAthleteRecordToolService]


@dataclass(frozen=True)
class CoachPlanningToolOwners:
    training_plan_artifacts: Callable[[], TrainingPlanArtifactService]
    training_plan_replacement: Callable[[], StructuredTrainingPlanReplacementService]
    training_changes: Callable[[], planning_changes.StructuredTrainingChangeService]
    database_manager: Callable[[], DatabaseManager]
    database_lock: Any
    workout_library_service: Callable[[], WorkoutLibraryService]
    training_plan_service: Callable[[], TrainingPlanService]


@dataclass(frozen=True)
class CoachSyncToolOwners:
    library_plan_tools: Callable[[], CoachLibraryPlanToolService]
    sync_tools: Callable[[], CoachSyncToolService]
    history_undo: Callable[[], HistoryUndoService]


@dataclass(frozen=True)
class CoachProposalToolOwners:
    adaptive_preview: Callable[[], AdaptiveReplanPreviewService]
    adaptive_apply: Callable[[], CoachAdaptiveApplyService]
    proposal_creation: Callable[[], CoachProposalCreationService]


class CoachToolDispatchAssembly:
    """Own one stateless dispatcher; factories keep manager-bound services fresh."""

    @dataclass(frozen=True)
    class Inputs:
        reads: CoachReadToolOwners
        planning: CoachPlanningToolOwners
        sync: CoachSyncToolOwners
        proposals: CoachProposalToolOwners

    def __init__(self, *, dependencies: CoachToolDispatchAssembly.Inputs) -> None:
        reads = dependencies.reads
        planning = dependencies.planning
        sync = dependencies.sync
        proposals = dependencies.proposals
        self._read_tools = reads.read_tools
        self._profile_update = reads.profile_update
        self._athlete_records = reads.athlete_records
        self._training_plan_artifacts = planning.training_plan_artifacts
        self._training_plan_replacement = planning.training_plan_replacement
        self._training_changes = planning.training_changes
        self._database_manager = planning.database_manager
        self._database_lock = planning.database_lock
        self._workout_library_service = planning.workout_library_service
        self._training_plan_service = planning.training_plan_service
        self._library_plan_tools = sync.library_plan_tools
        self._sync_tools = sync.sync_tools
        self._history_undo = sync.history_undo
        self._adaptive_preview = proposals.adaptive_preview
        self._adaptive_apply = proposals.adaptive_apply
        self._proposal_creation = proposals.proposal_creation
        self._service: CoachToolDispatchService | None = None

    def service(self) -> CoachToolDispatchService:
        if self._service is None:
            self._service = CoachToolDispatchService(
                self._read_tools,
                self._profile_update,
                self._athlete_records,
                CoachPlanArtifactToolService(self._training_plan_artifacts),
                CoachPlanningChangeToolService(
                    self._training_plan_replacement, self._training_changes
                ),
                TrainingTemplateToolService(
                    self._database_manager,
                    self._database_lock,
                    self._workout_library_service,
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
        return self._service
