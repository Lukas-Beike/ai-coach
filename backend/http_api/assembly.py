from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable

from backend.http_api.athlete_get import AthleteGetRoutes
from backend.http_api.athlete_put import AthletePutRoutes
from backend.http_api.auth_post import AuthPostRoutes
from backend.http_api.chat_cancel_post import ChatCancelPostRoutes
from backend.http_api.chat_post import ChatPostRoutes
from backend.http_api.coach_actions_post import CoachActionsPostRoutes
from backend.http_api.coach_get import CoachGetRoutes
from backend.http_api.chat_stream import CoachChatStreamTransport
from backend.http_api.diagnostics_get import DiagnosticsGetRoutes
from backend.http_api.route_dispatch import HttpRouteDispatcher
from backend.http_api.handler import HttpRequestHandlerDependencies, create_request_handler
from backend.http_api.history_get import HistoryGetRoutes
from backend.http_api.history_undo_post import HistoryUndoPostRoutes
from backend.http_api.nutrition import NutritionGetRoutes, NutritionPostRoutes, NutritionPutRoutes
from backend.http_api.planning_commands_post import PlanningCommandsPostRoutes
from backend.http_api.planning_get import PlanningGetRoutes
from backend.http_api.post_dispatch import HttpAuthenticatedPostRoutes, HttpPostDispatcher
from backend.http_api.privacy_delete_post import PrivacyDeletePostRoutes
from backend.http_api.privacy_get import PrivacyGetRoutes
from backend.http_api.public_get import PublicGetRoutes
from backend.http_api.response_transport import HttpResponseTransport
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.http_api.state_events_transport import StateEventTransport
from backend.http_api.settings_put import SettingsPutRoutes
from backend.http_api.state_events_get import StateEventsGetRoutes
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.http_api.sync_get import SyncGetRoutes
from backend.http_api.transcribe_post import TranscribePostRoutes
from backend.http_api.feedback_post import FeedbackPostRoutes
from backend.http_api.privacy_restore_post import PrivacyRestorePostRoutes
from backend.http_api.static_assets import StaticAssetService


@dataclass(frozen=True)
class HttpHandlerConfiguration:
    app_version: str
    logger: Any
    session_auth_service: Callable[[], Any]
    maintenance_gate: Any
    redact_text: Callable[[str], str]
    public_app_error_status: Callable[[Any], int]
    internal_server_error: str
    max_body_bytes: int
    max_audio_body_bytes: int
    voice_audio_types: Any
    normalize_audio_type: Callable[[str], str]
    public_dir: Path


class HttpApiAssembly:
    """Own eager HTTP route composition and lazy request-handler creation."""

    def __init__(
        self,
        *,
        handler_configuration: Callable[[], HttpHandlerConfiguration],
        maintenance_gate: Any,
        readiness_service: Callable[[], Any],
        session_auth_service: Callable[[], Any],
        chat_history_page_service: Callable[[], Any],
        coach_command_receipt_service: Callable[[], Any],
        coach_job_submission_service: Callable[[], Any],
        coach_job_cancellation_service: Callable[[], Any],
        public_bootstrap_service: Callable[[], Any],
        public_plan_state_service: Callable[[], Any],
        public_weather_state_service: Callable[[], Any],
        public_performance_state_service: Callable[[], Any],
        public_feedback_state_service: Callable[[], Any],
        public_sync_state_service: Callable[[], Any],
        library_page_service: Callable[[], Any],
        profile_service: Callable[[], Any],
        competition_service: Callable[[], Any],
        activity_read_service: Callable[[], Any],
        checkin_service: Callable[[], Any],
        coach_context_preview_service: Callable[[], Any],
        settings: Any,
        recent_log_entries_service: Callable[[], Any],
        diagnostic_report_service: Callable[[], Any],
        athlete_clock: Any,
        local_today: Callable[[], Any],
        all_sync_days: int,
        change_history_service: Callable[[], Any],
        history_undo_service: Callable[[], Any],
        proposal_creation_service: Callable[[], Any],
        proposal_confirmation_service: Callable[[], Any],
        proposal_execution_service: Callable[[], Any],
        coach_reset_service: Callable[[], Any],
        coach_provision_service: Callable[[], Any],
        max_chat_request_bytes: int,
        chat_stream_registry: Any,
        redact_text: Callable[[str], str],
        export_stream_transport: Any,
        privacy_delete_service: Callable[[], Any],
        backup_restore_service: Callable[[], Any],
        state_event_buffer: Any,
        athlete_context_service: Callable[[], Any],
        coach_planning_command_service: Callable[[], Any],
        sync_job_queue_service: Callable[[], Any],
        sync_state_repository: Callable[[], Any],
        performance_refresh_service: Callable[[], Any],
        full_provider_resync_service: Callable[[], Any],
        sync_period_defaults: Any,
        uuid_factory: Callable[[], str],
        audio_transcription_client: Callable[[], Any],
        nutrition_service: Callable[[], Any],
        intervals_nutrition_sync_service: Callable[[], Any],
        http_response_transport: HttpResponseTransport,
        openai_response_timeout_seconds: float,
        logger: Any,
        max_backup_bytes: int,
    ) -> None:
        self.coach_get_routes = CoachGetRoutes(
            session_auth_service, chat_history_page_service,
            coach_command_receipt_service, coach_job_submission_service,
        )
        self.public_get_routes = PublicGetRoutes(
            maintenance_gate, readiness_service, session_auth_service,
            public_bootstrap_service,
        )
        self.planning_get_routes = PlanningGetRoutes(
            session_auth_service, public_plan_state_service,
            public_weather_state_service, library_page_service,
        )
        self.athlete_get_routes = AthleteGetRoutes(
            session_auth_service, public_performance_state_service,
            profile_service, competition_service,
            public_feedback_state_service, coach_context_preview_service, settings,
        )
        self.diagnostics_get_routes = DiagnosticsGetRoutes(
            session_auth_service, recent_log_entries_service,
            diagnostic_report_service,
        )
        self.sync_get_routes = SyncGetRoutes(
            session_auth_service, sync_job_queue_service,
            public_sync_state_service, activity_read_service,
            local_today, all_sync_days,
        )
        self.history_get_routes = HistoryGetRoutes(session_auth_service, change_history_service)
        self.history_undo_post_routes = HistoryUndoPostRoutes(
            history_undo_service, proposal_creation_service,
        )
        self.coach_actions_post_routes = CoachActionsPostRoutes(
            proposal_confirmation_service, proposal_execution_service,
        )
        self.chat_post_routes = ChatPostRoutes(
            coach_job_submission_service,
            coach_reset_service, max_chat_request_bytes,
        )
        self.chat_stream_transport = CoachChatStreamTransport(
            chat_stream_registry,
            coach_job_submission_service,
            coach_command_receipt_service, redact_text, logger,
            max_request_bytes=max_chat_request_bytes,
            response_timeout_seconds=openai_response_timeout_seconds,
        )
        self.transcribe_post_routes = TranscribePostRoutes(
            settings, audio_transcription_client,
        )
        self.privacy_delete_post_routes = PrivacyDeletePostRoutes(privacy_delete_service)
        self.privacy_get_routes = PrivacyGetRoutes(
            session_auth_service, export_stream_transport, privacy_delete_service,
        )
        self.state_events_get_routes = StateEventsGetRoutes(
            session_auth_service, StateEventTransport(state_event_buffer),
        )
        self.settings_put_routes = SettingsPutRoutes(settings)
        self.athlete_put_routes = AthletePutRoutes(athlete_context_service, profile_service)
        self.planning_commands_post_routes = PlanningCommandsPostRoutes(
            coach_planning_command_service,
            coach_provision_service,
        )
        self.feedback_post_routes = FeedbackPostRoutes(checkin_service)
        self.chat_cancel_post_routes = ChatCancelPostRoutes(coach_job_cancellation_service)
        self.privacy_restore_post_routes = PrivacyRestorePostRoutes(
            session_auth_service, backup_restore_service, max_backup_bytes,
        )
        self.auth_post_routes = AuthPostRoutes(session_auth_service, maintenance_gate)
        self.nutrition_get_routes = NutritionGetRoutes(
            session_auth_service, nutrition_service, athlete_clock.now,
        )
        self.nutrition_post_routes = NutritionPostRoutes(
            nutrition_service, intervals_nutrition_sync_service,
        )
        self.nutrition_put_routes = NutritionPutRoutes(nutrition_service)
        self.route_dispatcher = HttpRouteDispatcher(
            (
                self.public_get_routes, self.planning_get_routes,
                self.sync_get_routes, self.state_events_get_routes,
                self.coach_get_routes, self.athlete_get_routes,
                self.history_get_routes, self.diagnostics_get_routes,
                self.privacy_get_routes, self.nutrition_get_routes,
            ),
            (self.settings_put_routes, self.athlete_put_routes, self.nutrition_put_routes),
        )
        self.sync_command_post_route = SyncCommandPostRoute(
            lambda: self.sync_command_endpoint()
        )
        self.authenticated_post_routes = HttpAuthenticatedPostRoutes(
            self.coach_actions_post_routes, self.chat_post_routes,
            self.transcribe_post_routes, self.planning_commands_post_routes,
            self.feedback_post_routes, self.chat_stream_transport,
            self.sync_command_post_route, self.history_undo_post_routes,
            self.privacy_delete_post_routes,
            self.nutrition_post_routes,
        )
        self.post_dispatcher = HttpPostDispatcher(
            self.auth_post_routes, self.privacy_restore_post_routes,
            self.chat_cancel_post_routes, self.authenticated_post_routes,
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
        return create_request_handler(HttpRequestHandlerDependencies(
            app_version=handler.app_version,
            logger=handler.logger,
            session_auth_service=handler.session_auth_service,
            route_dispatcher=self.route_dispatcher,
            post_dispatcher=self.post_dispatcher,
            response_transport=self.response_transport,
            maintenance_gate=handler.maintenance_gate,
            redact_text=handler.redact_text,
            public_app_error_status=handler.public_app_error_status,
            internal_server_error=handler.internal_server_error,
            max_body_bytes=handler.max_body_bytes,
            max_audio_body_bytes=handler.max_audio_body_bytes,
            voice_audio_types=handler.voice_audio_types,
            normalize_audio_type=handler.normalize_audio_type,
            static_asset_service=StaticAssetService(handler.public_dir),
        ))
