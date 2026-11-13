"""Build the Coach planning, command, dispatch and tool-round services (#2102).

Like the other Coach builders, every service reads the live owners from the
application context when it is built. The dispatcher is one stateless instance
per process, created on its first use.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from backend.app.context import AppContext
from backend.coach import limits as coach_limits
from backend.coach import structured_tool_round
from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.library_plan_tools import CoachLibraryPlanToolService
from backend.coach.plan_artifact_tools import CoachPlanArtifactToolService
from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.planning_change_tools import CoachPlanningChangeToolService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundLimits,
    CoachStructuredToolRoundService,
)
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.coach.tool_replay import CoachStructuredToolReplayService
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal
from backend.coach.training_patch import CoachTrainingPatchService
from backend.coach.training_template_tools import TrainingTemplateToolService
from backend.coach.turn_write_gate import (
    CoachWriteGateService,
    build_impact_classifier,
)
from backend.coach.wiring import athlete_today
from backend.coach.write_gate import ImpactClassifier
from backend.history.wiring import HistoryServices
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService
from backend.planning.wiring import PlanGuardServices
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync.wiring import SyncCommandServices


@dataclass(frozen=True)
class CoachPlanningToolServices:
    training_plan_artifact_service: Callable[[], TrainingPlanArtifactService]
    library_plan_tool_service: Callable[[], CoachLibraryPlanToolService]
    training_patch_service: Callable[[], CoachTrainingPatchService]
    adaptive_apply_service: Callable[[], CoachAdaptiveApplyService]


@dataclass(frozen=True)
class CoachCommandToolServices:
    sync_tool_service: Callable[[], CoachSyncToolService]
    athlete_record_tool_service: Callable[[], CoachAthleteRecordToolService]
    profile_update_service: Callable[[], CoachProfileUpdateService]


@dataclass(frozen=True)
class CoachToolDispatchServices:
    service: Callable[[], CoachToolDispatchService]


@dataclass(frozen=True)
class CoachToolRoundServices:
    service: Callable[[], CoachStructuredToolRoundService]


def build_coach_planning_tools(
    ctx: AppContext,
    *,
    plan_guard: PlanGuardServices,
    sync_commands: SyncCommandServices,
) -> CoachPlanningToolServices:
    """Fresh planning mutation and local plan artifact services per call."""
    local_date = athlete_today(ctx)
    training_change_limit = coach_limits.COACH_TRAINING_CHANGE_LIMIT
    event_buffer = runtime_events.STATE_EVENT_BUFFER
    utc_now = runtime_clock.utc_now

    def training_plan_artifact_service() -> TrainingPlanArtifactService:
        return TrainingPlanArtifactService(
            ctx.database(),
            ctx.planning_workflows.local_plan_creation_service(),
            local_date,
            utc_now,
            uuid.uuid4,
        )

    def library_plan_tool_service() -> CoachLibraryPlanToolService:
        return CoachLibraryPlanToolService(
            ctx.planning_workflows.workout_library_plan_service()
        )

    def training_patch_service() -> CoachTrainingPatchService:
        workflows = ctx.planning_workflows
        return CoachTrainingPatchService(
            ctx.database(),
            ctx.database_lock,
            workflows.structured_training_change_validator(),
            workflows.structured_training_change_service(),
            workflows.local_plan_creation_service(),
            workflows.calendar_conflict_service(),
            ctx.key_values,
            event_buffer,
            local_date,
            training_change_limit,
        )

    def adaptive_apply_service() -> CoachAdaptiveApplyService:
        return CoachAdaptiveApplyService(
            ctx.planning_workflows.adaptive_replan_preview_service(),
            sync_commands.illness_pause(),
            ctx.database(),
            ctx.database_lock,
            plan_guard.plan_guard_service,
        )

    return CoachPlanningToolServices(
        training_plan_artifact_service,
        library_plan_tool_service,
        training_patch_service,
        adaptive_apply_service,
    )


def build_coach_command_tools(
    ctx: AppContext, *, sync_commands: SyncCommandServices
) -> CoachCommandToolServices:
    """Fresh sync and athlete mutation tool services per call."""

    def sync_tool_service() -> CoachSyncToolService:
        return CoachSyncToolService(
            ctx.sync_job_queue.service(),
            sync_commands.authority(),
            sync_commands.conflicts(),
            sync_commands.structured_plan_sync(),
            sync_commands.repair_manifest(),
            sync_commands.plan_push(),
            sync_commands.provider_refresh(),
            nutrition_diary=ctx.nutrition.diary_service(),
        )

    def athlete_record_tool_service() -> CoachAthleteRecordToolService:
        athlete, nutrition = ctx.athlete, ctx.nutrition
        return CoachAthleteRecordToolService(
            athlete.checkin(),
            athlete.activity_feedback(),
            ctx.planning.competition(),
            nutrition.diary_service(),
            nutrition.meal_library_service(),
            equipment=athlete.equipment(),
            session_corrections=athlete.session_corrections(),
        )

    def profile_update_service() -> CoachProfileUpdateService:
        return CoachProfileUpdateService(
            ctx.athlete.profile(), ctx.database(), ctx.database_lock
        )

    return CoachCommandToolServices(
        sync_tool_service, athlete_record_tool_service, profile_update_service
    )


def build_coach_tool_dispatch(
    ctx: AppContext, *, history: HistoryServices
) -> CoachToolDispatchServices:
    """One stateless dispatcher; its factories keep manager-bound services fresh."""

    @cache
    def service() -> CoachToolDispatchService:
        planning, workflows = ctx.planning, ctx.planning_workflows
        planning_tools = ctx.coach_planning_tools
        return CoachToolDispatchService(
            ctx.coach_read_tools.read_service,
            ctx.coach_command_tools.profile_update_service,
            ctx.coach_command_tools.athlete_record_tool_service,
            CoachPlanArtifactToolService(planning_tools.training_plan_artifact_service),
            CoachPlanningChangeToolService(
                workflows.structured_training_plan_replacement_service,
                workflows.structured_training_change_service,
            ),
            TrainingTemplateToolService(
                ctx.database, ctx.database_lock, planning.workout_library
            ),
            planning_tools.library_plan_tool_service,
            ctx.coach_command_tools.sync_tool_service,
            CoachPlanningActionToolService(
                workflows.adaptive_replan_preview_service,
                planning_tools.adaptive_apply_service,
                planning.training_plan,
                history.undo_service,
                ctx.coach_proposals.creation_service,
            ),
        )

    return CoachToolDispatchServices(service)


def build_coach_tool_rounds(
    ctx: AppContext,
    *,
    root: Path,
    read_only_tools: Collection[str],
    plan_guard: PlanGuardServices,
    sync_commands: SyncCommandServices,
) -> CoachToolRoundServices:
    """Fresh structured tool rounds; the round limits are read on each call."""
    read_only = frozenset(read_only_tools)

    def execution_service() -> CoachStructuredToolExecutionService:
        return CoachStructuredToolExecutionService(
            ctx.database(),
            ctx.database_lock,
            ctx.key_values,
            ctx.coach_local.clarification_service(),
            ctx.coach_planning_tools.training_patch_service(),
            ctx.coach_proposals.creation_service(),
            ctx.coach_tool_dispatch.service(),
            ctx.profile_mutation_coordinator,
            plan_guard.plan_guard_service,
        )

    def failure_service() -> CoachStructuredToolFailureService:
        return CoachStructuredToolFailureService(
            root,
            ctx.logger,
            frozenset(tool["name"] for tool in ctx.coach_dialogue_tools),
        )

    def replay_service() -> CoachStructuredToolReplayService:
        return CoachStructuredToolReplayService(
            ctx.database(), ctx.database_lock, read_only
        )

    def preparation_service() -> CoachStructuredToolPreparationService:
        return CoachStructuredToolPreparationService(
            ctx.coach_local.dialogue_action_service(),
            sync_commands.authority(),
            read_only,
        )

    def write_gate_service() -> CoachWriteGateService:
        def classifier(model: str) -> ImpactClassifier:
            # Same model transport (and OPENAI_BASE_URL) as the Coach turn.
            return build_impact_classifier(
                ctx.coach_conversation.response_transport().request,
                model=model,
                reasoning_effort="low",
            )

        return CoachWriteGateService(read_only, classifier, ctx.logger)

    def limits() -> CoachStructuredToolRoundLimits:
        return CoachStructuredToolRoundLimits(
            max_rounds=structured_tool_round.COACH_TOOL_MAX_ROUNDS,
            background_horizon_days=coach_limits.COACH_BACKGROUND_HORIZON_DAYS,
            default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
            long_plan_max_output_tokens=coach_limits.COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
        )

    def service() -> CoachStructuredToolRoundService:
        return CoachStructuredToolRoundService(
            ctx.database,
            ctx.database_lock,
            replay_service(),
            preparation_service(),
            execution_service(),
            failure_service(),
            CoachStructuredToolRoundJournal(ctx.coach_background_jobs.job_store()),
            ctx.coach_background_jobs.job_store(),
            ctx.coach_context.training_context_service(),
            ctx.coach_turns.structured_response_service(),
            write_gate_service(),
            limits(),
            ctx.profile_mutation_coordinator,
        )

    return CoachToolRoundServices(service)
