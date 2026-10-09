from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from backend.diagnostics.readiness_probe import ReadinessProbeService
from backend.http_api.analysis import AnalysisRoutes
from backend.http_api.athlete_get import AthleteGetRoutes
from backend.http_api.athlete_put import AthletePutRoutes
from backend.http_api.auth_post import AuthPostRoutes
from backend.http_api.chat_cancel_post import ChatCancelPostRoutes
from backend.http_api.chat_page import ChatHistoryPageService
from backend.http_api.chat_post import ChatPostRoutes
from backend.http_api.chat_stream import CoachChatStreamTransport
from backend.http_api.coach_actions_post import CoachActionsPostRoutes
from backend.http_api.coach_get import CoachGetRoutes
from backend.http_api.diagnostics_delete_post import DiagnosticsDeletePostRoutes
from backend.http_api.diagnostics_get import DiagnosticsGetRoutes
from backend.http_api.equipment_post import EquipmentPostRoutes
from backend.http_api.export_streams import ExportStreamTransport
from backend.http_api.feedback_post import FeedbackPostRoutes
from backend.http_api.handler import (
    HttpRequestHandlerDependencies,
    create_request_handler,
)
from backend.http_api.history_get import HistoryGetRoutes
from backend.http_api.history_undo_post import HistoryUndoPostRoutes
from backend.http_api.library_page import LibraryPageService
from backend.http_api.nutrition import (
    NutritionGetRoutes,
    NutritionPostRoutes,
    NutritionPutRoutes,
)
from backend.http_api.planning_commands_post import PlanningCommandsPostRoutes
from backend.http_api.planning_get import PlanningGetRoutes
from backend.http_api.post_dispatch import (
    HttpAuthenticatedPostRoutes,
    HttpPostDispatcher,
)
from backend.http_api.privacy_delete_post import PrivacyDeletePostRoutes
from backend.http_api.privacy_get import PrivacyGetRoutes
from backend.http_api.privacy_restore_post import PrivacyRestorePostRoutes
from backend.http_api.public_get import PublicGetRoutes
from backend.http_api.readiness import ReadinessService
from backend.http_api.response_transport import HttpResponseTransport
from backend.http_api.route_dispatch import HttpRouteDispatcher
from backend.http_api.settings_put import SettingsPutRoutes
from backend.http_api.state_events_get import StateEventsGetRoutes
from backend.http_api.state_events_transport import StateEventTransport
from backend.http_api.static_assets import StaticAssetService
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.http_api.sync_get import SyncGetRoutes
from backend.http_api.transcribe_post import TranscribePostRoutes
from backend.performance.report_service import (
    TrainingDerivedReadService,
    TrainingProfileSelectionService,
    TrainingRecordsService,
    TrainingReportReadService,
    TrainingReportServices,
    TrainingSeasonReadService,
)


@dataclass(frozen=True)
class HttpHandlerIdentity:
    app_version: str
    logger: Any
    session_auth_service: Callable[[], Any]
    maintenance_gate: Any


@dataclass(frozen=True)
class HttpHandlerErrors:
    redact_text: Callable[[str], str]
    internal_server_error: str


@dataclass(frozen=True)
class HttpRequestBodyLimits:
    max_body_bytes: int
    max_audio_body_bytes: int


@dataclass(frozen=True)
class HttpAudioInput:
    voice_audio_types: Any
    normalize_audio_type: Callable[[str], str]


@dataclass(frozen=True)
class HttpHandlerConfiguration:
    identity: HttpHandlerIdentity
    errors: HttpHandlerErrors
    body_limits: HttpRequestBodyLimits
    audio: HttpAudioInput
    public_dir: Path


@dataclass(frozen=True)
class HttpCoreResources:
    database_manager: Callable[[], Any]
    database_lock: Callable[[], Any]
    data_dir: Callable[[], Path]
    readiness_maintenance_gate: Callable[[], Any]


@dataclass(frozen=True)
class HttpHandlerServices:
    handler_configuration: Callable[[], HttpHandlerConfiguration]
    maintenance_gate: Any
    session_auth_service: Callable[[], Any]
    settings: Any
    redact_text: Callable[[str], str]
    logger: Any


@dataclass(frozen=True)
class HttpResponseServices:
    response_transport: HttpResponseTransport
    logger: Any


@dataclass(frozen=True)
class HttpCoreServices:
    resources: HttpCoreResources
    handler: HttpHandlerServices
    response: HttpResponseServices


@dataclass(frozen=True)
class HttpCoachReadServices:
    conversation_history_service: Callable[[], Any]
    proposal_read_service: Callable[[], Any]
    chat_page_max: int
    command_receipt_service: Callable[[], Any]
    job_submission_service: Callable[[], Any]


@dataclass(frozen=True)
class HttpCoachWriteActions:
    job_cancellation_service: Callable[[], Any]
    context_preview_service: Callable[[], Any]
    proposal_creation_service: Callable[[], Any]
    proposal_confirmation_service: Callable[[], Any]
    proposal_execution_service: Callable[[], Any]
    reset_service: Callable[[], Any]
    provision_service: Callable[[], Any]
    planning_command_service: Callable[[], Any]


@dataclass(frozen=True)
class HttpCoachStreamSettings:
    max_chat_request_bytes: int
    chat_stream_registry: Any


@dataclass(frozen=True)
class HttpCoachWriteServices:
    actions: HttpCoachWriteActions
    stream: HttpCoachStreamSettings


@dataclass(frozen=True)
class HttpPublicServices:
    bootstrap: Callable[[], Any]
    plan_state: Callable[[], Any]
    weather_state: Callable[[], Any]
    performance_state: Callable[[], Any]
    feedback_state: Callable[[], Any]
    sync_state: Callable[[], Any]


@dataclass(frozen=True)
class HttpAthleteServices:
    profile: Callable[[], Any]
    competition: Callable[[], Any]
    activity_read: Callable[[], Any]
    checkin: Callable[[], Any]
    context_service: Callable[[], Any]
    clock: Any
    local_today: Callable[[], Any]
    state_event_buffer: Any
    equipment: Callable[[], Any] | None = None
    activity_feedback: Callable[[], Any] | None = None


@dataclass(frozen=True)
class HttpHistoryServices:
    change_history: Callable[[], Any]
    undo: Callable[[], Any]


@dataclass(frozen=True)
class HttpDiagnosticsServices:
    recent_logs: Callable[[], Any]
    report: Callable[[], Any]


@dataclass(frozen=True)
class HttpPrivacyServices:
    backup: Callable[[], Any]
    export: Callable[[], Any]
    monotonic: Callable[[], float]
    export_time_limit_seconds: int
    delete: Callable[[], Any]
    restore: Callable[[], Any]
    max_backup_bytes: int


@dataclass(frozen=True)
class HttpSyncServices:
    job_queue: Callable[[], Any]
    state_repository: Callable[[], Any]
    performance_refresh: Callable[[], Any]
    full_resync: Callable[[], Any]
    period_defaults: Any
    all_sync_days: int
    uuid_factory: Callable[[], str]


@dataclass(frozen=True)
class HttpNutritionServices:
    diary: Callable[[], Any]
    meal_library: Callable[[], Any]
    intervals_sync: Callable[[], Any]
    audio_transcription: Callable[[], Any]


@dataclass(frozen=True)
class HttpCoreAndTransport:
    services: HttpCoreServices
    openai_response_timeout_seconds: float


@dataclass(frozen=True)
class HttpCoachRouteServices:
    reads: HttpCoachReadServices
    writes: HttpCoachWriteServices


@dataclass(frozen=True)
class HttpReadRouteServices:
    public: HttpPublicServices
    athlete: HttpAthleteServices
    history: HttpHistoryServices
    diagnostics: HttpDiagnosticsServices
    workout_library: Callable[[], Any]


@dataclass(frozen=True)
class HttpDomainRouteServices:
    privacy: HttpPrivacyServices
    sync: HttpSyncServices
    nutrition: HttpNutritionServices


class HttpApiAssembly:
    """Own eager HTTP route composition and lazy request-handler creation."""

    @dataclass(frozen=True)
    class Inputs:
        core: HttpCoreAndTransport
        coach: HttpCoachRouteServices
        reads: HttpReadRouteServices
        domains: HttpDomainRouteServices

    def __init__(
        self,
        *,
        dependencies: HttpApiAssembly.Inputs,
    ) -> None:
        core = dependencies.core.services
        timeout = dependencies.core.openai_response_timeout_seconds
        coach_reads = dependencies.coach.reads
        coach_writes = dependencies.coach.writes.actions
        coach_stream = dependencies.coach.writes.stream
        public = dependencies.reads.public
        athlete = dependencies.reads.athlete
        history = dependencies.reads.history
        diagnostics = dependencies.reads.diagnostics
        workout_library = dependencies.reads.workout_library
        privacy = dependencies.domains.privacy
        sync = dependencies.domains.sync
        nutrition = dependencies.domains.nutrition
        resources = core.resources
        handler_services = core.handler
        handler_configuration = handler_services.handler_configuration
        maintenance_gate = handler_services.maintenance_gate
        database_manager = resources.database_manager
        database_lock = resources.database_lock
        data_dir = resources.data_dir
        readiness_maintenance_gate = resources.readiness_maintenance_gate
        session_auth_service = handler_services.session_auth_service
        settings = handler_services.settings
        redact_text = handler_services.redact_text
        http_response_transport = core.response.response_transport
        logger = core.response.logger
        conversation_history_service = coach_reads.conversation_history_service
        proposal_read_service = coach_reads.proposal_read_service
        chat_page_max = coach_reads.chat_page_max
        coach_command_receipt_service = coach_reads.command_receipt_service
        coach_job_submission_service = coach_reads.job_submission_service
        coach_job_cancellation_service = coach_writes.job_cancellation_service
        coach_context_preview_service = coach_writes.context_preview_service
        proposal_creation_service = coach_writes.proposal_creation_service
        proposal_confirmation_service = coach_writes.proposal_confirmation_service
        proposal_execution_service = coach_writes.proposal_execution_service
        coach_reset_service = coach_writes.reset_service
        coach_provision_service = coach_writes.provision_service
        max_chat_request_bytes = coach_stream.max_chat_request_bytes
        chat_stream_registry = coach_stream.chat_stream_registry
        coach_planning_command_service = coach_writes.planning_command_service
        public_bootstrap_service = public.bootstrap
        public_plan_state_service = public.plan_state
        public_weather_state_service = public.weather_state
        public_performance_state_service = public.performance_state
        public_feedback_state_service = public.feedback_state
        public_sync_state_service = public.sync_state
        profile_service = athlete.profile
        competition_service = athlete.competition
        activity_read_service = athlete.activity_read
        checkin_service = athlete.checkin
        athlete_context_service = athlete.context_service
        athlete_clock = athlete.clock
        local_today = athlete.local_today
        state_event_buffer = athlete.state_event_buffer
        change_history_service = history.change_history
        history_undo_service = history.undo
        recent_log_entries_service = diagnostics.recent_logs
        diagnostic_report_service = diagnostics.report
        backup_service = privacy.backup
        privacy_export_service = privacy.export
        monotonic = privacy.monotonic
        export_time_limit_seconds = privacy.export_time_limit_seconds
        privacy_delete_service = privacy.delete
        backup_restore_service = privacy.restore
        max_backup_bytes = privacy.max_backup_bytes
        sync_job_queue_service = sync.job_queue
        sync_state_repository = sync.state_repository
        performance_refresh_service = sync.performance_refresh
        full_provider_resync_service = sync.full_resync
        sync_period_defaults = sync.period_defaults
        all_sync_days = sync.all_sync_days
        uuid_factory = sync.uuid_factory
        diary_service = nutrition.diary
        meal_library_service = nutrition.meal_library
        audio_transcription_client = nutrition.audio_transcription
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._data_dir = data_dir
        self._readiness_maintenance_gate = readiness_maintenance_gate
        self._workout_library = workout_library
        self._conversation_history_service = conversation_history_service
        self._proposal_read_service = proposal_read_service
        self._chat_page_max = chat_page_max
        self.coach_get_routes = CoachGetRoutes(
            session_auth_service,
            self.chat_history_page_service,
            coach_command_receipt_service,
            coach_job_submission_service,
        )
        self.public_get_routes = PublicGetRoutes(
            maintenance_gate,
            self.readiness_service,
            session_auth_service,
            public_bootstrap_service,
        )
        self.planning_get_routes = PlanningGetRoutes(
            session_auth_service,
            public_plan_state_service,
            public_weather_state_service,
            self.library_page_service,
        )
        self.athlete_get_routes = AthleteGetRoutes(
            session_auth_service,
            public_performance_state_service,
            profile_service,
            competition_service,
            public_feedback_state_service,
            coach_context_preview_service,
            settings,
        )
        self.diagnostics_get_routes = DiagnosticsGetRoutes(
            session_auth_service,
            recent_log_entries_service,
            diagnostic_report_service,
        )
        self.sync_get_routes = SyncGetRoutes(
            session_auth_service,
            sync_job_queue_service,
            public_sync_state_service,
            activity_read_service,
            local_today,
            all_sync_days,
        )
        self.history_get_routes = HistoryGetRoutes(
            session_auth_service, change_history_service
        )
        report_snapshot = lambda: sync_state_repository().latest_snapshot()
        report_plan = lambda: public_plan_state_service().read(local_only=True)
        report_checkins = lambda: checkin_service().list(365)
        report_feedback = lambda: (
            athlete.activity_feedback().list(500) if athlete.activity_feedback else []
        )
        report_timezone = lambda: str(profile_service().get().get("timezone") or "UTC")
        report_recovery = lambda: (
            public_performance_state_service()
            .performance_state()["performance"]
            .get("personal_recovery", {})
        )
        report_performance = lambda: (
            public_performance_state_service().performance_state()["performance"]
        )

        def training_report_services() -> TrainingReportServices:
            records = TrainingRecordsService(
                database_manager=database_manager(),
                read_snapshot=report_snapshot,
                read_equipment=lambda: (
                    athlete.equipment().read() if athlete.equipment else {}
                ),
                read_record=lambda kind, record_id: (
                    {
                        "record_type": kind,
                        "record": athlete.equipment().read(record_id)["items"][0],
                    }
                    if kind == "equipment" and athlete.equipment
                    else {}
                ),
            )
            report_read = TrainingReportReadService(
                read_snapshot=report_snapshot,
                read_plan=report_plan,
                read_checkins=report_checkins,
                read_feedback=report_feedback,
                today=local_today,
            )
            return TrainingReportServices(
                records=records,
                profiles=TrainingProfileSelectionService(local_today),
                report=report_read,
                derived=TrainingDerivedReadService(
                    read_snapshot=report_snapshot,
                    read_checkins=report_checkins,
                    read_recovery=report_recovery,
                    read_performance=report_performance,
                    today=local_today,
                ),
                season=TrainingSeasonReadService(
                    read_snapshot=report_snapshot,
                    read_competitions=lambda: competition_service().list(100),
                    read_observations=records.observations,
                    today=local_today,
                ),
                timezone=report_timezone,
            )

        self.training_reports = training_report_services
        self.analysis_routes = AnalysisRoutes(
            session_auth_service, self.training_reports
        )
        self.history_undo_post_routes = HistoryUndoPostRoutes(
            history_undo_service,
            proposal_creation_service,
        )
        self.coach_actions_post_routes = CoachActionsPostRoutes(
            proposal_confirmation_service,
            proposal_execution_service,
        )
        self.chat_post_routes = ChatPostRoutes(
            coach_job_submission_service,
            coach_reset_service,
            max_chat_request_bytes,
        )
        self.chat_stream_transport = CoachChatStreamTransport(
            chat_stream_registry,
            coach_job_submission_service,
            coach_command_receipt_service,
            redact_text,
            logger,
            max_request_bytes=max_chat_request_bytes,
            response_timeout_seconds=timeout,
        )
        self.transcribe_post_routes = TranscribePostRoutes(
            audio_transcription_client,
        )
        self.privacy_delete_post_routes = PrivacyDeletePostRoutes(
            privacy_delete_service
        )
        self.diagnostics_delete_post_routes = DiagnosticsDeletePostRoutes(
            recent_log_entries_service,
            diagnostic_report_service,
        )
        self.privacy_get_routes = PrivacyGetRoutes(
            session_auth_service,
            self.export_stream_transport,
            privacy_delete_service,
        )
        self.state_events_get_routes = StateEventsGetRoutes(
            session_auth_service,
            StateEventTransport(state_event_buffer),
        )
        self.settings_put_routes = SettingsPutRoutes(settings)
        self.athlete_put_routes = AthletePutRoutes(
            athlete_context_service, profile_service, database_lock()
        )
        self.planning_commands_post_routes = PlanningCommandsPostRoutes(
            coach_planning_command_service,
            coach_provision_service,
        )
        self.feedback_post_routes = FeedbackPostRoutes(
            checkin_service, athlete.activity_feedback
        )
        self.equipment_post_routes = (
            EquipmentPostRoutes(athlete.equipment) if athlete.equipment else None
        )
        self.chat_cancel_post_routes = ChatCancelPostRoutes(
            coach_job_cancellation_service
        )
        self.privacy_restore_post_routes = PrivacyRestorePostRoutes(
            session_auth_service,
            backup_restore_service,
            max_backup_bytes,
        )
        self.auth_post_routes = AuthPostRoutes(session_auth_service, maintenance_gate)
        self.nutrition_get_routes = NutritionGetRoutes(
            session_auth_service,
            diary_service,
            meal_library_service,
            athlete_clock.now,
        )
        self.nutrition_post_routes = NutritionPostRoutes(
            diary_service,
            meal_library_service,
            sync_job_queue_service,
        )
        self.nutrition_put_routes = NutritionPutRoutes(
            diary_service, meal_library_service
        )
        self.route_dispatcher = HttpRouteDispatcher(
            (
                self.public_get_routes,
                self.planning_get_routes,
                self.sync_get_routes,
                self.state_events_get_routes,
                self.coach_get_routes,
                self.athlete_get_routes,
                self.history_get_routes,
                self.diagnostics_get_routes,
                self.privacy_get_routes,
                self.nutrition_get_routes,
                self.analysis_routes,
            ),
            (
                self.settings_put_routes,
                self.athlete_put_routes,
                self.nutrition_put_routes,
            ),
        )
        self.sync_command_post_route = SyncCommandPostRoute(
            lambda: self.sync_command_endpoint()
        )
        self.authenticated_post_routes = HttpAuthenticatedPostRoutes(
            self.coach_actions_post_routes,
            self.chat_post_routes,
            self.transcribe_post_routes,
            self.planning_commands_post_routes,
            self.feedback_post_routes,
            self.chat_stream_transport,
            self.sync_command_post_route,
            self.history_undo_post_routes,
            self.privacy_delete_post_routes,
            self.diagnostics_delete_post_routes,
            self.nutrition_post_routes,
            self.analysis_routes,
            self.equipment_post_routes,
        )
        self.post_dispatcher = HttpPostDispatcher(
            self.auth_post_routes,
            self.privacy_restore_post_routes,
            self.chat_cancel_post_routes,
            self.authenticated_post_routes,
        )
        self.response_transport = http_response_transport
        self._handler_configuration = handler_configuration
        self._sync_job_queue_service = sync_job_queue_service
        self._sync_state_repository = sync_state_repository
        self._performance_refresh_service = performance_refresh_service
        self._full_provider_resync_service = full_provider_resync_service
        self._sync_period_defaults = sync_period_defaults
        self._all_sync_days = all_sync_days
        self._uuid_factory = uuid_factory
        self._backup_service = backup_service
        self._privacy_export_service = privacy_export_service
        self._monotonic = monotonic
        self._export_time_limit_seconds = export_time_limit_seconds

    def readiness_service(self) -> ReadinessService:
        return ReadinessService(
            self._database_manager,
            self._database_lock(),
            self._data_dir(),
            self._readiness_maintenance_gate(),
            ReadinessProbeService(),
        )

    def export_stream_transport(self) -> ExportStreamTransport:
        return ExportStreamTransport(
            self._backup_service,
            self._privacy_export_service,
            monotonic=self._monotonic,
            time_limit_seconds=self._export_time_limit_seconds,
        )

    def library_page_service(self) -> LibraryPageService:
        return LibraryPageService(self._database_manager(), self._workout_library())

    def chat_history_page_service(self) -> ChatHistoryPageService:
        return ChatHistoryPageService(
            self._conversation_history_service(),
            self._proposal_read_service(),
            maximum=self._chat_page_max,
        )

    def sync_command_endpoint(self) -> SyncCommandEndpoint:
        return SyncCommandEndpoint(
            self._sync_job_queue_service(),
            self._sync_state_repository(),
            self._performance_refresh_service(),
            self._full_provider_resync_service(),
            self._uuid_factory,
            self._sync_period_defaults,
            self._all_sync_days,
        )

    def request_handler_class(self) -> type[BaseHTTPRequestHandler]:
        handler = self._handler_configuration()
        return create_request_handler(
            HttpRequestHandlerDependencies(
                app_version=handler.identity.app_version,
                logger=handler.identity.logger,
                session_auth_service=handler.identity.session_auth_service,
                route_dispatcher=self.route_dispatcher,
                post_dispatcher=self.post_dispatcher,
                response_transport=self.response_transport,
                maintenance_gate=handler.identity.maintenance_gate,
                redact_text=handler.errors.redact_text,
                internal_server_error=handler.errors.internal_server_error,
                max_body_bytes=handler.body_limits.max_body_bytes,
                max_audio_body_bytes=handler.body_limits.max_audio_body_bytes,
                voice_audio_types=handler.audio.voice_audio_types,
                normalize_audio_type=handler.audio.normalize_audio_type,
                static_asset_service=StaticAssetService(handler.public_dir),
            )
        )
