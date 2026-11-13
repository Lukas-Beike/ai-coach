"""Build the public read projections the HTTP routes serve."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from backend.calendar import local as calendar_local
from backend.canonical.records import Observation
from backend.http_api.bootstrap_state import (
    PublicBootstrapDependencies,
    PublicBootstrapService,
)
from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService
from backend.http_api.public_weather import PublicWeatherStateService
from backend.http_api.state_versions import StateVersionService
from backend.performance.canonical_current import read_zone_thresholds
from backend.performance.canonical_inputs import (
    CanonicalPerformanceSource,
    resolve_reader,
)
from backend.performance.season_inputs import SeasonSource
from backend.performance.source_policy import (
    SourcePreferences,
    preferences_from_profile,
)
from backend.planning import season as planning_season
from backend.planning.compact_activities import ActivitySummarySource
from backend.sync import intervals_state
from backend.sync.adaptive import AdaptivePreviewFollowupService
from backend.sync.library import workout_library_sync_running
from backend.sync.status import SyncPublicStateService
from backend.weather.recommendations import PLANNED_WORKOUT_LABEL


@dataclass(frozen=True)
class PublicStateServices:
    bootstrap_service: Callable[[], PublicBootstrapService]
    plan_state_service: Callable[[], PublicPlanStateService]
    weather_state_service: Callable[[], PublicWeatherStateService]
    performance_state_service: Callable[[], PublicPerformanceStateService]
    feedback_state_service: Callable[[], PublicFeedbackStateService]
    sync_public_state_service: Callable[[], SyncPublicStateService]
    canonical_performance_source: Callable[[], CanonicalPerformanceSource]
    season_source: Callable[[], SeasonSource]


def build_public_state(
    # The application context (backend.app.context.AppContext). This layer may
    # not import backend.app, so the parameter stays untyped here.
    ctx: Any,
    *,
    key_value_service: Callable[[], Any],
    provider_credentials: Callable[[], Any],
    provider_resync: Callable[[], Any],
    running_probes: Mapping[str, Callable[[], bool]],
    sync_period_defaults: Callable[[], Any],
    all_sync_days: int,
    external_calendar_window_days: Callable[[], int],
) -> PublicStateServices:
    """Public read projections, each service fresh per call over the context.

    Owners are read from the context when a service is built, so owners the
    context receives later (the canonical read, the performance reports) are found.
    """

    def source_preferences(db: Any) -> SourcePreferences:
        return preferences_from_profile(ctx.athlete.profile().get_from_db(db))

    def canonical_performance_source() -> CanonicalPerformanceSource:
        return CanonicalPerformanceSource(
            ctx.database,
            lambda: ctx.canonical_read,
            serving=lambda: ctx.canonical_read,
            activity_summaries=lambda: ctx.canonical_read,
            coverage=lambda: ctx.canonical_read,
            source_preferences=source_preferences,
        )

    def plan_zone_thresholds(db: Any) -> tuple[Observation, ...]:
        """The plan-zone thresholds inside the plan's read."""
        return read_zone_thresholds(
            resolve_reader(ctx.canonical_read, db),
            db,
            as_of=ctx.clock.now().date(),
            preferences=source_preferences(db),
        )

    def state_version_service() -> StateVersionService:
        return StateVersionService(
            ctx.database(), key_value_service(), ctx.athlete.profile()
        )

    def sync_public_state_service() -> SyncPublicStateService:
        return SyncPublicStateService(
            ctx.config(),
            ctx.database(),
            ctx.key_values,
            ctx.provider_sync.freshness_service(),
            ctx.athlete.profile(),
            ctx.garmin.sync_state_service(),
            ctx.maintenance,
            ctx.sync_job_queue.service(),
            state_version_service(),
            running_probes=running_probes,
        )

    def performance_state_service() -> PublicPerformanceStateService:
        garmin = ctx.garmin
        athlete = ctx.athlete
        return PublicPerformanceStateService(
            garmin.payload_service(),
            athlete.profile(),
            garmin.projection_service(),
            lambda: ctx.clock.now().date(),
            canonical_performance_source(),
            session_feedback=partial(
                athlete.activity_feedback().for_activity_ids, sessions_only=True
            ),
            now=ctx.clock.now,
            zone_configurations=athlete.zones().configurations,
            lt1_session_records=lambda days: ctx.performance.curve_records(days),
        )

    def bootstrap_service() -> PublicBootstrapService:
        planning = ctx.planning
        athlete = ctx.athlete
        calendar = ctx.external_calendar
        garmin = ctx.garmin
        return PublicBootstrapService(
            PublicBootstrapDependencies(
                database_manager=ctx.database,
                database_lock=ctx.database_lock,
                config=ctx.config(),
                app_name=ctx.app_name,
                app_version=ctx.app_version,
                key_values=key_value_service(),
                sync_state_repository=ctx.sync_persistence.state_repository,
                planned_unit_service=planning.planned_unit,
                competition_service=planning.competition,
                external_calendar_reader=calendar.reader,
                profile_service=athlete.profile,
                provider_freshness_service=ctx.provider_sync.freshness_service,
                garmin_sync_state_service=garmin.sync_state_service,
                garmin_sync_service=garmin.sync_service,
                sync_job_queue_service=ctx.sync_job_queue.service,
                state_version_service=state_version_service,
                coach_message_service=ctx.coach_conversation.message_service,
                local_calendar_events=calendar_local.local_calendar_events,
                planning_state=planning_season.planning_state,
                adaptive_replan_preview_service=ctx.planning_workflows.adaptive_replan_preview_service,
                external_calendar_sync_service=calendar.sync_service,
                external_calendar_window_days=external_calendar_window_days(),
                garmin_projection_service=garmin.projection_service,
                diagnostic_capture=ctx.diagnostic_capture,
                intervals_public_state=intervals_state.public_state,
                workout_library_sync_running=workout_library_sync_running,
                workout_library_sync_state_service=ctx.workout_library_sync.sync_state_service,
                full_provider_resync_service=provider_resync().full_resync_service,
                sync_public_state_service=sync_public_state_service,
                sync_period_defaults=sync_period_defaults(),
                all_sync_days=all_sync_days,
                settings=ctx.settings,
                local_date=lambda: ctx.clock.now().date(),
                morning_checkin_state_service=ctx.coach_local.morning_checkin_state_service,
                coach_quick_actions_service=ctx.coach_local.quick_actions_service,
                provider_state_service=ctx.provider_state,
                provider_credentials=provider_credentials,
                threshold_warnings=lambda: athlete.zones().threshold_warnings(),
            )
        )

    def plan_state_service() -> PublicPlanStateService:
        planning = ctx.planning
        athlete = ctx.athlete
        calendar = ctx.external_calendar
        workflows = ctx.planning_workflows
        return PublicPlanStateService(
            PublicPlanDependencies(
                planned_units=planning.planned_unit(),
                activity_feedback=athlete.activity_feedback(),
                weather=ctx.weather.service(),
                adaptive_followup=AdaptivePreviewFollowupService(
                    workflows.adaptive_replan_preview_service(), ctx.logger
                ),
                database_manager_factory=ctx.database,
                key_values=ctx.key_values,
                training_plans=planning.training_plan(),
                external_calendar=calendar.reader(),
                external_calendar_sync=calendar.sync_service(),
                daily_context=workflows.daily_planning_context_service(),
                checkins=athlete.checkin(),
                competitions=planning.competition(),
                adaptive_preview=workflows.adaptive_replan_preview_service(),
                coach_quick_actions=ctx.coach_local.quick_actions_service(),
                today=lambda: ctx.clock.now().date(),
                external_calendar_configured=bool(ctx.config().calendar_ical_url),
                external_calendar_window_days=external_calendar_window_days(),
                default_workout_name=PLANNED_WORKOUT_LABEL,
                activity_rows=ActivitySummarySource(
                    ctx.database, lambda: ctx.canonical_read
                ),
                zone_configurations=athlete.zones().configurations,
                sport_thresholds=plan_zone_thresholds,
                template_names=lambda: {
                    str(item["id"]): str(item.get("name") or "")
                    for item in planning.workout_library().list(
                        1000, include_archived=True
                    )
                },
            )
        )

    return PublicStateServices(
        bootstrap_service=bootstrap_service,
        plan_state_service=plan_state_service,
        weather_state_service=lambda: PublicWeatherStateService(ctx.weather.service()),
        performance_state_service=performance_state_service,
        feedback_state_service=lambda: PublicFeedbackStateService(
            ctx.athlete.checkin(), ctx.athlete.activity_feedback()
        ),
        sync_public_state_service=sync_public_state_service,
        canonical_performance_source=canonical_performance_source,
        season_source=lambda: SeasonSource(
            ctx.database, lambda: ctx.canonical_read, lambda: ctx.canonical_read
        ),
    )
