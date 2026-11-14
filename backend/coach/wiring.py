"""Build the Coach conversation, local, context, read-tool and proposal services (#2102).

Every service reads the live configuration, database and domain owners from the
application context when it is built, so a configuration change or a restore
applies without a restart. A service that another Coach service needs later
(the dialogue tools, a turn) is read from the context at call time.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from backend.app.context import AppContext
from backend.coach import context as coach_context
from backend.coach import limits as coach_limits
from backend.coach import streams as coach_streams
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.coach.clarification import CoachClarificationService
from backend.coach.context import (
    CoachContextPreviewLimits,
    CoachContextPreviewService,
    CoachPerformanceContextReader,
    CoachPlanningContextReader,
    CoachQuickActionsService,
    CoachStructuredContextService,
    CoachTrainingContextService,
)
from backend.coach.conversation import (
    CoachAttachmentContextService,
    CoachConversationHistoryService,
    CoachConversationProvisionService,
    CoachConversationResetService,
    CoachMessageService,
)
from backend.coach.dialogue import CoachDialogueReadService
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.coach.morning import (
    GarminSleepObservations,
    ManualMorningCheckinService,
    MorningCheckinStateService,
)
from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.coach.proposal_read import (
    CoachProposalConfirmationService,
    CoachProposalReadService,
)
from backend.coach.read_tools import CoachReadToolService
from backend.coach.request_payload import CoachRequestPayloadService
from backend.coach.response_transport import CoachResponseTransport
from backend.db.repositories import ChatRepository
from backend.history.wiring import HistoryServices
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.source_policy import preferences_from_profile
from backend.planning.compact_activities import ActivitySummarySource
from backend.planning.wiring import PlanGuardServices
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance
from backend.weather.recommendations import PLANNED_WORKOUT_LABEL


@dataclass(frozen=True)
class CoachConversationServices:
    provision_service: Callable[[], CoachConversationProvisionService]
    reset_service: Callable[[], CoachConversationResetService]
    message_service: Callable[[], CoachMessageService]
    history_service: Callable[[], CoachConversationHistoryService]
    dialogue_read_service: Callable[[], CoachDialogueReadService]
    attachment_context_service: Callable[[], CoachAttachmentContextService]
    response_transport: Callable[[], CoachResponseTransport]


@dataclass(frozen=True)
class CoachLocalServices:
    quick_actions_service: Callable[[], CoachQuickActionsService]
    dialogue_action_service: Callable[[], CoachDialogueActionService]
    clarification_service: Callable[[], CoachClarificationService]
    manual_morning_checkin_service: Callable[[], ManualMorningCheckinService]
    morning_checkin_state_service: Callable[[], MorningCheckinStateService]


@dataclass(frozen=True)
class CoachContextServices:
    structured_context_service: Callable[[], CoachStructuredContextService]
    training_context_service: Callable[[], CoachTrainingContextService]
    request_payload_service: Callable[[], CoachRequestPayloadService]
    preview_service: Callable[[], CoachContextPreviewService]


@dataclass(frozen=True)
class CoachReadToolServices:
    read_service: Callable[[], CoachReadToolService]


@dataclass(frozen=True)
class CoachProposalServices:
    read_service: Callable[[], CoachProposalReadService]
    creation_service: Callable[[], CoachProposalCreationService]
    confirmation_service: Callable[[], CoachProposalConfirmationService]
    execution_service: Callable[[], CoachProposalExecutionService]


def athlete_today(ctx: AppContext) -> Callable[[], date]:
    """The athlete's local day, read from the live clock on each call."""

    def today() -> date:
        return ctx.clock.now().date()

    return today


def build_coach_conversation(
    ctx: AppContext, *, chat_repository: ChatRepository, conversation_lock: Any
) -> CoachConversationServices:
    """Fresh conversation services over the shared stream registry and gate lock."""
    event_buffer = runtime_events.STATE_EVENT_BUFFER
    streams = coach_streams.CHAT_STREAM_REGISTRY
    utc_now = runtime_clock.utc_now

    def provision_service() -> CoachConversationProvisionService:
        return CoachConversationProvisionService(
            ctx.database(),
            ctx.key_values,
            ctx.model_transport.openai_responses_client(),
            uuid.uuid4,
            logger=ctx.logger,
        )

    def reset_service() -> CoachConversationResetService:
        return CoachConversationResetService(
            ctx.database(),
            ctx.key_values,
            ctx.model_transport.openai_responses_client(),
            streams,
            conversation_lock,
            utc_now,
            uuid.uuid4,
            ctx.logger,
        )

    def message_service() -> CoachMessageService:
        return CoachMessageService(ctx.database(), chat_repository, event_buffer)

    def history_service() -> CoachConversationHistoryService:
        return CoachConversationHistoryService(
            ctx.database(), chat_repository, ctx.key_values
        )

    def dialogue_read_service() -> CoachDialogueReadService:
        return CoachDialogueReadService(
            ctx.database(),
            message_service(),
            ctx.key_values,
            ctx.athlete.profile(),
        )

    def attachment_context_service() -> CoachAttachmentContextService:
        return CoachAttachmentContextService(ctx.database())

    def response_transport() -> CoachResponseTransport:
        return CoachResponseTransport(
            ctx.model_transport.complete, ctx.model_transport.stream
        )

    return CoachConversationServices(
        provision_service,
        reset_service,
        message_service,
        history_service,
        dialogue_read_service,
        attachment_context_service,
        response_transport,
    )


def build_coach_local(ctx: AppContext) -> CoachLocalServices:
    """Fresh Coach-local dialogue and check-in services over the live owners."""
    local_date = athlete_today(ctx)

    def quick_actions_service() -> CoachQuickActionsService:
        return CoachQuickActionsService(
            ctx.database(),
            ctx.key_values,
            ctx.planning_workflows.adaptive_replan_preview_service(),
            local_date,
            PLANNED_WORKOUT_LABEL,
        )

    def dialogue_action_service() -> CoachDialogueActionService:
        manager = ctx.database()
        return CoachDialogueActionService(
            manager,
            ctx.sync_job_queue.service,
            CoachDialoguePlanScopeService(manager),
            local_date,
        )

    def clarification_service() -> CoachClarificationService:
        return CoachClarificationService(ctx.database(), ctx.key_values)

    def manual_morning_checkin_service() -> ManualMorningCheckinService:
        return ManualMorningCheckinService(
            ctx.garmin.sync_service(),
            ctx.garmin.payload_service(),
            ctx.morning_body_battery_service(),
            local_date,
            ctx.logger,
            observations=GarminSleepObservations(
                ctx.database(), lambda: ctx.canonical_read
            ),
        )

    def morning_checkin_state_service() -> MorningCheckinStateService:
        return MorningCheckinStateService(ctx.database(), ctx.key_values, local_date)

    return CoachLocalServices(
        quick_actions_service,
        dialogue_action_service,
        clarification_service,
        manual_morning_checkin_service,
        morning_checkin_state_service,
    )


def _context_limits() -> dict[str, Any]:
    return {
        "local_planned_limit": coach_context.COACH_LOCAL_PLANNED_LIMIT,
        "library_limit": coach_context.COACH_LIBRARY_LIMIT,
        "library_description_limit": coach_context.COACH_LIBRARY_DESCRIPTION_LIMIT,
        "section_limits": coach_context.COACH_CONTEXT_SECTION_LIMITS,
        "total_char_limit": coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT,
        "activity_limit_per_sport": coach_context.COACH_RECENT_ACTIVITIES_PER_SPORT,
        "planned_event_limit": coach_context.COACH_PLANNED_EVENT_LIMIT,
    }


def build_coach_context(
    ctx: AppContext,
    *,
    threshold_warnings: Callable[[], Any],
    plan_guard: PlanGuardServices,
) -> CoachContextServices:
    """Fresh bounded context, request and preview services; limits read per call."""
    local_date = athlete_today(ctx)

    def canonical_reader() -> Any:
        return ctx.canonical_read

    canonical = CanonicalPerformanceSource(
        database_manager=ctx.database,
        observation_reader=canonical_reader,
        serving=canonical_reader,
        activity_summaries=canonical_reader,
        coverage=canonical_reader,
        source_preferences=lambda db: preferences_from_profile(
            ctx.athlete.profile().get_from_db(db)
        ),
    )
    activity_rows = ActivitySummarySource(
        database_manager=ctx.database,
        reader=canonical_reader,
        coverage=canonical_reader,
    )

    def session_feedback(keys: list[str]) -> list[dict[str, Any]]:
        """The session-aware local feedback the load rollups' session-RPE load reads."""
        return ctx.athlete.activity_feedback().for_activity_ids(
            keys, sessions_only=True
        )

    def zone_configurations() -> Any:
        return ctx.athlete.zones().configurations()

    def lt1_session_records(days: int) -> Any:
        return ctx.performance.curve_records(days)

    def structured_context_service() -> CoachStructuredContextService:
        athlete, planning, garmin = ctx.athlete, ctx.planning, ctx.garmin
        return CoachStructuredContextService(
            athlete.checkin(),
            ctx.weather.service(),
            athlete.activity_feedback(),
            CoachPlanningContextReader(
                planning.planned_unit(),
                ctx.planning_workflows.daily_planning_context_service(),
                ctx.external_calendar.reader(),
                planning.competition(),
                planning.training_plan(),
                ctx.planning_workflows.adaptive_replan_preview_service(),
                local_date,
            ),
            CoachPerformanceContextReader(
                athlete.profile(),
                garmin.payload_service(),
                garmin.projection_service(),
                local_date,
                canonical,
                activity_rows,
                session_feedback=session_feedback,
                zone_configurations=zone_configurations,
                lt1_session_records=lt1_session_records,
            ),
            nutrition_meal_library=ctx.nutrition.meal_library_service,
            zone_configurations=zone_configurations,
            threshold_warnings=threshold_warnings,
            first_threshold_estimate=lambda: ctx.athlete.first_threshold().estimate(),
            planning_brief=lambda: plan_guard.plan_guard_service().brief(),
            today=local_date,
        )

    def training_context_service() -> CoachTrainingContextService:
        limits = _context_limits()
        return CoachTrainingContextService(
            structured_context_service(),
            ctx.planning.workout_library(),
            local_planned_limit=limits["local_planned_limit"],
            library_limit=limits["library_limit"],
            library_description_limit=limits["library_description_limit"],
            section_limits=limits["section_limits"],
            total_char_limit=limits["total_char_limit"],
            activity_limit_per_sport=limits["activity_limit_per_sport"],
            planned_event_limit=limits["planned_event_limit"],
        )

    def request_payload_service() -> CoachRequestPayloadService:
        return CoachRequestPayloadService(
            training_context_service(),
            ctx.settings,
            coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
        )

    def preview_service() -> CoachContextPreviewService:
        limits = _context_limits()
        return CoachContextPreviewService(
            ctx.coach_conversation.message_service(),
            training_context_service(),
            structured_context_service(),
            ctx.planning.workout_library(),
            CoachContextPreviewLimits(
                library_limit=limits["library_limit"],
                library_description_limit=limits["library_description_limit"],
                section_limits=limits["section_limits"],
                total_char_limit=limits["total_char_limit"],
                local_planned_limit=limits["local_planned_limit"],
                activity_limit_per_sport=limits["activity_limit_per_sport"],
                planned_event_limit=limits["planned_event_limit"],
            ),
            utc_now=lambda: datetime.now(UTC),
        )

    return CoachContextServices(
        structured_context_service,
        training_context_service,
        request_payload_service,
        preview_service,
    )


def build_coach_read_tools(
    ctx: AppContext,
    *,
    activity_read: Callable[[], Any],
    history: HistoryServices,
    plan_guard: PlanGuardServices,
) -> CoachReadToolServices:
    """Fresh read-only tool services; the activity reads come from the HTTP layer."""
    local_date = athlete_today(ctx)

    def activity_read_service() -> CoachActivityReadToolService:
        return CoachActivityReadToolService(
            activity_read(),
            ctx.garmin.payload_service(),
            ctx.athlete.profile(),
            local_date,
            ctx.performance.training_reports(),
            ctx.planning.planned_unit(),
            plan_guard.planned_unit_estimator(),
            ctx.athlete.session_corrections(),
        )

    def read_service() -> CoachReadToolService:
        return CoachReadToolService(
            ctx.athlete.profile,
            ctx.planning_workflows.structured_training_state_service,
            activity_read_service,
            ctx.planning.workout_library,
            ctx.planning.planned_unit,
            history.change_history_service,
            ctx.planning.competition,
            ctx.planning.training_plan,
            coach_limits.COACH_TRAINING_CHANGE_LIMIT,
            ctx.nutrition.diary_service,
            ctx.nutrition.meal_library_service,
            ctx.coach_context.structured_context_service,
        )

    return CoachReadToolServices(read_service)


def build_coach_proposals(
    ctx: AppContext, *, history: HistoryServices
) -> CoachProposalServices:
    """Fresh proposal services; the dispatcher is read when a proposal executes."""
    local_date = athlete_today(ctx)
    utc_now = runtime_clock.utc_now

    def now() -> float:
        return time.time()

    def read_service() -> CoachProposalReadService:
        return CoachProposalReadService(ctx.database(), now=now)

    def creation_service() -> CoachProposalCreationService:
        return CoachProposalCreationService(
            ctx.database(),
            now=now,
            utc_now=utc_now,
            uuid_factory=uuid.uuid4,
            nutrition_diary_service=ctx.nutrition.diary_service,
            today=local_date,
        )

    def confirmation_service() -> CoachProposalConfirmationService:
        return CoachProposalConfirmationService(ctx.database(), now=now)

    def execution_service() -> CoachProposalExecutionService:
        return CoachProposalExecutionService(
            ctx.database(),
            history.undo_service(),
            ctx.provider_transport.intervals_client,
            runtime_maintenance.MAINTENANCE_GATE,
            tool_dispatch_service=lambda: ctx.coach_tool_dispatch.service(),
            now=now,
            utc_now=utc_now,
        )

    return CoachProposalServices(
        read_service, creation_service, confirmation_service, execution_service
    )
