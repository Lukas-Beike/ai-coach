"""Build the local planning services from the application context."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any

from backend.app.context import AppContext
from backend.athlete.checkins import CHECKIN_TEXT_LIMITS
from backend.db.repositories import (
    CompetitionRepository,
    PlanAdjustmentRepository,
    PlanningStateRepository,
    TrainingPlanRepository,
)
from backend.performance.source_policy import preferences_from_profile
from backend.planning import adaptive as planning_adaptive
from backend.planning import changes as planning_changes
from backend.planning.adaptive_preview_service import (
    AdaptivePreviewLimits,
    AdaptiveReplanPreviewService,
)
from backend.planning.block_review import block_review, last_completed_test
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.competition_service import CompetitionService
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.planning.illness_return_signals import overnight_reader
from backend.planning.leg_strength import strength_expected
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.local_plan_creation_service import (
    LocalTrainingPlanCreationService,
)
from backend.planning.plan_guard_service import (
    LAST_TEST_DAYS,
    BriefHistory,
    PlanGuardService,
    read_completed,
    read_lessons,
    read_load_thresholds,
    read_progress,
    recent_illness,
)
from backend.planning.planned_unit_load import PlannedUnitEstimator
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.replacement_service import (
    StructuredTrainingPlanReplacementService,
)
from backend.planning.run_hr_cap import profile_run_caps
from backend.planning.season_preparation import season_preparation
from backend.planning.state_service import StructuredTrainingStateService
from backend.planning.training_plans import TrainingPlanService
from backend.providers import calendar as calendar_provider
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events


@dataclass(frozen=True)
class PlanningDataServices:
    competition: Callable[[], CompetitionService]
    training_plan: Callable[[], TrainingPlanService]
    planned_unit: Callable[[], PlannedUnitService]
    workout_library: Callable[[], WorkoutLibraryService]
    adaptive_apply: Callable[[], planning_adaptive.AdaptiveReplanApplyService]


@dataclass(frozen=True)
class PlanningWorkflowServices:
    calendar_conflict_service: Callable[[], CalendarConflictService]
    workout_library_plan_service: Callable[[], WorkoutLibraryPlanService]
    local_plan_creation_service: Callable[[], LocalTrainingPlanCreationService]
    daily_planning_context_service: Callable[[], DailyPlanningContextService]
    structured_training_state_service: Callable[[], StructuredTrainingStateService]
    structured_training_change_validator: Callable[
        [], planning_changes.StructuredTrainingChangeValidator
    ]
    structured_training_change_service: Callable[
        [], planning_changes.StructuredTrainingChangeService
    ]
    structured_training_plan_replacement_service: Callable[
        [], StructuredTrainingPlanReplacementService
    ]
    adaptive_replan_preview_service: Callable[[], AdaptiveReplanPreviewService]
    # Pure planning reads the training reports compose (performance may not import planning).
    block_review: Callable[..., dict[str, Any]]
    last_completed_test: Callable[[Mapping[str, Any] | None], str | None]
    season_preparation: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class PlanGuardServices:
    plan_guard_service: Callable[[], PlanGuardService]
    planned_unit_estimator: Callable[[], PlannedUnitEstimator]


def _publish_changed(topic: str) -> None:
    runtime_events.STATE_EVENT_BUFFER.publish(topic, {"status": "changed"})


def build_planning_data(ctx: AppContext) -> PlanningDataServices:
    """Fresh services per call over the current database."""
    competitions = CompetitionRepository()
    training_plans = TrainingPlanRepository()
    plan_adjustments = PlanAdjustmentRepository()

    def local_date() -> Any:
        return ctx.clock.now().date()

    def competition() -> CompetitionService:
        return CompetitionService(
            ctx.database(),
            competitions,
            runtime_clock.utc_now,
            local_date,
        )

    def training_plan() -> TrainingPlanService:
        return TrainingPlanService(
            ctx.database(),
            training_plans,
            ctx.key_values,
            ctx.planning_revision,
            runtime_events.STATE_EVENT_BUFFER,
            runtime_clock.utc_now,
        )

    def planned_unit() -> PlannedUnitService:
        return PlannedUnitService(
            ctx.database(),
            ctx.planning_revision,
            runtime_clock.utc_now,
            local_date,
            uuid.uuid4,
            ctx.redactor.redact_text,
            ctx.planning_workflows.calendar_conflict_service(),
            partial(_publish_changed, "coach"),
            lambda db, payloads: ctx.run_lthr.resync(db, payloads),
        )

    def workout_library() -> WorkoutLibraryService:
        return WorkoutLibraryService(
            ctx.database(),
            runtime_clock.utc_now,
            uuid.uuid4,
            partial(_publish_changed, "coach"),
        )

    def adaptive_apply() -> planning_adaptive.AdaptiveReplanApplyService:
        return planning_adaptive.AdaptiveReplanApplyService(
            ctx.database(),
            plan_adjustments,
            ctx.planning_revision,
            local_date,
            runtime_clock.utc_now,
            ctx.planning_workflows.calendar_conflict_service(),
        )

    return PlanningDataServices(
        competition, training_plan, planned_unit, workout_library, adaptive_apply
    )


def build_planning_workflows(ctx: AppContext) -> PlanningWorkflowServices:
    """Fresh planning reads, local mutations and adaptive previews per call."""
    plan_state = PlanningStateRepository()
    training_plans = TrainingPlanRepository()
    plan_adjustments = PlanAdjustmentRepository()
    calendar_window_days = calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS
    checkin_text_limit = CHECKIN_TEXT_LIMITS["illness"]

    def local_date() -> Any:
        return ctx.clock.now().date()

    def observation_reader() -> Any:
        return ctx.canonical_read

    def source_preferences(db: Any) -> Any:
        return preferences_from_profile(ctx.athlete.profile().get_from_db(db))

    def calendar_conflict_service() -> CalendarConflictService:
        return CalendarConflictService(ctx.database(), ctx.external_calendar.reader())

    def workout_library_plan_service() -> WorkoutLibraryPlanService:
        return WorkoutLibraryPlanService(
            ctx.database(),
            ctx.planning.planned_unit(),
            calendar_conflict_service(),
            partial(_publish_changed, "coach"),
        )

    def local_plan_creation_service() -> LocalTrainingPlanCreationService:
        return LocalTrainingPlanCreationService(
            ctx.database(),
            training_plans,
            ctx.planning.planned_unit(),
            ctx.planning.workout_library(),
            calendar_conflict_service(),
            ctx.planning_revision,
            local_date,
            runtime_clock.utc_now,
            uuid.uuid4,
            ctx.logger,
        )

    def daily_planning_context_service() -> DailyPlanningContextService:
        return DailyPlanningContextService(
            ctx.database(),
            ctx.key_values,
            ctx.athlete.checkin(),
            ctx.external_calendar.reader(),
            ctx.morning_body_battery_service(),
            ctx.athlete.activity_feedback(),
            local_date,
            calendar_window_days,
            observation_reader,
            source_preferences,
            timezone=lambda: str(ctx.athlete.profile().get().get("timezone") or "UTC"),
        )

    def structured_training_state_service() -> StructuredTrainingStateService:
        return StructuredTrainingStateService(
            ctx.database(),
            plan_state,
            ctx.planning.competition(),
            ctx.planning.training_plan(),
            ctx.coach_conversation.dialogue_read_service().artifact_refs,
            ctx.sync_job_queue.service().list,
            local_date,
        )

    def structured_training_change_validator() -> (
        planning_changes.StructuredTrainingChangeValidator
    ):
        return planning_changes.StructuredTrainingChangeValidator(
            plan_state, calendar_conflict_service()
        )

    def structured_training_change_service() -> (
        planning_changes.StructuredTrainingChangeService
    ):
        return planning_changes.StructuredTrainingChangeService(
            ctx.database(),
            structured_training_change_validator(),
            planning_changes.StructuredTrainingPlanResolver(training_plans),
            ctx.planning.planned_unit(),
            ctx.planning_revision,
            ctx.planning.training_plan(),
            local_date,
            planning_changes.TRAINING_CHANGE_LIMIT,
            partial(_publish_changed, "planning"),
        )

    def structured_training_plan_replacement_service() -> (
        StructuredTrainingPlanReplacementService
    ):
        return StructuredTrainingPlanReplacementService(
            ctx.database(),
            plan_state,
            ctx.planning_revision,
            training_plans,
            ctx.key_values,
            calendar_conflict_service(),
            ctx.planning.planned_unit(),
            local_date,
            runtime_clock.utc_now,
            uuid.uuid4,
        )

    def adaptive_replan_preview_service() -> AdaptiveReplanPreviewService:
        return AdaptiveReplanPreviewService(
            ctx.database(),
            plan_adjustments,
            ctx.athlete.checkin(),
            ctx.planning.planned_unit(),
            ctx.external_calendar.reader(),
            ctx.weather.service(),
            local_date,
            runtime_clock.utc_now,
            uuid.uuid4,
            AdaptivePreviewLimits(
                calendar_window_days,
                checkin_text_limit,
                planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS,
                planning_adaptive.WEATHER_ADAPTIVE_MAX_MINUTES,
            ),
            lambda: profile_run_caps(ctx.athlete.profile().get()),
            overnight_reader(
                ctx.database(), observation_reader, source_preferences, local_date
            ),
        )

    return PlanningWorkflowServices(
        calendar_conflict_service,
        workout_library_plan_service,
        local_plan_creation_service,
        daily_planning_context_service,
        structured_training_state_service,
        structured_training_change_validator,
        structured_training_change_service,
        structured_training_plan_replacement_service,
        adaptive_replan_preview_service,
        block_review,
        last_completed_test,
        season_preparation,
    )


def build_plan_guard(ctx: AppContext) -> PlanGuardServices:
    """Plan checks and planning brief over the current local state, fresh per call."""

    def local_date() -> Any:
        return ctx.clock.now().date()

    def source_preferences(db: Any) -> Any:
        return preferences_from_profile(ctx.athlete.profile().get_from_db(db))

    def thresholds() -> Any:
        return read_load_thresholds(
            ctx.database(),
            ctx.canonical_read,
            local_date(),
            ctx.athlete.zones().configurations(),
            source_preferences,
        )

    def planned_unit_estimator() -> PlannedUnitEstimator:
        return PlannedUnitEstimator(
            database_manager=ctx.database,
            observation_reader=lambda: ctx.canonical_read,
            zone_configurations=lambda: ctx.athlete.zones().configurations(),
            today=local_date,
            source_preferences=source_preferences,
        )

    def block_lessons() -> list[dict[str, object]]:
        """Lessons of the last 4 whole weeks for the planning brief."""
        reports = ctx.performance.training_reports()
        return reports.report.block_review(
            {}, reports.timezone(), with_curves=False
        ).get("lessons", [])

    def plan_guard_service() -> PlanGuardService:
        guard = PlanGuardService(
            estimate_unit=planned_unit_estimator(),
            planned_units=lambda: ctx.planning.planned_unit().list(
                1000, future_only=True
            ),
            completed_activities=lambda: read_completed(
                ctx.database(), ctx.canonical_read, local_date()
            ),
            competitions=lambda: ctx.planning.competition().list(),
            illness=lambda: recent_illness(
                ctx.athlete.checkin().list(10),
                local_date(),
                (
                    ctx.planning_workflows.adaptive_replan_preview_service().latest_illness_pause()
                    or (None, None)
                )[1],
            ),
            progress=lambda: read_progress(ctx.performance.training_reports()),
            training_model=lambda: str(
                ctx.athlete.profile().get().get("training_model") or ""
            ),
            profile=lambda: ctx.athlete.profile().get(),
            today=local_date,
            thresholds=thresholds,
            expects_strength=lambda: strength_expected(
                str(
                    ctx.athlete.profile().get().get("training_preferences_strength")
                    or ""
                ),
                ctx.planning.competition().list(),
                local_date(),
            ),
            calendar_events=lambda: (
                ctx.external_calendar.reader().list_events_in_window(56)
            ),
            history=BriefHistory(
                lessons=lambda: read_lessons(block_lessons),
                recent_units=lambda: ctx.planning.planned_unit().list(
                    1000,
                    future_only=True,
                    since=local_date() - timedelta(days=LAST_TEST_DAYS),
                ),
                recent_completed=lambda: read_completed(
                    ctx.database(),
                    ctx.canonical_read,
                    local_date(),
                    days=LAST_TEST_DAYS,
                ),
            ),
        ).with_return_stage(
            lambda: (
                ctx.planning_workflows.adaptive_replan_preview_service().enforced_return_stage()
            )
        )
        # Units come only from the athlete's library templates (#2379).
        return guard.with_templates(
            lambda: {
                str(item["id"]): item
                for item in ctx.planning.workout_library().list(1000)
                if not item.get("date")
            }
        )

    return PlanGuardServices(plan_guard_service, planned_unit_estimator)
