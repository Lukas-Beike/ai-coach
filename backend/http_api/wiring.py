"""Build the public read projections and the HTTP API the routes serve."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from backend.backup.database import MAX_BACKUP_BYTES
from backend.calendar import local as calendar_local
from backend.canonical.records import Observation
from backend.coach import attachments as coach_attachments
from backend.coach import streams as coach_streams
from backend.coach.turn_undo import CoachTurnUndoService
from backend.diagnostics.readiness_probe import ReadinessProbeService
from backend.errors import INTERNAL_SERVER_ERROR
from backend.http_api.activity_route_post import ActivityRoutePostRoutes
from backend.http_api.analysis import AnalysisRoutes
from backend.http_api.athlete_get import AthleteGetRoutes
from backend.http_api.athlete_put import AthletePutRoutes
from backend.http_api.auth_post import AuthPostRoutes
from backend.http_api.bootstrap_state import (
    PublicBootstrapDependencies,
    PublicBootstrapService,
)
from backend.http_api.calendar_decision_post import CalendarDecisionPostRoutes
from backend.http_api.chat_cancel_post import ChatCancelPostRoutes
from backend.http_api.chat_page import ChatHistoryPageService
from backend.http_api.chat_post import ChatPostRoutes
from backend.http_api.chat_stream import CoachChatStreamTransport
from backend.http_api.coach_actions_post import CoachActionsPostRoutes
from backend.http_api.coach_get import CoachGetRoutes
from backend.http_api.credentials_put import CredentialsPutRoutes
from backend.http_api.diagnostics_delete_post import DiagnosticsDeletePostRoutes
from backend.http_api.diagnostics_get import DiagnosticsGetRoutes
from backend.http_api.equipment_post import EquipmentPostRoutes
from backend.http_api.export_streams import ExportStreamTransport
from backend.http_api.feedback_post import FeedbackPostRoutes
from backend.http_api.first_threshold_post import FirstThresholdPostRoutes
from backend.http_api.garmin_post import GarminPostRoutes
from backend.http_api.handler import (
    HttpRequestHandlerDependencies,
    create_request_handler,
)
from backend.http_api.history_undo_post import HistoryUndoPostRoutes
from backend.http_api.library_page import LibraryPageService
from backend.http_api.metric_export_post import MetricExportPostRoutes
from backend.http_api.nutrition import (
    NutritionGetRoutes,
    NutritionPostRoutes,
    NutritionPutRoutes,
)
from backend.http_api.planned_unit_focus_post import PlannedUnitFocusPostRoutes
from backend.http_api.planning_get import PlanningGetRoutes
from backend.http_api.privacy_delete_post import PrivacyDeletePostRoutes
from backend.http_api.privacy_get import PrivacyGetRoutes
from backend.http_api.privacy_restore_post import PrivacyRestorePostRoutes
from backend.http_api.provider_connections import (
    ProviderConnectionGetRoutes,
    ProviderConnectionPostRoutes,
)
from backend.http_api.public_get import PublicGetRoutes
from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService
from backend.http_api.public_weather import PublicWeatherStateService
from backend.http_api.readiness import ReadinessService
from backend.http_api.response_transport import HttpResponseTransport
from backend.http_api.route_table import RouteTable
from backend.http_api.settings_put import SettingsPutRoutes
from backend.http_api.state_events_get import StateEventsGetRoutes
from backend.http_api.state_events_transport import StateEventTransport
from backend.http_api.state_versions import StateVersionService
from backend.http_api.static_assets import StaticAssetService
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.http_api.sync_get import SyncGetRoutes
from backend.http_api.transcribe_post import TranscribePostRoutes
from backend.http_api.wahoo import WahooGetRoutes, WahooPostRoutes
from backend.nutrition.macro_context import macro_context
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
from backend.planning.race_results import with_race_results
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance
from backend.sync import intervals_state
from backend.sync.adaptive import AdaptivePreviewFollowupService
from backend.sync.analysis_refresh import AnalysisRefreshService
from backend.sync.library import workout_library_sync_running
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
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


@dataclass(frozen=True)
class HttpApi:
    """The route table, the shared response transport and the lazy services."""

    route_table: RouteTable
    response_transport: HttpResponseTransport
    public_get_routes: PublicGetRoutes
    planning_get_routes: PlanningGetRoutes
    analysis_routes: AnalysisRoutes
    history_undo_post_routes: HistoryUndoPostRoutes
    transcribe_post_routes: TranscribePostRoutes
    chat_stream_transport: CoachChatStreamTransport
    sync_command_post_route: SyncCommandPostRoute
    readiness_service: Callable[[], ReadinessService]
    export_stream_transport: Callable[[], ExportStreamTransport]
    library_page_service: Callable[[], LibraryPageService]
    chat_history_page_service: Callable[[], ChatHistoryPageService]
    sync_command_endpoint: Callable[[], SyncCommandEndpoint]
    request_handler_class: Callable[[], type[BaseHTTPRequestHandler]]


def _local_today(ctx: Any) -> Any:
    return ctx.clock.now().date()


def _session_rpe_load(ctx: Any, activity_id: str) -> Any:
    return ctx.activity_reads.activity_read().session_rpe_load(
        activity_id, _local_today(ctx)
    )


def _readiness_service(ctx: Any) -> ReadinessService:
    return ReadinessService(
        ctx.database,
        ctx.data_dir(),
        runtime_maintenance.MAINTENANCE_GATE,
        ReadinessProbeService(),
    )


def _export_stream_transport(ctx: Any) -> ExportStreamTransport:
    return ExportStreamTransport(
        ctx.backup.backup_service, ctx.privacy.archive_export_service
    )


def _library_page_service(ctx: Any) -> LibraryPageService:
    wahoo = ctx.wahoo.library_state
    return LibraryPageService(
        ctx.database(),
        ctx.planning.workout_library(),
        wahoo_states=lambda rows: wahoo().states(rows),
    )


def _chat_history_page_service(ctx: Any, maximum: int) -> ChatHistoryPageService:
    return ChatHistoryPageService(
        ctx.coach_conversation.history_service(),
        ctx.coach_proposals.read_service(),
        maximum=maximum,
    )


def _sync_command_endpoint(
    ctx: Any,
    provider_configured: Mapping[str, Callable[[], bool]],
    period_defaults: Any,
    all_sync_days: int,
) -> SyncCommandEndpoint:
    return SyncCommandEndpoint(
        ctx.sync_job_queue.service(),
        ctx.sync_persistence.state_repository(),
        ctx.provider_resync.full_resync_service(),
        ctx.ids,
        period_defaults,
        all_sync_days,
        provider_configured=lambda provider_id: provider_configured[provider_id](),
    )


def _coach_routes(
    ctx: Any,
    chat_history_page_service: Callable[[], ChatHistoryPageService],
    response_timeout_seconds: int,
) -> tuple[Any, ...]:
    """Coach chat, proposals and voice transcription routes."""
    receipts = ctx.coach_turns.command_receipt_service
    submissions = ctx.coach_background_jobs.job_submission_service
    max_request_bytes = coach_attachments.MAX_REQUEST_BYTES
    return (
        CoachGetRoutes(chat_history_page_service, receipts, submissions),
        ChatPostRoutes(
            lambda: ctx.coach_conversation.reset_service(), max_request_bytes
        ),
        CoachChatStreamTransport(
            coach_streams.CHAT_STREAM_REGISTRY,
            submissions,
            receipts,
            ctx.redactor.redact_text,
            ctx.logger,
            max_request_bytes=max_request_bytes,
            response_timeout_seconds=response_timeout_seconds,
            maintenance_pending=lambda: bool(ctx.maintenance.state()["active"]),
        ),
        CoachActionsPostRoutes(
            ctx.coach_proposals.confirmation_service,
            ctx.coach_proposals.execution_service,
        ),
        ChatCancelPostRoutes(ctx.coach_background_jobs.cancellation_service),
        TranscribePostRoutes(ctx.model_transport.audio_transcription_client),
    )


def _read_routes(
    ctx: Any,
    session_auth_service: Callable[[], Any],
    readiness_service: Callable[[], ReadinessService],
    library_page_service: Callable[[], LibraryPageService],
    all_sync_days: int,
) -> tuple[Any, ...]:
    """Routes that only read: public state, planning, athlete, sync, diagnostics."""
    public = ctx.public_state
    athlete = ctx.athlete
    activity_read = ctx.activity_reads.activity_read
    return (
        PublicGetRoutes(
            ctx.maintenance,
            readiness_service,
            session_auth_service,
            public.bootstrap_service,
        ),
        PlanningGetRoutes(
            public.plan_state_service,
            public.weather_state_service,
            library_page_service,
        ),
        SyncGetRoutes(
            ctx.sync_job_queue.service,
            public.sync_public_state_service,
            activity_read,
            lambda: _local_today(ctx),
            all_sync_days,
            athlete.session_corrections,
            ctx.provider_resync.full_resync_service,
            dict(DEFAULT_PROVIDER_REGISTRY.full_resync_routes()),
        ),
        StateEventsGetRoutes(
            session_auth_service,
            StateEventTransport(runtime_events.STATE_EVENT_BUFFER),
        ),
        AthleteGetRoutes(
            public.performance_state_service,
            athlete.profile,
            ctx.planning.competition,
            public.feedback_state_service,
            ctx.coach_context.preview_service,
            ctx.settings,
            athlete.zones,
            race_results=lambda competitions: with_race_results(
                competitions,
                _local_today(ctx),
                activity_read().summaries_on_days,
            ),
            first_threshold_service=athlete.first_threshold,
        ),
        DiagnosticsGetRoutes(
            ctx.diagnostics.recent_log_entries_service,
            ctx.diagnostics.report_service,
        ),
        AnalysisRoutes(
            ctx.performance.training_reports,
            lambda: AnalysisRefreshService(
                ctx.garmin.targeted_refresh_service,
                lambda: _local_today(ctx),
                ctx.wahoo.sync_service,
            ),
        ),
    )


def _athlete_write_routes(
    ctx: Any, session_auth_service: Callable[[], Any]
) -> tuple[Any, ...]:
    """Session and CSRF routes that change settings, the profile and records."""
    athlete = ctx.athlete
    history_undo = ctx.history.undo_service
    rpe_load = partial(_session_rpe_load, ctx)
    return (
        SettingsPutRoutes(ctx.settings),
        AthletePutRoutes(
            athlete.profile,
            ctx.database,
            athlete.zones,
            lambda profile, revision, deadline: ctx.garmin.body_export(
                athlete.profile()
            ).export(profile, revision, deadline),
        ),
        AuthPostRoutes(session_auth_service, ctx.maintenance),
        FeedbackPostRoutes(
            athlete.activity_feedback, rpe_load, athlete.session_corrections
        ),
        HistoryUndoPostRoutes(
            history_undo,
            CoachTurnUndoService(ctx.database, history_undo),
            rpe_load,
        ),
        PlannedUnitFocusPostRoutes(ctx.planning.planned_unit, ctx.database),
        CredentialsPutRoutes(ctx.provider_credential_service, session_auth_service),
        EquipmentPostRoutes(athlete.equipment),
        FirstThresholdPostRoutes(
            athlete.first_threshold, athlete.profile, ctx.database
        ),
        ActivityRoutePostRoutes(lambda: ctx.activity_routes),
        CalendarDecisionPostRoutes(lambda: ctx.external_calendar.decisions()),
    )


def _domain_routes(
    ctx: Any,
    session_auth_service: Callable[[], Any],
    export_stream_transport: Callable[[], ExportStreamTransport],
    sync_command_endpoint: Callable[[], SyncCommandEndpoint],
) -> tuple[Any, ...]:
    """Privacy, nutrition, sync command and provider connection routes."""
    nutrition = ctx.nutrition
    public = ctx.public_state
    privacy_delete = ctx.privacy.delete_service
    wahoo_connection = ctx.wahoo_connection.service
    return (
        PrivacyGetRoutes(export_stream_transport, privacy_delete),
        NutritionGetRoutes(
            nutrition.diary_service,
            nutrition.meal_library_service,
            ctx.clock.now,
            partial(
                macro_context,
                public.performance_state_service,
                public.plan_state_service,
                ctx.athlete.profile,
            ),
        ),
        NutritionPutRoutes(nutrition.meal_library_service),
        PrivacyRestorePostRoutes(
            session_auth_service, ctx.backup.restore_service, MAX_BACKUP_BYTES
        ),
        NutritionPostRoutes(
            nutrition.diary_service,
            nutrition.meal_library_service,
            ctx.garmin.targeted_refresh_service,
            ctx.clock.now,
        ),
        SyncCommandPostRoute(sync_command_endpoint),
        PrivacyDeletePostRoutes(privacy_delete),
        DiagnosticsDeletePostRoutes(
            ctx.diagnostics.recent_log_entries_service,
            ctx.diagnostics.report_service,
        ),
        WahooGetRoutes(wahoo_connection, ctx.maintenance),
        WahooPostRoutes(wahoo_connection),
        ProviderConnectionGetRoutes(lambda: ctx.provider_connection_checks),
        ProviderConnectionPostRoutes(lambda: ctx.provider_connection_checks),
        MetricExportPostRoutes(lambda: ctx.metric_export),
        GarminPostRoutes(lambda: ctx.garmin_login),
    )


def build_http_api(
    # The application context (backend.app.context.AppContext). This layer may
    # not import backend.app, so the parameter stays untyped here.
    ctx: Any,
    *,
    session_auth_service: Callable[[], Any],
    audio: Any,
    max_body_bytes: int,
    max_audio_body_bytes: int,
    public_dir: Path,
    chat_page_max: int,
    response_timeout_seconds: int,
    sync_period_defaults: Any,
    all_sync_days: int,
    provider_configured: Mapping[str, Callable[[], bool]],
) -> HttpApi:
    """The HTTP routes and the request handler class over the context.

    The routes take most owners from the context while they are built, so every
    owner they use must be on the context before this call; the page, export,
    readiness and sync services read theirs on each use. The handler class is
    built fresh on every call from the live version, logger and maintenance gate.
    """
    readiness_service = partial(_readiness_service, ctx)
    export_stream_transport = partial(_export_stream_transport, ctx)
    library_page_service = partial(_library_page_service, ctx)
    chat_history_page_service = partial(_chat_history_page_service, ctx, chat_page_max)
    sync_command_endpoint = partial(
        _sync_command_endpoint,
        ctx,
        provider_configured,
        sync_period_defaults,
        all_sync_days,
    )
    (
        coach_get,
        chat_post,
        chat_stream_transport,
        coach_actions_post,
        chat_cancel_post,
        transcribe_post,
    ) = _coach_routes(ctx, chat_history_page_service, response_timeout_seconds)
    (
        public_get,
        planning_get,
        sync_get,
        state_events_get,
        athlete_get,
        diagnostics_get,
        analysis,
    ) = _read_routes(
        ctx,
        session_auth_service,
        readiness_service,
        library_page_service,
        all_sync_days,
    )
    (
        settings_put,
        athlete_put,
        auth_post,
        feedback_post,
        history_undo_post,
        planned_unit_focus_post,
        credentials_put,
        equipment_post,
        first_threshold_post,
        activity_route_post,
        calendar_decision_post,
    ) = _athlete_write_routes(ctx, session_auth_service)
    (
        privacy_get,
        nutrition_get,
        nutrition_put,
        privacy_restore_post,
        nutrition_post,
        sync_command_post,
        privacy_delete_post,
        diagnostics_delete_post,
        wahoo_get,
        wahoo_post,
        provider_connection_get,
        provider_connection_post,
        metric_export_post,
        garmin_post,
    ) = _domain_routes(
        ctx, session_auth_service, export_stream_transport, sync_command_endpoint
    )
    route_table = RouteTable(
        route
        for owner in (
            public_get,
            planning_get,
            sync_get,
            state_events_get,
            coach_get,
            athlete_get,
            diagnostics_get,
            privacy_get,
            nutrition_get,
            analysis,
            settings_put,
            athlete_put,
            nutrition_put,
            auth_post,
            privacy_restore_post,
            chat_cancel_post,
            coach_actions_post,
            chat_post,
            transcribe_post,
            feedback_post,
            chat_stream_transport,
            sync_command_post,
            history_undo_post,
            privacy_delete_post,
            diagnostics_delete_post,
            nutrition_post,
            planned_unit_focus_post,
            credentials_put,
            wahoo_get,
            wahoo_post,
            provider_connection_get,
            provider_connection_post,
            equipment_post,
            metric_export_post,
            garmin_post,
            first_threshold_post,
            activity_route_post,
            calendar_decision_post,
        )
        for route in owner.routes()
    )
    response_transport = HttpResponseTransport()

    def request_handler_class() -> type[BaseHTTPRequestHandler]:
        return create_request_handler(
            HttpRequestHandlerDependencies(
                app_version=ctx.app_version,
                logger=ctx.logger,
                session_auth_service=session_auth_service,
                route_table=route_table,
                response_transport=response_transport,
                maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
                redact_text=ctx.redactor.redact_text,
                internal_server_error=INTERNAL_SERVER_ERROR,
                max_body_bytes=max_body_bytes,
                max_audio_body_bytes=max_audio_body_bytes,
                voice_audio_types=audio.VOICE_AUDIO_TYPES,
                normalize_audio_type=audio.normalized_audio_type,
                static_asset_service=StaticAssetService(public_dir),
            )
        )

    return HttpApi(
        route_table=route_table,
        response_transport=response_transport,
        public_get_routes=public_get,
        planning_get_routes=planning_get,
        analysis_routes=analysis,
        history_undo_post_routes=history_undo_post,
        transcribe_post_routes=transcribe_post,
        chat_stream_transport=chat_stream_transport,
        sync_command_post_route=sync_command_post,
        readiness_service=readiness_service,
        export_stream_transport=export_stream_transport,
        library_page_service=library_page_service,
        chat_history_page_service=chat_history_page_service,
        sync_command_endpoint=sync_command_endpoint,
        request_handler_class=request_handler_class,
    )
