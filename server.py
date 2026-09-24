from __future__ import annotations
from backend.coach import attachments as coach_attachments
from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.read_tools import CoachReadToolService
from backend.coach.training_template_tools import TrainingTemplateToolService
from backend.coach import limits as coach_limits
from backend.coach import streams as coach_streams

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.db import row_factory as database_row_factory
from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import (
    DiagnosticReportDependencies,
    DiagnosticReportService,
)
from backend.errors import (
    INTERNAL_SERVER_ERROR,
    AppError,
    ClientDisconnected,
    public_app_error_status,
)
from backend import config as app_config
from backend import observability
from backend.activities.duplicate_service import DuplicateActivityService
from backend.calendar import external as calendar_external
from backend.calendar import local as calendar_local
from backend.activities.feedback import ActivityFeedbackService
from backend.activities.read_service import ActivityReadService
from backend.privacy import (
    PrivacyDataExportDependencies,
    PrivacyDataExportService,
    PrivacyDeleteDependencies,
    PrivacyDeleteService,
)
from backend.athlete.checkins import (
    CHECKIN_SCORE_FIELDS,
    CHECKIN_TEXT_LIMITS,
    CheckinService,
)
from backend.athlete.context import AthleteContextService
from backend.athlete.profile import DEFAULT_PROFILE, ProfileService, normalize_profile, timezone_name
from backend.performance import morning_battery as performance_morning_battery
from backend.performance.morning_battery_service import (
    MorningBatteryClock,
    MorningBatteryEvents,
    MorningBatteryExecutionGate,
    MorningBatteryRetryPolicy,
    MorningBatterySource,
    MorningBatteryStore,
    MorningBodyBatteryService,
)
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance
from backend.sync import freshness as sync_freshness
from backend.sync import garmin as garmin_sync
from backend.sync.gates import (
    GARMIN_RESYNC_GATE,
    INTERVALS_RESYNC_GATE,
)
from backend.sync import intervals_state
from backend.sync import observation as sync_observation
from backend.sync.intervals_lock import INTERVALS_SYNC_LOCK
from backend.sync.intervals import (
    IntervalsSnapshotReader,
    IntervalsSnapshotService,
    IntervalsSyncJournal,
    IntervalsSyncRuntime,
    IntervalsSyncService,
    IntervalsSyncStatus,
    IntervalsSyncWorkflow,
)
from backend.sync.competitions import CompetitionSyncReconciler, CompetitionSyncService
from backend.weather.service import (
    WeatherCacheStore,
    WeatherRefreshJournal,
    WeatherService,
)
from backend.settings import SettingsService
from backend.db.bootstrap import initialize_application_database
from backend.db.key_value import KeyValueService
from backend.db.repositories import ActivityFeedbackRepository, ChatRepository, CheckinRepository, CompetitionRepository, KeyValueRepository, NutritionRepository, PlanAdjustmentRepository, PlanningStateRepository, ProfileRepository, SnapshotRepository, TrainingPlanRepository
from backend.db.manager import DatabaseManager
from backend.db.schema import configure_cipher, database_schema_is_current
from backend.config import Config, DEFAULT_OPENAI_BASE_URL, load_config
from backend.providers.intervals import IntervalsApiClient
from backend.providers import audio as audio_provider
from backend.providers import calendar as calendar_provider
from backend.providers import gemini as gemini_provider
from backend.providers import http as provider_http
from backend.providers import openai as openai_provider
from backend.providers import state as provider_state
from backend.providers import weather as weather_provider
from backend.providers import intervals_client as intervals_client_module
from backend.providers.garmin import GarminClientFactory
from backend.providers import garmin_morning
from backend.http_api import server as http_server
from backend.http_api.bootstrap_state import (
    PublicBootstrapDependencies,
    PublicBootstrapService,
)
from backend.http_api.athlete_get import AthleteGetRoutes
from backend.http_api.athlete_put import AthletePutRoutes
from backend.http_api.coach_actions_post import CoachActionsPostRoutes
from backend.http_api.chat_post import ChatPostRoutes
from backend.http_api.chat_stream import CoachChatStreamTransport
from backend.http_api.transcribe_post import TranscribePostRoutes
from backend.http_api.planning_commands_post import PlanningCommandsPostRoutes
from backend.http_api.feedback_post import FeedbackPostRoutes
from backend.http_api.chat_cancel_post import ChatCancelPostRoutes
from backend.http_api.privacy_restore_post import PrivacyRestorePostRoutes
from backend.http_api.auth_post import AuthPostRoutes
from backend.http_api.coach_get import CoachGetRoutes
from backend.http_api.diagnostics_get import DiagnosticsGetRoutes
from backend.http_api.diagnostics_post import DiagnosticsCapturePostRoutes
from backend.http_api.public_get import PublicGetRoutes
from backend.http_api.planning_get import PlanningGetRoutes
from backend.http_api.rate_limit import RateLimiter
from backend.http_api.readiness import ReadinessService
from backend.http_api.auth import SessionAuthService
from backend.http_api.public_performance import (
    PublicFeedbackStateService,
    PublicPerformanceStateService,
)
from backend.http_api.public_weather import PublicWeatherStateService
from backend.http_api.state_prelude import (
    CalendarWindowRange,
    PublicStateLocalPrelude,
    PublicStateWeatherPrelude,
)
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService
from backend.http_api.state_versions import StateVersionService
from backend.http_api.sync_commands import SyncCommandEndpoint
from backend.http_api.sync_commands_post import SyncCommandPostRoute
from backend.http_api.post_dispatch import (
    HttpAuthenticatedPostRoutes,
    HttpPostDispatcher,
)
from backend.http_api.sync_get import SyncGetRoutes
from backend.http_api.history_get import HistoryGetRoutes
from backend.http_api.history_undo_post import HistoryUndoPostRoutes
from backend.http_api.privacy_get import PrivacyGetRoutes
from backend.http_api.privacy_delete_post import PrivacyDeletePostRoutes
from backend.http_api.settings_put import SettingsPutRoutes
from backend.http_api.nutrition import (
    NutritionGetRoutes,
    NutritionPostRoutes,
    NutritionPutRoutes,
)
from backend.nutrition.service import NutritionService
from backend.nutrition.sync import IntervalsNutritionSyncService
from backend.sync.status import SyncOperationStateWriter, SyncPublicStateService
from backend.sync.authority import PlanningAuthorityService
from backend.sync.adaptive import AdaptivePreviewFollowupService, IllnessPauseSyncService
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.daily import DailySyncMarkerService
from backend.sync.refresh import ProviderRefreshTracker
from backend.sync.reconcile import PlannedUnitSyncStateWriter
from backend.sync.planned_units import RemotePlannedUnitReconciler
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.library import (
    WorkoutLibraryRefreshService,
    WorkoutLibraryRemoteReconciler,
    WorkoutLibrarySyncService,
    WorkoutLibrarySyncStateService,
    workout_library_sync_running,
)
from backend.sync.state import SyncStateRepository
from backend.sync.selected import SelectedWorkoutSyncService
from backend.sync.performance import (
    PerformanceRefreshFollowupService,
    PerformanceRefreshService,
)
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminRemoteReader,
    GarminSyncCoordination,
    GarminSyncLifecycleState,
    GarminSyncService,
    GarminSyncSource,
    shared_garmin_sync_lock,
)
from backend.sync.garmin_projection_service import GarminProjectionService
from backend.sync.full_resync import (
    FullProviderResyncService,
    FullResyncOperationJournal,
    FullResyncProviderExecution,
    FullResyncStateStore,
    PROVIDER_RESYNC_KEYS,
)
from backend.sync.external_calendar import (
    ExternalCalendarSyncService,
    shared_external_calendar_sync_lock,
)
from backend.sync.executor import (
    CalendarWeatherSyncJobOwner,
    GarminSyncJobOwner,
    HistoricalSyncJobOwner,
    IntervalsSyncJobOwner,
    SyncJobExecutor,
    SyncJobProviderDispatcher,
)
from backend.sync.weather import WeatherSyncService
from backend.sync.worker import SyncJobWorker, shared_sync_job_wake_event
from backend.planning import adaptive as planning_adaptive
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning import changes as planning_changes
from backend.planning import context as planning_context
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.planning import competitions as planning_competitions
from backend.planning.competition_service import CompetitionService
from backend.planning import library as planning_library
from backend.planning import library_service as planning_library_service
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.local_plan_creation_service import LocalTrainingPlanCreationService
from backend.planning import planned_unit_service as planning_planned_unit_service
from backend.planning.replacement_service import StructuredTrainingPlanReplacementService
from backend.planning.revision import PlanningRevisionService
from backend.planning import season as planning_season
from backend.planning.state_service import StructuredTrainingStateService
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService
from backend.planning import training_plans as planning_training_plans
from backend.http_api.bootstrap_calendar import PublicStateCalendarProjection
from backend.http_api.public_state import PublicStateDependencies, PublicStateService
from backend.sync.jobs import (
    SyncJobStore,
)
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.queue import SyncJobQueueService
from backend.sync.scheduler import (
    AUTO_UPDATE_LABEL,
    DailySyncScheduler,
    DailySyncSchedulerConfig,
    DailySyncLoop,
    StartupSyncScheduler,
    StartupSyncSchedulerConfig,
)
from backend.coach.activity_read_tools import CoachActivityReadToolService
from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.library_plan_tools import CoachLibraryPlanToolService
from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.plan_artifact_tools import CoachPlanArtifactToolService
from backend.coach.tool_replay import CoachStructuredToolReplayService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.coach.planning_change_tools import CoachPlanningChangeToolService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach import context as coach_context_module
from backend.coach.context import (
    CoachContextPreviewLimits,
    CoachContextPreviewService,
    CoachPerformanceContextReader,
    CoachPlanningContextReader,
    CoachStructuredContextService,
    CoachTrainingContextService,
    CoachQuickActionsService,
)
from backend.coach.request_payload import CoachRequestPayloadService
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.conversation import (
    CoachAttachmentContextService,
    CoachConversationHistoryService,
    CoachConversationProvisionService,
    CoachConversationResetService,
    CoachMessageService,
    GeminiConversationHistoryService,
    GeminiConversationResponseService,
    GeminiLocalChatHistoryService,
    GeminiRequestPayloadService,
    GeminiResponseNormalizationService,
)
from backend.coach.conversation_gate import CoachConversationGate
from backend.coach.proposals import (
    CoachProposalCreationService,
    CoachProposalConfirmationService,
    CoachProposalExecutionService,
    CoachProposalReadService,
)
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.turn_opening import CoachTurnOpeningService
from backend.coach.dialogue import CoachDialogueReadService, dialogue_tools
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.coach.clarification import CoachClarificationService
from backend.coach.turn_outcome import CoachStructuredOutcomeService
from backend.coach.training_patch import CoachTrainingPatchService
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal
from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.coach.final_receipt import CoachFinalReceiptService
from backend.coach.response_transport import CoachResponseTransport
from backend.coach.structured_response import CoachStructuredResponseService
from backend.coach import structured_tool_round
from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundLimits,
    CoachStructuredToolRoundService,
)
from backend.coach.structured_turn import CoachStructuredTurnDependencies, CoachStructuredTurnService
from backend.coach.chat_turn import CoachChatTurnService
from backend.coach.planning_commands import CoachPlanningCommandService
from backend.coach.job_store import CoachJobStore
from backend.coach.cancellation import CoachCancellationService
from backend.coach.turn_failures import (
    CoachTurnFailureDependencies,
    CoachTurnFailureService,
)
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.morning import ManualMorningCheckinService, MorningCheckinStateService
from backend.coach.morning_completion import MorningCoachJobCompletionService
from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.coach.tools import build_tool_contracts
from backend.coach.service import command_receipt
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.http_api.library_page import LibraryPageService
from backend.http_api.chat_page import ChatHistoryPageService
from backend.http_api.static_assets import StaticAssetService
from backend.http_api.export_streams import ExportStreamTransport
from backend.http_api.state_events_transport import StateEventTransport
from backend.http_api.state_events_get import StateEventsGetRoutes
from backend.http_api.route_dispatch import HttpRouteDispatcher
from backend.http_api.response_transport import HttpResponseTransport
from backend.http_api.requests import (
    read_audio_body as read_request_audio_body,
    read_body as read_request_body,
    read_json as read_request_json,
)
from backend.backup.export import (
    PrivacyArchiveExportConfig,
    PrivacyArchiveExportService,
)
from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.restore import DatabaseRestoreConfig, DatabaseRestoreService
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)

try:
    from sqlcipher3 import dbapi2 as sqlite_backend
    SQLCIPHER_AVAILABLE = True
except ImportError:  # Local unit tests may run without optional DB crypto.
    sqlite_backend = sqlite3
    SQLCIPHER_AVAILABLE = False


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "intervals-coach.db"
LOG_PATH = DATA_DIR / "intervals-coach.log"
PROVIDER_INTERVALS_NAME = "Intervals.icu"
PROVIDER_GARMIN_NAME = "Garmin Connect"
PROVIDER_INTERVALS_WELLNESS_NAME = "Intervals.icu Wellness"
JSON_MEDIA_TYPE = "application/json"
OPENAI_RESPONSES_PATH = "/responses"
PLANNED_WORKOUT_LABEL = "Geplante Einheit"
APP_NAME = "Intervals Coach"
SELECT_PLANNED_PAYLOAD_SQL = "SELECT payload FROM planned_units WHERE local_id=?"
APP_VERSION = "1.11.12"
MAX_BODY_BYTES = 1_000_000
MAX_AUDIO_BODY_BYTES = 8_000_000
MAX_BACKUP_BYTES = 100_000_000
MAX_PRIVACY_EXPORT_BYTES = 100_000_000
MIN_EXPORT_FREE_BYTES = 10_000_000
EXPORT_TIME_LIMIT_SECONDS = 120
# The Responses API counts both visible output and reasoning tokens against
# max_output_tokens. Keep ordinary replies bounded, but leave enough room for
# an explicitly requested multi-week training plan.
OPENAI_RESPONSE_TIMEOUT_SECONDS = 180
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_BACKGROUND_POLL_SECONDS = 2
OPENAI_BACKGROUND_MAX_SECONDS = 60 * 60
INTERVALS_SYNC_WAIT_SECONDS = 120
DB_LOCK = threading.RLock()
COACH_CONVERSATION_GATE = CoachConversationGate()
SYNC_JOB_WORKER: SyncJobWorker | None = None
RATE_LIMITER = RateLimiter()


CONFIG = load_config(ROOT, DATA_DIR)


LOGGER = logging.getLogger("intervals_coach")
REDACTOR = observability.Redactor(lambda: CONFIG)




def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


KEY_VALUE_REPOSITORY = KeyValueRepository(utc_now)
PROFILE_REPOSITORY = ProfileRepository(KEY_VALUE_REPOSITORY)
COMPETITION_REPOSITORY = CompetitionRepository()
TRAINING_PLAN_REPOSITORY = TrainingPlanRepository()
PLANNING_STATE_REPOSITORY = PlanningStateRepository()
PLANNING_REVISION_SERVICE = PlanningRevisionService(
    PLANNING_STATE_REPOSITORY, utc_now
)
PLAN_ADJUSTMENT_REPOSITORY = PlanAdjustmentRepository()
CHAT_REPOSITORY = ChatRepository(utc_now)
CHECKIN_REPOSITORY = CheckinRepository(utc_now)
ACTIVITY_FEEDBACK_REPOSITORY = ActivityFeedbackRepository(utc_now)
SNAPSHOT_REPOSITORY = SnapshotRepository()


DATABASE_MANAGER: DatabaseManager | None = None
DATABASE_MANAGER_SIGNATURE: tuple[str, str, bool] | None = None
SESSION_AUTH_SERVICE: SessionAuthService | None = None
SESSION_AUTH_SIGNATURE: tuple[Any, Config, bool] | None = None
PROVIDER_STATE_SERVICE: provider_state.ProviderStateService | None = None
PROVIDER_HTTP_CLIENT: provider_http.JsonHttpClient | None = None
PROVIDER_REFRESH_TRACKER: ProviderRefreshTracker | None = None
WEATHER_SERVICE: WeatherService | None = None
MORNING_BODY_BATTERY_SERVICE: MorningBodyBatteryService | None = None

PROVIDER_REFRESH_RETRY_BASE_SECONDS = 15 * 60
PROVIDER_REFRESH_RETRY_MAX_SECONDS = 6 * 60 * 60
SYNC_JOB_RETRY_BASE_SECONDS = 15 * 60
SYNC_JOB_RETRY_MAX_SECONDS = 6 * 60 * 60
SYNC_JOB_POLL_SECONDS = 1.0
GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS = 120
def database_manager() -> DatabaseManager:
    """Return the manager for the active path and secure configuration."""
    global DATABASE_MANAGER, DATABASE_MANAGER_SIGNATURE, PROVIDER_HTTP_CLIENT, PROVIDER_REFRESH_TRACKER, PROVIDER_STATE_SERVICE, WEATHER_SERVICE, MORNING_BODY_BATTERY_SERVICE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signature = (str(DB_PATH.resolve()), CONFIG.app_password, SQLCIPHER_AVAILABLE)
    if DATABASE_MANAGER is not None and DATABASE_MANAGER_SIGNATURE != signature:
        DATABASE_MANAGER.close()
        DATABASE_MANAGER = None
        DATABASE_MANAGER_SIGNATURE = None
        PROVIDER_HTTP_CLIENT = None
        PROVIDER_REFRESH_TRACKER = None
        PROVIDER_STATE_SERVICE = None
        WEATHER_SERVICE = None
        MORNING_BODY_BATTERY_SERVICE = None
    if DATABASE_MANAGER is None:
        PROVIDER_HTTP_CLIENT = None
        PROVIDER_REFRESH_TRACKER = None
        PROVIDER_STATE_SERVICE = None
        WEATHER_SERVICE = None
        MORNING_BODY_BATTERY_SERVICE = None
        if CONFIG.app_password and not SQLCIPHER_AVAILABLE:
            raise RuntimeError("SQLCipher ist fÃ¼r eine verschlÃ¼sselte Datenbank erforderlich.")
        DATABASE_MANAGER = DatabaseManager(
            DB_PATH,
            sqlite_backend if CONFIG.app_password else sqlite3,
            password=CONFIG.app_password,
            configure=configure_cipher,
            row_factory=database_row_factory,
            reader_count=4,
            timeout=20,
            persist_connections=bool(CONFIG.app_password),
        )
        DATABASE_MANAGER_SIGNATURE = signature
    return DATABASE_MANAGER


def session_auth_service() -> SessionAuthService:
    """Compose the HTTP session owner from the active persistence and security configuration."""
    global SESSION_AUTH_SERVICE, SESSION_AUTH_SIGNATURE
    with DB_LOCK:
        manager = database_manager()
        signature = (manager, CONFIG, SQLCIPHER_AVAILABLE)
        if SESSION_AUTH_SERVICE is None or SESSION_AUTH_SIGNATURE != signature:
            SESSION_AUTH_SERVICE = SessionAuthService(
                manager, DB_LOCK, CONFIG, SQLCIPHER_AVAILABLE, RATE_LIMITER
            )
            SESSION_AUTH_SIGNATURE = signature
        return SESSION_AUTH_SERVICE


def provider_state_service() -> provider_state.ProviderStateService:
    """Return provider observability state bound to the active database manager."""
    global PROVIDER_STATE_SERVICE
    manager = database_manager()
    if PROVIDER_STATE_SERVICE is None:
        PROVIDER_STATE_SERVICE = provider_state.ProviderStateService(
            manager,
            KEY_VALUE_REPOSITORY,
            DB_LOCK,
            utc_now,
            lambda: local_now().date(),
            LOGGER,
        )
    return PROVIDER_STATE_SERVICE


def provider_refresh_tracker() -> ProviderRefreshTracker:
    """Return refresh history orchestration bound to the active database manager."""
    global PROVIDER_REFRESH_TRACKER
    manager = database_manager()
    if PROVIDER_REFRESH_TRACKER is None:
        PROVIDER_REFRESH_TRACKER = ProviderRefreshTracker(
            manager,
            runtime_events.STATE_EVENT_BUFFER,
            lambda: datetime.now(timezone.utc),
            lambda: uuid.uuid4().hex,
            retention_days=sync_freshness.PROVIDER_REFRESH_RETENTION_DAYS,
            max_rows=sync_freshness.PROVIDER_REFRESH_MAX_ROWS,
            retry_base_seconds=PROVIDER_REFRESH_RETRY_BASE_SECONDS,
            retry_max_seconds=PROVIDER_REFRESH_RETRY_MAX_SECONDS,
        )
    return PROVIDER_REFRESH_TRACKER


def sync_operation_observer() -> sync_observation.SyncOperationObserver:
    """Compose the shared provider-operation lifecycle owner."""
    return sync_observation.SyncOperationObserver(
        provider_refresh_tracker(),
        runtime_maintenance.MAINTENANCE_GATE,
        LOGGER,
    )


def provider_freshness_service() -> sync_freshness.ProviderFreshnessService:
    """Compose provider freshness persistence and projection."""
    return sync_freshness.ProviderFreshnessService(
        CONFIG,
        database_manager(),
        KEY_VALUE_REPOSITORY,
        lambda: datetime.now(timezone.utc),
    )


def sync_job_store() -> SyncJobStore:
    """Compose durable synchronization-job persistence."""
    return SyncJobStore(database_manager(), utc_now, lambda: uuid.uuid4().hex)


def sync_job_queue_service() -> SyncJobQueueService:
    """Compose the persistent sync-job queue control plane."""
    return SyncJobQueueService(
        sync_job_store(),
        runtime_events.STATE_EVENT_BUFFER,
        runtime_maintenance.MAINTENANCE_GATE,
        shared_sync_job_wake_event(),
        ALL_SYNC_DAYS,
        daily_sync_marker_service(),
    )


def sync_command_endpoint() -> SyncCommandEndpoint:
    """Compose authenticated manual synchronization POST commands."""
    return SyncCommandEndpoint(
        sync_job_queue_service(), sync_state_repository(),
        performance_refresh_service(), full_provider_resync_service(),
        lambda: uuid.uuid4().hex, SYNC_PERIOD_DEFAULTS, ALL_SYNC_DAYS,
    )


def provider_refresh_command_service() -> ProviderRefreshCommandService:
    """Compose authorized Coach refresh command execution."""
    return ProviderRefreshCommandService(
        sync_job_queue_service(), intervals_sync_service(), ALL_SYNC_DAYS
    )


def sync_conflict_command_service() -> SyncConflictCommandService:
    """Compose local conflict decisions and explicitly authorized job retry."""
    return SyncConflictCommandService(
        database_manager(),
        planned_unit_service(),
        competition_service(),
        sync_job_queue_service(),
    )


def plan_push_command_service() -> PlanPushCommandService:
    """Compose explicit Coach plan-push chunking and queue persistence."""
    return PlanPushCommandService(sync_job_queue_service())


def structured_plan_sync_service() -> StructuredPlanSyncService:
    """Compose authorized structured-plan selection and execution."""
    return StructuredPlanSyncService(
        database_manager(),
        planning_authority_service(),
        plan_push_command_service(),
        coach_limits.COACH_TRAINING_CHANGE_LIMIT,
    )


def plan_repair_manifest_service() -> PlanRepairManifestService:
    """Compose complete-period local repair manifest validation."""
    return PlanRepairManifestService(database_manager(), planning_authority_service())


def coach_sync_tool_service() -> CoachSyncToolService:
    """Compose concrete sync commands for structured Coach tool execution."""
    return CoachSyncToolService(
        sync_job_queue_service(), planning_authority_service(),
        sync_conflict_command_service(), structured_plan_sync_service(),
        plan_repair_manifest_service(), plan_push_command_service(),
        provider_refresh_command_service(),
    )


def nutrition_service() -> NutritionService:
    """Compose nutrition and calorie tracking for the active database manager."""
    return NutritionService(
        database_manager=database_manager(),
        db_lock=DB_LOCK,
        nutrition_repository=NutritionRepository(utc_now),
        utc_now=utc_now,
        local_now=local_now,
    )


def intervals_nutrition_sync_service() -> IntervalsNutritionSyncService:
    """Compose nutrition sync to Intervals.icu wellness."""
    api_client = IntervalsApiClient(
        api_key=CONFIG.intervals_api_key,
        request=provider_http_client().request,
    )
    return IntervalsNutritionSyncService(
        config=CONFIG,
        api_client=api_client,
        nutrition_service=nutrition_service(),
    )


def coach_athlete_record_tool_service() -> CoachAthleteRecordToolService:
    """Compose concrete local services for Coach athlete-record mutations."""
    return CoachAthleteRecordToolService(
        checkin_service(),
        activity_feedback_service(),
        competition_service(),
        nutrition_service(),
    )


def coach_activity_read_tool_service() -> CoachActivityReadToolService:
    """Compose the read-only activity tools from their owning services."""
    return CoachActivityReadToolService(
        activity_read_service(),
        garmin_payload_service(),
        profile_service(),
        lambda: local_now().date(),
    )


def coach_read_tool_service() -> CoachReadToolService:
    """Compose the read-only Coach tool dispatcher from domain service factories."""
    return CoachReadToolService(
        profile_service,
        structured_training_state_service,
        coach_activity_read_tool_service,
        workout_library_service,
        planned_unit_service,
        change_history_service,
        competition_service,
        training_plan_service,
        coach_limits.COACH_TRAINING_CHANGE_LIMIT,
        nutrition_service,
    )


def state_version_service() -> StateVersionService:
    """Compose the read-only browser version projection."""
    return StateVersionService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        SNAPSHOT_REPOSITORY,
        profile_service(),
    )


def public_performance_state_service() -> PublicPerformanceStateService:
    """Compose the read-only performance projection."""
    return PublicPerformanceStateService(
        sync_state_repository(),
        garmin_payload_service(),
        profile_service(),
        garmin_projection_service(),
        lambda: local_now().date(),
    )


def public_feedback_state_service() -> PublicFeedbackStateService:
    """Compose the read-only feedback projection."""
    return PublicFeedbackStateService(checkin_service(), activity_feedback_service())


def sync_public_state_service() -> SyncPublicStateService:
    """Compose the public sync-status projection."""
    return SyncPublicStateService(
        CONFIG,
        database_manager(),
        KEY_VALUE_REPOSITORY,
        provider_freshness_service(),
        profile_service(),
        garmin_sync_state_service(),
        runtime_maintenance.MAINTENANCE_GATE,
        sync_job_queue_service(),
        state_version_service(),
        INTERVALS_SYNC_LOCK,
    )


def sync_state_repository() -> SyncStateRepository:
    """Compose transactional provider synchronization state."""
    return SyncStateRepository(
        database_manager(), KEY_VALUE_REPOSITORY, SNAPSHOT_REPOSITORY, utc_now
    )


def performance_refresh_service() -> PerformanceRefreshService:
    """Compose targeted Intervals performance refresh persistence."""
    return PerformanceRefreshService(
        CONFIG,
        database_manager(),
        sync_state_repository(),
        KEY_VALUE_REPOSITORY,
        intervals_snapshot_reader(),
        runtime_events.STATE_EVENT_BUFFER,
        REDACTOR.redact_text,
        LOGGER,
        sync_operation_observer(),
        INTERVALS_RESYNC_GATE,
    )


def intervals_snapshot_reader() -> IntervalsSnapshotReader:
    """Compose the Intervals provider snapshot reader."""
    api_client = IntervalsApiClient(
        api_key=CONFIG.intervals_api_key,
        request=provider_http_client().request,
    )
    return IntervalsSnapshotReader(
        CONFIG,
        api_client,
        sync_state_repository(),
        local_now,
        utc_now,
        SYNC_EARLIEST_DATE,
        SYNC_CHUNK_DAYS,
        ALL_SYNC_DAYS,
        PLANNED_CALENDAR_HISTORY_DAYS,
        PLANNED_CALENDAR_FUTURE_DAYS,
    )


def performance_refresh_followup_service() -> PerformanceRefreshFollowupService:
    """Compose performance follow-up queueing and polling."""
    return PerformanceRefreshFollowupService(
        CONFIG,
        sync_job_queue_service(),
        performance_refresh_service(),
        database_manager(),
        KEY_VALUE_REPOSITORY,
        LOGGER,
        wait_seconds=INTERVALS_SYNC_WAIT_SECONDS,
        poll_seconds=SYNC_JOB_POLL_SECONDS,
    )


def sync_job_outcome_service() -> SyncJobOutcomeService:
    """Compose durable sync-job result and retry handling."""
    return SyncJobOutcomeService(
        sync_job_store(),
        runtime_events.STATE_EVENT_BUFFER,
        shared_sync_job_wake_event(),
        REDACTOR.redact_text,
        LOGGER,
        lambda: datetime.now(timezone.utc),
        SYNC_JOB_RETRY_BASE_SECONDS,
        SYNC_JOB_RETRY_MAX_SECONDS,
    )


def daily_sync_marker_service() -> DailySyncMarkerService:
    """Compose transactional provider daily-marker persistence."""
    return DailySyncMarkerService(
        database_manager(), KEY_VALUE_REPOSITORY, local_now
    )


def intervals_snapshot_service() -> IntervalsSnapshotService:
    """Compose Intervals snapshot and sync-window persistence."""
    return IntervalsSnapshotService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        sync_state_repository(),
        remote_planned_unit_reconciler(),
        workout_library_refresh_service(),
        workout_library_service(),
        REDACTOR.redact_text,
        local_now,
        SYNC_EARLIEST_DATE,
        SYNC_CHUNK_DAYS,
        ALL_SYNC_DAYS,
    )


def intervals_sync_service() -> IntervalsSyncService:
    """Compose the complete read-only Intervals synchronization use case."""
    status = IntervalsSyncStatus(database_manager(), KEY_VALUE_REPOSITORY)
    return IntervalsSyncService(
        CONFIG,
        IntervalsSyncWorkflow(
            intervals_snapshot_reader(),
            intervals_snapshot_service(),
            sync_state_repository(),
            daily_sync_marker_service(),
            SYNC_PERIOD_DEFAULTS,
            ALL_SYNC_DAYS,
        ),
        performance_refresh_followup_service(),
        status,
        IntervalsSyncJournal(
            status,
            SyncOperationStateWriter(
                database_manager(),
                KEY_VALUE_REPOSITORY,
                runtime_events.STATE_EVENT_BUFFER,
                REDACTOR.redact_text,
            ),
            REDACTOR.redact_text,
            LOGGER,
            utc_now,
        ),
        IntervalsSyncRuntime(
            INTERVALS_SYNC_LOCK,
            sync_operation_observer(),
            INTERVALS_RESYNC_GATE,
            wait_seconds=INTERVALS_SYNC_WAIT_SECONDS,
        ),
    )


def garmin_fixture_loader() -> garmin_sync.GarminFixtureLoader:
    """Compose fixture loading from the current runtime configuration."""
    return garmin_sync.GarminFixtureLoader(
        CONFIG,
        ROOT,
        local_now,
        utc_now,
        SYNC_EARLIEST_DATE,
        ALL_SYNC_DAYS,
    )


def garmin_client_factory() -> GarminClientFactory:
    """Compose the optional Garmin SDK boundary."""
    return GarminClientFactory()


def garmin_payload_service() -> garmin_sync.GarminPayloadService:
    """Compose Garmin snapshot reads and payload preparation."""
    return garmin_sync.GarminPayloadService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        sync_state_repository(),
        lambda: local_now().date(),
    )


def garmin_sync_state_service() -> garmin_sync.GarminSyncStateService:
    """Compose Garmin sync state and payload persistence."""
    return garmin_sync.GarminSyncStateService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        sync_state_repository(),
        daily_sync_marker_service(),
        REDACTOR,
        utc_now,
        lambda: datetime.now(timezone.utc),
    )


def garmin_remote_reader() -> GarminRemoteReader:
    """Compose authenticated Garmin SDK reads."""
    return GarminRemoteReader(
        CONFIG,
        garmin_client_factory(),
        garmin_sync_state_service(),
        DIAGNOSTIC_CAPTURE,
        REDACTOR.redact_text,
        LOGGER,
        utc_now,
        lambda: local_now().date(),
        SYNC_EARLIEST_DATE,
        SYNC_CHUNK_DAYS,
        ALL_SYNC_DAYS,
    )


def garmin_sync_service() -> GarminSyncService:
    """Compose the complete Garmin synchronization use case."""
    state_service = garmin_sync_state_service()
    return GarminSyncService(
        GarminSyncSource(
            garmin_fixture_loader(),
            garmin_remote_reader(),
            SYNC_EARLIEST_DATE,
            lambda: local_now().date(),
        ),
        garmin_payload_service(),
        state_service,
        SyncOperationStateWriter(
            database_manager(),
            KEY_VALUE_REPOSITORY,
            runtime_events.STATE_EVENT_BUFFER,
            REDACTOR.redact_text,
        ),
        sync_operation_observer(),
        GarminSyncCoordination(
            shared_garmin_sync_lock(),
            GARMIN_RESYNC_GATE,
            wait_seconds=GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS,
        ),
        GarminSyncLifecycleState(
            database_manager(), KEY_VALUE_REPOSITORY, utc_now, LOGGER
        ),
    )


def garmin_projection_service() -> GarminProjectionService:
    """Compose the read-only Garmin public and Coach projections."""
    return GarminProjectionService(
        CONFIG,
        garmin_payload_service(),
        garmin_sync_service(),
        garmin_sync_state_service(),
        sync_state_repository(),
        morning_body_battery_service(),
        garmin_client_factory(),
        database_manager(),
        KEY_VALUE_REPOSITORY,
        REDACTOR,
        local_now,
    )


def full_provider_resync_service() -> FullProviderResyncService:
    """Compose complete provider reset orchestration."""
    observer = sync_operation_observer()
    return FullProviderResyncService(
        FullResyncProviderExecution(
            CONFIG,
            intervals_sync_service(),
            garmin_sync_service(),
            competition_sync_service(),
            INTERVALS_RESYNC_GATE,
            GARMIN_RESYNC_GATE,
            ALL_SYNC_DAYS,
        ),
        FullResyncStateStore(database_manager(), KEY_VALUE_REPOSITORY),
        FullResyncOperationJournal(
            observer,
            LOGGER,
            REDACTOR.redact_text,
            utc_now,
            time.perf_counter,
            lambda: uuid.uuid4().hex,
        ),
    )


def weather_service() -> WeatherService:
    """Return weather orchestration bound to the active runtime resources."""
    global WEATHER_SERVICE
    manager = database_manager()
    if WEATHER_SERVICE is None:
        WEATHER_SERVICE = WeatherService(
            WeatherCacheStore(manager, KEY_VALUE_REPOSITORY, profile_service()),
            lambda: weather_provider.WeatherClient(
                provider_http_client().request, utc_now, LOGGER
            ),
            WeatherRefreshJournal(
                provider_refresh_tracker(),
                sync_observation.OPERATION_CONTEXT,
                lambda: uuid.uuid4().hex,
                LOGGER,
            ),
            runtime_maintenance.MAINTENANCE_GATE,
            lambda: datetime.now(timezone.utc),
            lambda: local_now().date(),
        )
    return WEATHER_SERVICE


def weather_sync_service() -> WeatherSyncService:
    """Compose the observed weather refresh use case."""
    return WeatherSyncService(
        profile_service(),
        weather_service(),
        adaptive_replan_preview_service(),
        sync_operation_observer(),
        LOGGER,
    )


def public_weather_state_service() -> PublicWeatherStateService:
    """Compose the public weather endpoint projection."""
    return PublicWeatherStateService(weather_service())


def morning_body_battery_service() -> MorningBodyBatteryService:
    """Compose morning recovery orchestration from concrete runtime resources."""
    global MORNING_BODY_BATTERY_SERVICE
    manager = database_manager()
    if MORNING_BODY_BATTERY_SERVICE is None:
        client_factory = garmin_client_factory()
        source = MorningBatterySource(
            garmin_fixture_loader(),
            lambda: bool(
                client_factory.available()
                and (CONFIG.garmin_email or Path(CONFIG.garmin_tokenstore).exists())
            ),
            lambda checkin_date: garmin_morning.fetch_morning_body_battery(
                client_factory.create(
                    CONFIG.garmin_email or None, CONFIG.garmin_password or None
                ),
                checkin_date,
                tokenstore=CONFIG.garmin_tokenstore,
                email_configured=bool(CONFIG.garmin_email),
                tokenstore_exists=Path(CONFIG.garmin_tokenstore).exists(),
                profile_timezone=timezone_name(profile_service().get().get("timezone")),
                fallback_zone=local_now().tzinfo or timezone.utc,
                external_call=lambda service, operation, callback, details: provider_http.external_call(
                    service,
                    operation,
                    callback,
                    details,
                    logger=LOGGER,
                    diagnostic_capture=DIAGNOSTIC_CAPTURE,
                    operation_context=sync_observation.operation_context(),
                ),
                sleep_bounds=performance_morning_battery.sleep_bounds,
            ),
            observability.safe_diagnostic_error,
        )
        MORNING_BODY_BATTERY_SERVICE = MorningBodyBatteryService(
            MorningBatteryStore(manager, KEY_VALUE_REPOSITORY),
            source,
            MorningBatteryExecutionGate(
                shared_garmin_sync_lock(),
                runtime_maintenance.MAINTENANCE_GATE,
                GARMIN_RESYNC_GATE,
                GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS,
            ),
            MorningBatteryClock(lambda: datetime.now(timezone.utc), local_now),
            MorningBatteryEvents(runtime_events.STATE_EVENT_BUFFER.publish, LOGGER),
            MorningBatteryRetryPolicy(),
        )
    return MORNING_BODY_BATTERY_SERVICE


def external_calendar_reader() -> calendar_external.ExternalCalendarReader:
    """Compose external-calendar reads for the active database manager."""
    return calendar_external.ExternalCalendarReader(
        database_manager(), lambda: local_now().date()
    )


def external_calendar_sync_service() -> ExternalCalendarSyncService:
    """Compose the complete external-calendar synchronization use case."""
    return ExternalCalendarSyncService(
        CONFIG,
        database_manager(),
        KEY_VALUE_REPOSITORY,
        daily_sync_marker_service(),
        sync_operation_observer(),
        adaptive_replan_preview_service(),
        runtime_events.STATE_EVENT_BUFFER,
        LOGGER,
        REDACTOR.redact_text,
        local_now,
        utc_now,
        APP_VERSION,
        lock=shared_external_calendar_sync_lock(),
    )


def calendar_conflict_service() -> CalendarConflictService:
    """Compose local and external planning-conflict reads."""
    return CalendarConflictService(database_manager(), external_calendar_reader())


def activity_feedback_service() -> ActivityFeedbackService:
    """Compose activity-feedback use cases for the active database manager."""
    return ActivityFeedbackService(
        database_manager(),
        ACTIVITY_FEEDBACK_REPOSITORY,
        SNAPSHOT_REPOSITORY,
    )


def activity_read_service() -> ActivityReadService:
    """Compose completed-activity reads for the active database manager."""
    return ActivityReadService(
        database_manager(),
        SNAPSHOT_REPOSITORY,
        activity_feedback_service(),
    )


def duplicate_activity_service() -> DuplicateActivityService:
    """Compose the authorized duplicate-activity deletion use case."""
    return DuplicateActivityService(
        database_manager(),
        SNAPSHOT_REPOSITORY,
        utc_now,
        runtime_events.STATE_EVENT_BUFFER,
    )


def checkin_service() -> CheckinService:
    """Compose athlete check-in use cases for the active database manager."""
    return CheckinService(
        database_manager(),
        CHECKIN_REPOSITORY,
        lambda: local_now().date(),
    )


def profile_service() -> ProfileService:
    """Compose profile persistence for the active database manager."""
    return ProfileService(
        database_manager(), PROFILE_REPOSITORY, KEY_VALUE_REPOSITORY
    )


def coach_profile_update_service() -> CoachProfileUpdateService:
    """Compose the scoped transactional Coach profile update owner."""
    return CoachProfileUpdateService(profile_service(), database_manager(), DB_LOCK)


def change_history_service() -> ChangeHistoryService:
    """Compose local change-history reads for the active database manager."""
    return ChangeHistoryService(database_manager(), PROFILE_REPOSITORY)


def history_undo_service() -> HistoryUndoService:
    """Compose transactional local history undo orchestration."""
    return HistoryUndoService(
        database_manager(),
        change_history_service(),
        profile_service(),
        workout_library_service(),
        competition_service(),
        planned_unit_service(),
        training_plan_service(),
        PLANNING_REVISION_SERVICE,
    )


def competition_service() -> CompetitionService:
    """Compose transactional local competition use cases."""
    return CompetitionService(database_manager(), COMPETITION_REPOSITORY, utc_now)


def competition_sync_reconciler() -> CompetitionSyncReconciler:
    """Compose local competition reconciliation persistence."""
    return CompetitionSyncReconciler(database_manager(), uuid.uuid4)


def competition_sync_service() -> CompetitionSyncService:
    """Compose the complete competition synchronization use case."""
    return CompetitionSyncService(
        CONFIG,
        intervals_client,
        competition_sync_reconciler(),
        competition_service(),
        database_manager(),
        KEY_VALUE_REPOSITORY,
        runtime_events.STATE_EVENT_BUFFER,
        REDACTOR,
        LOGGER,
        utc_now,
    )


def training_plan_service() -> planning_training_plans.TrainingPlanService:
    """Compose transactional local training-plan metadata use cases."""
    return planning_training_plans.TrainingPlanService(
        database_manager(),
        TRAINING_PLAN_REPOSITORY,
        KEY_VALUE_REPOSITORY,
        PLANNING_REVISION_SERVICE,
        runtime_events.STATE_EVENT_BUFFER,
        utc_now,
    )


def planned_unit_service() -> planning_planned_unit_service.PlannedUnitService:
    """Compose local planned-unit persistence use cases."""
    return planning_planned_unit_service.PlannedUnitService(
        database_manager(),
        PLANNING_REVISION_SERVICE,
        utc_now,
        lambda: local_now().date(),
        uuid.uuid4,
        REDACTOR.redact_text,
        calendar_conflict_service(),
        lambda: runtime_events.STATE_EVENT_BUFFER.publish(
            "coach", {"status": "changed"}
        ),
    )


def planned_unit_sync_state_writer() -> PlannedUnitSyncStateWriter:
    """Compose planned-unit synchronization persistence."""
    return PlannedUnitSyncStateWriter(PLANNING_REVISION_SERVICE, REDACTOR)


def planned_calendar_sync_service() -> PlannedCalendarSyncService:
    """Compose the normal single-unit Intervals calendar push."""
    return PlannedCalendarSyncService(
        CONFIG,
        database_manager(),
        intervals_client,
        planned_unit_sync_state_writer(),
        utc_now,
        lambda: local_now().date(),
    )


def planned_calendar_repair_service() -> PlannedCalendarRepairService:
    """Compose the exact-identity planned calendar repair use case."""
    return PlannedCalendarRepairService(
        CONFIG,
        database_manager(),
        intervals_client,
        planned_unit_sync_state_writer(),
        utc_now,
        lambda: local_now().date(),
        PLANNED_CALENDAR_FUTURE_DAYS,
    )


def remote_planned_unit_reconciler() -> RemotePlannedUnitReconciler:
    """Compose remote planned-unit reconciliation."""
    return RemotePlannedUnitReconciler(
        database_manager(),
        planned_unit_service(),
        PLANNING_REVISION_SERVICE,
        utc_now,
        lambda: local_now().date(),
    )


def workout_library_sync_state_service() -> WorkoutLibrarySyncStateService:
    """Compose workout-library synchronization persistence and projections."""
    return WorkoutLibrarySyncStateService(
        database_manager(), REDACTOR, KEY_VALUE_REPOSITORY, utc_now
    )


def planning_authority_service() -> PlanningAuthorityService:
    """Compose explicit local-authority decisions before provider sync."""
    return PlanningAuthorityService(
        database_manager(),
        workout_library_sync_state_service(),
        PLANNING_REVISION_SERVICE,
        utc_now,
    )


def workout_library_remote_reconciler() -> WorkoutLibraryRemoteReconciler:
    """Compose local reconciliation for already-read remote templates."""
    return WorkoutLibraryRemoteReconciler(database_manager(), utc_now, uuid.uuid4)


def workout_library_refresh_service() -> WorkoutLibraryRefreshService:
    """Compose the read-only initial workout-library refresh."""
    return WorkoutLibraryRefreshService(
        CONFIG,
        database_manager(),
        intervals_client,
        workout_library_remote_reconciler(),
        workout_library_service(),
        workout_library_sync_state_service(),
        KEY_VALUE_REPOSITORY,
        runtime_events.STATE_EVENT_BUFFER,
        utc_now,
    )


def workout_library_sync_service() -> WorkoutLibrarySyncService:
    """Compose the explicit single-entry workout-library synchronization use case."""
    return WorkoutLibrarySyncService(
        CONFIG, intervals_client, workout_library_sync_state_service()
    )


def selected_workout_sync_service() -> SelectedWorkoutSyncService:
    """Compose selected workout and planned-unit synchronization."""
    return SelectedWorkoutSyncService(
        CONFIG,
        database_manager(),
        workout_library_sync_service(),
        planned_calendar_sync_service(),
        planned_calendar_repair_service(),
        REDACTOR.redact_text,
        lock=INTERVALS_SYNC_LOCK,
        wait_seconds=INTERVALS_SYNC_WAIT_SECONDS,
        provider_resync_gate=INTERVALS_RESYNC_GATE,
    )


def sync_job_executor() -> SyncJobExecutor:
    """Compose the concrete persistent provider-job dispatcher."""
    historical_sync = HistoricalSyncJobOwner(
        sync_state_repository=sync_state_repository(),
        queue_service=sync_job_queue_service(),
        local_now=local_now,
        sync_period_defaults=SYNC_PERIOD_DEFAULTS,
        all_sync_days=ALL_SYNC_DAYS,
        sync_chunk_days=SYNC_CHUNK_DAYS,
        sync_earliest_date=SYNC_EARLIEST_DATE,
    )
    provider_dispatcher = SyncJobProviderDispatcher(
        intervals_jobs=IntervalsSyncJobOwner(
            historical_sync=historical_sync,
            intervals_sync_service=intervals_sync_service(),
            performance_refresh_service=performance_refresh_service(),
            selected_workout_sync_service=selected_workout_sync_service(),
            competition_sync_service=competition_sync_service(),
            sync_operation_observer=sync_operation_observer(),
            intervals_resync_gate=INTERVALS_RESYNC_GATE,
        ),
        garmin_jobs=GarminSyncJobOwner(
            historical_sync=historical_sync,
            garmin_sync_service=garmin_sync_service(),
            morning_body_battery_service=morning_body_battery_service(),
            garmin_fixture_loader=garmin_fixture_loader(),
            all_sync_days=ALL_SYNC_DAYS,
        ),
        calendar_weather_jobs=CalendarWeatherSyncJobOwner(
            external_calendar_sync_service=external_calendar_sync_service(),
            weather_sync_service=weather_sync_service(),
        ),
    )
    return SyncJobExecutor(
        provider_dispatcher=provider_dispatcher,
        historical_sync=historical_sync,
        outcome_service=sync_job_outcome_service(),
        all_sync_days=ALL_SYNC_DAYS,
    )


def sync_job_worker() -> SyncJobWorker:
    """Return the one restartable persistent synchronization worker."""
    global SYNC_JOB_WORKER
    if SYNC_JOB_WORKER is None:
        SYNC_JOB_WORKER = SyncJobWorker(
            sync_job_store(),
            sync_job_executor(),
            runtime_maintenance.MAINTENANCE_GATE,
            SYNC_JOB_POLL_SECONDS,
            wake_event=shared_sync_job_wake_event(),
        )
    return SYNC_JOB_WORKER


def workout_library_service() -> planning_library_service.WorkoutLibraryService:
    """Compose local workout-library persistence use cases."""
    return planning_library_service.WorkoutLibraryService(
        database_manager(),
        utc_now,
        uuid.uuid4,
        lambda: runtime_events.STATE_EVENT_BUFFER.publish(
            "coach", {"status": "changed"}
        ),
    )


def workout_library_plan_service() -> WorkoutLibraryPlanService:
    """Compose atomic local planning from saved workout templates."""
    return WorkoutLibraryPlanService(
        database_manager(),
        planned_unit_service(),
        calendar_conflict_service(),
        lambda: runtime_events.STATE_EVENT_BUFFER.publish(
            "coach", {"status": "changed"}
        ),
    )


def coach_library_plan_tool_service() -> CoachLibraryPlanToolService:
    """Compose Coach authorization with atomic local library planning."""
    return CoachLibraryPlanToolService(workout_library_plan_service())


def local_plan_creation_service() -> LocalTrainingPlanCreationService:
    """Compose atomic local plan creation and template reuse."""
    return LocalTrainingPlanCreationService(
        database_manager(),
        TRAINING_PLAN_REPOSITORY,
        planned_unit_service(),
        workout_library_service(),
        calendar_conflict_service(),
        PLANNING_REVISION_SERVICE,
        lambda: local_now().date(),
        utc_now,
        uuid.uuid4,
        LOGGER,
    )


def training_plan_artifact_service() -> TrainingPlanArtifactService:
    """Compose the local Coach plan-artifact lifecycle."""
    return TrainingPlanArtifactService(
        database_manager(),
        local_plan_creation_service(),
        lambda: local_now().date(),
        utc_now,
        uuid.uuid4,
    )


def daily_planning_context_service() -> DailyPlanningContextService:
    """Compose the date-specific planning read model."""
    return DailyPlanningContextService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        checkin_service(),
        external_calendar_reader(),
        morning_body_battery_service(),
        activity_feedback_service(),
        lambda: local_now().date(),
        calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
    )


def structured_training_state_service() -> StructuredTrainingStateService:
    """Compose read-only structured planning-state projection."""
    return StructuredTrainingStateService(
        database_manager(),
        PLANNING_STATE_REPOSITORY,
        competition_service(),
        training_plan_service(),
        coach_dialogue_read_service().artifact_refs,
        sync_job_queue_service().list,
        lambda: local_now().date(),
    )


def structured_training_change_validator() -> planning_changes.StructuredTrainingChangeValidator:
    """Compose transaction-scoped structured planning validation."""
    return planning_changes.StructuredTrainingChangeValidator(
        PLANNING_STATE_REPOSITORY, calendar_conflict_service()
    )


def structured_training_change_service() -> planning_changes.StructuredTrainingChangeService:
    """Compose atomic structured planning changes."""
    return planning_changes.StructuredTrainingChangeService(
        database_manager(),
        structured_training_change_validator(),
        planning_changes.StructuredTrainingPlanResolver(TRAINING_PLAN_REPOSITORY),
        planned_unit_service(),
        PLANNING_REVISION_SERVICE,
        training_plan_service(),
        lambda: local_now().date(),
        coach_limits.COACH_TRAINING_CHANGE_LIMIT,
        lambda: runtime_events.STATE_EVENT_BUFFER.publish(
            "planning", {"status": "changed"}
        ),
    )


def coach_training_patch_service() -> CoachTrainingPatchService:
    """Compose the atomic local Coach training-patch owner."""
    return CoachTrainingPatchService(
        database_manager(), DB_LOCK, structured_training_change_validator(),
        structured_training_change_service(), local_plan_creation_service(),
        calendar_conflict_service(), KEY_VALUE_REPOSITORY,
        runtime_events.STATE_EVENT_BUFFER, lambda: local_now().date(),
        coach_limits.COACH_TRAINING_CHANGE_LIMIT,
    )


def structured_training_plan_replacement_service() -> StructuredTrainingPlanReplacementService:
    """Compose atomic structured training-plan replacement."""
    return StructuredTrainingPlanReplacementService(
        database_manager(),
        PLANNING_STATE_REPOSITORY,
        PLANNING_REVISION_SERVICE,
        TRAINING_PLAN_REPOSITORY,
        KEY_VALUE_REPOSITORY,
        calendar_conflict_service(),
        planned_unit_service(),
        lambda: local_now().date(),
        utc_now,
        uuid.uuid4,
    )


def adaptive_replan_apply_service() -> planning_adaptive.AdaptiveReplanApplyService:
    """Compose atomic local application of adaptive previews."""
    return planning_adaptive.AdaptiveReplanApplyService(
        database_manager(),
        PLAN_ADJUSTMENT_REPOSITORY,
        PLANNING_REVISION_SERVICE,
        lambda: local_now().date(),
        utc_now,
    )


def illness_pause_sync_service() -> IllnessPauseSyncService:
    """Compose the explicitly approved illness-pause remote sync use case."""
    return IllnessPauseSyncService(
        CONFIG,
        intervals_client(),
        adaptive_replan_apply_service=adaptive_replan_apply_service(),
        competition_service=competition_service(),
        adaptive_replan_preview_service=adaptive_replan_preview_service(),
        redactor=REDACTOR,
        today=lambda: local_now().date(),
    )


def coach_adaptive_apply_service() -> CoachAdaptiveApplyService:
    """Compose the later-turn approval and adaptive application owner."""
    return CoachAdaptiveApplyService(
        adaptive_replan_preview_service(), illness_pause_sync_service(),
        database_manager(), DB_LOCK,
    )


def adaptive_preview_followup_service() -> AdaptivePreviewFollowupService:
    """Compose the local preview check after a provider refresh."""
    return AdaptivePreviewFollowupService(adaptive_replan_preview_service(), LOGGER)


def adaptive_replan_preview_service() -> AdaptiveReplanPreviewService:
    """Compose adaptive preview creation and read state."""
    return AdaptiveReplanPreviewService(
        database_manager(),
        PLAN_ADJUSTMENT_REPOSITORY,
        checkin_service(),
        planned_unit_service(),
        external_calendar_reader(),
        weather_service(),
        lambda: local_now().date(),
        utc_now,
        uuid.uuid4,
        calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        CHECKIN_TEXT_LIMITS["illness"],
        planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS,
        planning_adaptive.WEATHER_ADAPTIVE_MAX_MINUTES,
    )


def privacy_data_export_service() -> PrivacyDataExportService:
    """Compose the local JSON privacy-data projection use case."""
    return PrivacyDataExportService(
        PrivacyDataExportDependencies(
            database_manager=database_manager(),
            database_lock=DB_LOCK,
            key_value_repository=KEY_VALUE_REPOSITORY,
            profile_service=profile_service(),
            workout_library_service=workout_library_service(),
            competition_service=competition_service(),
            training_plan_service=training_plan_service(),
            checkin_service=checkin_service(),
            activity_feedback_service=activity_feedback_service(),
            adaptive_preview_service=adaptive_replan_preview_service(),
            external_calendar_reader=external_calendar_reader(),
            local_now=local_now,
            utc_now=utc_now,
        )
    )


def privacy_delete_service() -> PrivacyDeleteService:
    """Compose the maintenance-gated local privacy deletion use case."""
    return PrivacyDeleteService(
        PrivacyDeleteDependencies(
            database_manager=database_manager(),
            database_lock=DB_LOCK,
            key_value_repository=KEY_VALUE_REPOSITORY,
            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
            planning_revision_service=PLANNING_REVISION_SERVICE,
            openai_client=openai_responses_client(),
            logger=LOGGER,
        )
    )


def athlete_context_service() -> AthleteContextService:
    """Compose atomic athlete profile and competition persistence."""
    return AthleteContextService(
        database_manager(),
        profile_service(),
        COMPETITION_REPOSITORY,
        normalize_profile,
        planning_competitions.normalize_competition,
        utc_now,
        uuid.uuid4,
    )


def initialise_database() -> None:
    with DB_LOCK, database_manager().unit_of_work() as db:
        initialize_application_database(
            db,
            key_values=KEY_VALUE_REPOSITORY,
            now=utc_now(),
            current_time=datetime.now(timezone.utc),
            default_profile_json=json.dumps(DEFAULT_PROFILE),
            provider_resync_keys=PROVIDER_RESYNC_KEYS.values(),
            retention_days=int(getattr(CONFIG, "data_retention_days", -1)),
            all_sync_days=ALL_SYNC_DAYS,
        )


def key_value_service() -> KeyValueService:
    return KeyValueService(database_manager(), KEY_VALUE_REPOSITORY)


SYNC_PERIOD_DEFAULTS = {"intervals": 90, "garmin": 30}
ALL_SYNC_DAYS = -1
SYNC_CHUNK_DAYS = 90
SYNC_EARLIEST_DATE = date(2000, 1, 1)
# Keep enough calendar history to show whether recently planned workouts were
# completed, while retaining the existing five-week forward planning horizon.
PLANNED_CALENDAR_HISTORY_DAYS = 35
PLANNED_CALENDAR_FUTURE_DAYS = 35
SETTINGS = SettingsService(
    lambda: CONFIG,
    lambda key: key_value_service().get(key),
    lambda key, value: key_value_service().set(key, value),
)
DIAGNOSTIC_CAPTURE = observability.DiagnosticCapture(
    lambda key: key_value_service().get(key),
    lambda key, value: key_value_service().set(key, value),
    REDACTOR,
    utc_now,
)


def provider_http_client() -> provider_http.JsonHttpClient:
    """Return the observed JSON client bound to the active provider state."""
    global PROVIDER_HTTP_CLIENT
    state = provider_state_service()
    if PROVIDER_HTTP_CLIENT is None or PROVIDER_HTTP_CLIENT.provider_state is not state:
        PROVIDER_HTTP_CLIENT = provider_http.JsonHttpClient(
            APP_VERSION,
            provider_http.MAX_EXTERNAL_RESPONSE_BYTES,
            LOGGER,
            DIAGNOSTIC_CAPTURE,
            state,
            REDACTOR.redact_text,
            partial(observability.safe_response_headers, redact=REDACTOR.redact_text),
            utc_now,
            sync_observation.operation_context,
            opener=provider_http.urlopen,
        )
    return PROVIDER_HTTP_CLIENT


def intervals_client(config: Config | None = None) -> intervals_client_module.IntervalsClient:
    """Compose an Intervals client with the active provider transport and clock."""
    return intervals_client_module.IntervalsClient(
        config or CONFIG,
        request=lambda *args, **kwargs: provider_http_client().request(*args, **kwargs),
        now=lambda: local_now(),
    )


def gemini_json_client() -> gemini_provider.GeminiJsonClient:
    """Compose the Gemini JSON adapter from the active runtime settings."""
    return gemini_provider.GeminiJsonClient(
        api_key=CONFIG.gemini_api_key,
        base_url=GEMINI_API_BASE_URL,
        response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
        http_client=provider_http_client(),
        provider_state=provider_state_service(),
    )


def audio_transcription_client() -> audio_provider.AudioTranscriptionClient:
    """Compose the transient audio adapter from active provider settings."""
    return audio_provider.AudioTranscriptionClient(
        max_audio_bytes=MAX_AUDIO_BODY_BYTES,
        openai_api_key=CONFIG.openai_api_key,
        gemini_api_key=CONFIG.gemini_api_key,
        openai_base_url=CONFIG.openai_base_url,
        default_openai_base_url=DEFAULT_OPENAI_BASE_URL,
        openai_transcription_model="gpt-transcribe",
        response_timeout_seconds=90,
        http_client=provider_http_client(),
        gemini_client=gemini_json_client(),
    )


def gemini_stream_client() -> gemini_provider.GeminiStreamClient:
    """Compose the Gemini streaming client from the active runtime settings."""
    return gemini_provider.GeminiStreamClient(
        api_key=CONFIG.gemini_api_key,
        base_url=GEMINI_API_BASE_URL,
        response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
        max_bytes=provider_http.MAX_EXTERNAL_RESPONSE_BYTES,
        app_version=APP_VERSION,
        json_media_type=JSON_MEDIA_TYPE,
        provider_state=provider_state_service(),
        logger=LOGGER,
        opener=gemini_provider.urlopen,
        monotonic=time.perf_counter,
        now=utc_now,
    )


def openai_responses_client() -> openai_provider.OpenAIResponsesClient:
    """Compose the OpenAI Responses adapter from the active runtime settings."""
    return openai_provider.OpenAIResponsesClient(
        api_key=CONFIG.openai_api_key,
        base_url=CONFIG.openai_base_url,
        default_base_url=DEFAULT_OPENAI_BASE_URL,
        responses_path=OPENAI_RESPONSES_PATH,
        response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
        background_poll_seconds=OPENAI_BACKGROUND_POLL_SECONDS,
        background_max_seconds=OPENAI_BACKGROUND_MAX_SECONDS,
        thinking_level=SETTINGS.selected_thinking_level,
        http_client=provider_http_client(),
        provider_state=provider_state_service(),
        logger=LOGGER,
        monotonic=time.monotonic,
        wait=time.sleep,
    )


def coach_conversation_provision_service() -> CoachConversationProvisionService:
    """Compose the Coach conversation ID provisioner from active services."""
    return CoachConversationProvisionService(
        SETTINGS,
        database_manager(),
        KEY_VALUE_REPOSITORY,
        openai_responses_client(),
        DB_LOCK,
        uuid.uuid4,
    )


def coach_conversation_reset_service() -> CoachConversationResetService:
    """Compose the Coach chat reset owner from concrete storage and provider adapters."""
    return CoachConversationResetService(
        database_manager(), KEY_VALUE_REPOSITORY, openai_responses_client(),
        coach_streams.CHAT_STREAM_REGISTRY, DB_LOCK, COACH_CONVERSATION_GATE.lock,
        utc_now, uuid.uuid4, LOGGER,
    )


def openai_stream_client() -> openai_provider.OpenAIStreamClient:
    """Compose the OpenAI streaming client from the active runtime settings."""
    return openai_provider.OpenAIStreamClient(
        openai_provider.OpenAIStreamConfig(
            api_key=CONFIG.openai_api_key,
            base_url=CONFIG.openai_base_url,
            default_base_url=DEFAULT_OPENAI_BASE_URL,
            responses_path=OPENAI_RESPONSES_PATH,
            timeout=OPENAI_RESPONSE_TIMEOUT_SECONDS,
        max_bytes=provider_http.MAX_EXTERNAL_RESPONSE_BYTES,
            app_version=APP_VERSION,
            media_type=JSON_MEDIA_TYPE,
        ),
        openai_provider.OpenAIStreamTelemetry(
            provider_state_service(),
            DIAGNOSTIC_CAPTURE,
            LOGGER,
            time.perf_counter,
            utc_now,
        ),
        SETTINGS.selected_thinking_level,
        opener=openai_provider.urlopen,
        wait=time.sleep,
    )


def external_calendar_events_for_date(target_date: str) -> list[dict[str, Any]]:
    today = local_now().date()
    return [
        event
        for event in external_calendar_reader().list_events(1000)
        if target_date
        in planning_context.external_calendar_event_dates(
            event,
            today=today,
            window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        )
    ]


def coach_quick_actions_service() -> CoachQuickActionsService:
    """Compose local quick-action reads and their public Coach projection."""
    return CoachQuickActionsService(
        database_manager(), KEY_VALUE_REPOSITORY, adaptive_replan_preview_service(),
        lambda: local_now().date(), PLANNED_WORKOUT_LABEL,
    )


def gemini_conversation_history_service() -> GeminiConversationHistoryService:
    """Compose bounded, restart-safe local Gemini history persistence."""
    return GeminiConversationHistoryService(database_manager(), KEY_VALUE_REPOSITORY)


def coach_message_service() -> CoachMessageService:
    """Compose local chat persistence and committed state-event publication."""
    return CoachMessageService(database_manager(), CHAT_REPOSITORY, runtime_events.STATE_EVENT_BUFFER)


def coach_conversation_history_service() -> CoachConversationHistoryService:
    """Compose local conversation history reads from shared persistence state."""
    return CoachConversationHistoryService(
        database_manager(), CHAT_REPOSITORY, KEY_VALUE_REPOSITORY, DB_LOCK
    )


def coach_job_store() -> CoachJobStore:
    """Compose durable Coach background-job persistence."""
    return CoachJobStore(
        database_manager, DB_LOCK, COACH_JOB_WORKER.wake_event,
        runtime_maintenance.MAINTENANCE_GATE, utc_now,
    )


def coach_turn_failure_service() -> CoachTurnFailureService:
    """Compose durable terminal Coach failure handling from current resources."""
    return CoachTurnFailureService(
        CoachTurnFailureDependencies(
            database_manager=database_manager,
            database_lock=DB_LOCK,
            chat_repository=CHAT_REPOSITORY,
            key_values=KEY_VALUE_REPOSITORY,
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            redactor=REDACTOR,
            utc_now=utc_now,
            repository_root=ROOT,
            read_only_tools=frozenset(STRUCTURED_READ_ONLY_TOOLS),
        )
    )


def coach_job_submission_service() -> CoachJobSubmissionService:
    """Compose validation and committed side effects for background submissions."""
    return CoachJobSubmissionService(
        database_manager, CHAT_REPOSITORY, DB_LOCK, SETTINGS,
        runtime_events.STATE_EVENT_BUFFER, coach_streams.CHAT_STREAM_REGISTRY,
        COACH_JOB_WORKER.wake_event, utc_now,
        background_horizon_days=coach_limits.COACH_BACKGROUND_HORIZON_DAYS,
        max_attachment_storage_bytes=coach_attachments.MAX_ATTACHMENT_STORAGE_BYTES,
        max_gemini_inline_image_bytes=coach_attachments.MAX_GEMINI_INLINE_IMAGE_BYTES,
    )


def coach_cancellation_service() -> CoachCancellationService:
    """Compose session-scoped Coach cancellation from its state owners."""
    return CoachCancellationService(
        coach_job_submission_service(), coach_job_store(),
        coach_streams.CHAT_STREAM_REGISTRY,
    )


def coach_dialogue_read_service() -> CoachDialogueReadService:
    """Compose local, read-only Coach dialogue projections."""
    manager = database_manager()
    return CoachDialogueReadService(
        manager, coach_message_service(), KEY_VALUE_REPOSITORY, profile_service()
    )


def coach_dialogue_action_service() -> CoachDialogueActionService:
    """Compose live dialogue authorization with its existing state owners."""
    manager = database_manager()
    return CoachDialogueActionService(
        manager,
        DB_LOCK,
        sync_job_queue_service,
        CoachDialoguePlanScopeService(manager, DB_LOCK),
        lambda: local_now().date(),
    )


def coach_clarification_service() -> CoachClarificationService:
    """Compose persistence for validated pending Coach questions."""
    return CoachClarificationService(database_manager(), KEY_VALUE_REPOSITORY, DB_LOCK)


def coach_attachment_context_service() -> CoachAttachmentContextService:
    """Compose local attachment reads for the current Coach turn."""
    return CoachAttachmentContextService(database_manager())


def manual_morning_checkin_service() -> ManualMorningCheckinService:
    """Compose the fresh-sleep gate for explicit morning Coach requests."""
    return ManualMorningCheckinService(
        garmin_sync_service(), garmin_payload_service(), morning_body_battery_service(),
        lambda: local_now().date(), LOGGER,
    )


def morning_checkin_state_service() -> MorningCheckinStateService:
    """Compose the local morning check-in state projection."""
    return MorningCheckinStateService(
        database_manager(), KEY_VALUE_REPOSITORY, lambda: local_now().date()
    )


def gemini_local_chat_history_service() -> GeminiLocalChatHistoryService:
    """Compose the read-only local-message projection for Gemini."""
    return GeminiLocalChatHistoryService(
        database_manager(), CHAT_REPOSITORY, max_inline_bytes=coach_attachments.MAX_GEMINI_INLINE_IMAGE_BYTES
    )


def gemini_request_payload_service() -> GeminiRequestPayloadService:
    """Compose Gemini's bounded, persisted request-history builder."""
    return GeminiRequestPayloadService(
        gemini_conversation_history_service(), gemini_local_chat_history_service(),
        database_manager(), KEY_VALUE_REPOSITORY,
    )


def gemini_response_normalization_service() -> GeminiResponseNormalizationService:
    """Compose Gemini response and durable function-call normalization."""
    return GeminiResponseNormalizationService(
        gemini_conversation_history_service(), database_manager(), KEY_VALUE_REPOSITORY,
        uuid.uuid4,
    )


def gemini_conversation_response_service() -> GeminiConversationResponseService:
    """Compose Gemini conversation response orchestration."""
    return GeminiConversationResponseService(
        gemini_request_payload_service(),
        gemini_response_normalization_service(),
        gemini_json_client(),
        gemini_stream_client(),
        settings_service=SETTINGS,
        default_thinking_level=SETTINGS.selected_thinking_level(),
        default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
        json_media_type=JSON_MEDIA_TYPE,
    )


CHAT_PAGE_MAX = 100


def library_page_service() -> LibraryPageService:
    """Compose the read-only workout-library page query."""
    return LibraryPageService(database_manager())


def chat_history_page_service() -> ChatHistoryPageService:
    """Compose bounded local chat history and session-bound proposal reads."""
    return ChatHistoryPageService(
        coach_conversation_history_service(),
        coach_proposal_read_service(),
        maximum=CHAT_PAGE_MAX,
    )


def coach_proposal_read_service() -> CoachProposalReadService:
    """Compose session-bound Coach proposal reads and expiration cleanup."""
    return CoachProposalReadService(database_manager(), now=time.time)


def coach_command_receipt_service() -> CoachCommandReceiptService:
    """Compose session-bound Coach command receipt reads."""
    return CoachCommandReceiptService(
        database_manager, DB_LOCK, now=time.time,
    )


def coach_turn_opening_service() -> CoachTurnOpeningService:
    """Compose atomic creation and session binding for a new Coach turn."""
    return CoachTurnOpeningService(
        database_manager(), DB_LOCK, CHAT_REPOSITORY,
        coach_command_receipt_service(), utc_now, uuid.uuid4,
    )


def coach_proposal_creation_service() -> CoachProposalCreationService:
    """Compose session-bound Coach proposal creation."""
    return CoachProposalCreationService(
        database_manager(), sync_state_repository(), now=time.time, utc_now=utc_now,
        uuid_factory=uuid.uuid4,
    )


def coach_proposal_confirmation_service() -> CoachProposalConfirmationService:
    """Compose atomic, session-bound confirmation of Coach action previews."""
    return CoachProposalConfirmationService(database_manager(), now=time.time)


def coach_proposal_execution_service() -> CoachProposalExecutionService:
    """Compose guarded dispatch for confirmed Coach actions."""
    return CoachProposalExecutionService(
        database_manager(), duplicate_activity_service(), history_undo_service(),
        intervals_client, runtime_maintenance.MAINTENANCE_GATE,
        now=time.time, utc_now=utc_now,
    )


LIBRARY_SYNC_PREVIEW_TTL_SECONDS = 10 * 60


def coach_structured_context_service() -> CoachStructuredContextService:
    """Compose the authoritative, read-only Coach context builder."""
    return CoachStructuredContextService(
        sync_state_repository(),
        checkin_service(),
        weather_service(),
        activity_feedback_service(),
        CoachPlanningContextReader(
            planned_unit_service(),
            daily_planning_context_service(),
            external_calendar_reader(),
            competition_service(),
            training_plan_service(),
            adaptive_replan_preview_service(),
            lambda: local_now().date(),
        ),
        CoachPerformanceContextReader(
            profile_service(),
            garmin_payload_service(),
            garmin_projection_service(),
            lambda: local_now().date(),
        ),
    )


def coach_training_context_service() -> CoachTrainingContextService:
    """Compose bounded Coach prompt context from concrete read services."""
    return CoachTrainingContextService(
        sync_state_repository(), coach_structured_context_service(), workout_library_service(),
        local_planned_limit=coach_context_module.COACH_LOCAL_PLANNED_LIMIT,
        library_limit=coach_context_module.COACH_LIBRARY_LIMIT,
        library_description_limit=coach_context_module.COACH_LIBRARY_DESCRIPTION_LIMIT,
        section_limits=coach_context_module.COACH_CONTEXT_SECTION_LIMITS,
        total_char_limit=coach_context_module.COACH_CONTEXT_TOTAL_CHAR_LIMIT,
        activity_limit_per_sport=coach_context_module.COACH_RECENT_ACTIVITIES_PER_SPORT,
        planned_event_limit=coach_context_module.COACH_PLANNED_EVENT_LIMIT,
    )


def coach_request_payload_service() -> CoachRequestPayloadService:
    """Compose the stateless structured Coach request builder."""
    return CoachRequestPayloadService(
        coach_training_context_service(), SETTINGS,
        coach_limits.COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
    )


def coach_context_preview_service() -> CoachContextPreviewService:
    """Compose read-only, user-inspectable Coach context preview."""
    return CoachContextPreviewService(
        sync_state_repository(), coach_message_service(), coach_training_context_service(),
        coach_structured_context_service(), workout_library_service(),
        CoachContextPreviewLimits(
            library_limit=coach_context_module.COACH_LIBRARY_LIMIT,
            library_description_limit=coach_context_module.COACH_LIBRARY_DESCRIPTION_LIMIT,
            section_limits=coach_context_module.COACH_CONTEXT_SECTION_LIMITS,
            total_char_limit=coach_context_module.COACH_CONTEXT_TOTAL_CHAR_LIMIT,
            local_planned_limit=coach_context_module.COACH_LOCAL_PLANNED_LIMIT,
            activity_limit_per_sport=coach_context_module.COACH_RECENT_ACTIVITIES_PER_SPORT,
            planned_event_limit=coach_context_module.COACH_PLANNED_EVENT_LIMIT,
        ),
        utc_now=lambda: datetime.now(timezone.utc),
    )


def coach_response_transport() -> CoachResponseTransport:
    """Compose concrete OpenAI and Gemini response adapters."""
    return CoachResponseTransport(
        SETTINGS, openai_responses_client, openai_stream_client,
        gemini_conversation_response_service,
    )


COACH_CANONICAL_TOOL_NAMES, COACH_STRUCTURED_TOOLS, STRUCTURED_READ_ONLY_TOOLS, COACH_DIALOGUE_TOOLS = build_tool_contracts(
    default_profile=DEFAULT_PROFILE,
    checkin_text_limits=CHECKIN_TEXT_LIMITS,
    checkin_score_fields=CHECKIN_SCORE_FIELDS,
    training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
    library_bulk_max_entries=planning_library.LIBRARY_BULK_MAX_ENTRIES,
    training_plan_statuses=planning_training_plans.TRAINING_PLAN_STATUSES,
    dialogue_tools=dialogue_tools,
)


def coach_tool_dispatch_service() -> CoachToolDispatchService:
    """Compose the concrete Coach tool owners without retaining tool logic."""
    return CoachToolDispatchService(
        coach_read_tool_service,
        coach_profile_update_service,
        coach_athlete_record_tool_service,
        lambda: CoachPlanArtifactToolService(training_plan_artifact_service),
        lambda: CoachPlanningChangeToolService(
            structured_training_plan_replacement_service,
            structured_training_change_service,
        ),
        lambda: TrainingTemplateToolService(
            database_manager, DB_LOCK, workout_library_service
        ),
        coach_library_plan_tool_service,
        coach_sync_tool_service,
        lambda: CoachPlanningActionToolService(
            adaptive_replan_preview_service,
            coach_adaptive_apply_service,
            training_plan_service,
            history_undo_service,
            coach_proposal_creation_service,
        ),
    )


def coach_structured_tool_execution_service() -> CoachStructuredToolExecutionService:
    """Compose the concrete owners used for structured Coach tool execution."""
    return CoachStructuredToolExecutionService(
        database_manager(),
        DB_LOCK,
        KEY_VALUE_REPOSITORY,
        coach_clarification_service(),
        coach_training_patch_service(),
        sync_state_repository(),
        coach_proposal_creation_service(),
        coach_tool_dispatch_service(),
    )


def coach_structured_tool_failure_service() -> CoachStructuredToolFailureService:
    """Compose structured tool failure projection from safe diagnostics."""
    return CoachStructuredToolFailureService(
        ROOT,
        LOGGER,
        frozenset(tool["name"] for tool in COACH_DIALOGUE_TOOLS),
    )


def coach_structured_tool_round_journal() -> CoachStructuredToolRoundJournal:
    """Compose the round journal with its durable Coach job-store owner."""
    return CoachStructuredToolRoundJournal(coach_job_store())


def coach_planning_command_service() -> CoachPlanningCommandService:
    """Compose the durable, session-bound local planning command owner."""
    return CoachPlanningCommandService(
        database_manager(), DB_LOCK, coach_command_receipt_service(),
        coach_tool_dispatch_service(), coach_turn_failure_service(), utc_now,
    )


def coach_structured_tool_replay_service() -> CoachStructuredToolReplayService:
    """Compose structured tool replay lookup with the active DB and allowlist."""
    return CoachStructuredToolReplayService(
        database_manager(), DB_LOCK, frozenset(STRUCTURED_READ_ONLY_TOOLS)
    )


def coach_structured_outcome_service() -> CoachStructuredOutcomeService:
    """Compose final Coach outcome projection and pending-request storage."""
    return CoachStructuredOutcomeService(
        database_manager(), DB_LOCK, KEY_VALUE_REPOSITORY,
        frozenset(STRUCTURED_READ_ONLY_TOOLS),
    )


def coach_structured_tool_preparation_service() -> CoachStructuredToolPreparationService:
    """Compose structured tool preparation with current Coach state owners."""
    return CoachStructuredToolPreparationService(
        coach_dialogue_action_service(),
        sync_state_repository(),
        planning_authority_service(),
        frozenset(STRUCTURED_READ_ONLY_TOOLS),
        SYNC_PERIOD_DEFAULTS,
        ALL_SYNC_DAYS,
    )


def coach_conversation_recovery_service() -> CoachConversationRecoveryService:
    """Compose the durable recovery owner from concrete storage services."""
    return CoachConversationRecoveryService(
        database_manager(), DB_LOCK, KEY_VALUE_REPOSITORY, coach_job_store(), LOGGER,
    )


def coach_response_retry_policy() -> CoachResponseRetryPolicy:
    """Compose retry policy with the application logger."""
    return CoachResponseRetryPolicy(LOGGER)


def coach_structured_response_service() -> CoachStructuredResponseService:
    """Compose the response loop from concrete transport and durable owners."""
    return CoachStructuredResponseService(
        coach_response_transport(), coach_conversation_recovery_service(),
        coach_response_retry_policy(), coach_job_store(),
    )


def coach_structured_tool_round_service() -> CoachStructuredToolRoundService:
    """Compose the concrete owners of tool transactions and provider follow-up."""
    return CoachStructuredToolRoundService(
        database_manager, DB_LOCK,
        coach_structured_tool_replay_service(), coach_structured_tool_preparation_service(),
        coach_structured_tool_execution_service(), coach_structured_tool_failure_service(),
        coach_structured_tool_round_journal(), coach_job_store(), coach_training_context_service(),
        coach_structured_response_service(), CoachStructuredToolRoundLimits(
            max_rounds=structured_tool_round.COACH_TOOL_MAX_ROUNDS,
            background_horizon_days=coach_limits.COACH_BACKGROUND_HORIZON_DAYS,
            default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
            long_plan_max_output_tokens=coach_limits.COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
        ),
    )






def coach_final_receipt_service() -> CoachFinalReceiptService:
    """Compose the atomic final Coach receipt owner."""
    return CoachFinalReceiptService(
        database_manager(), DB_LOCK, CHAT_REPOSITORY, KEY_VALUE_REPOSITORY,
        runtime_events.STATE_EVENT_BUFFER, utc_now,
    )


def coach_structured_turn_service() -> CoachStructuredTurnService:
    """Compose the complete structured turn from concrete Coach owners."""
    return CoachStructuredTurnService(CoachStructuredTurnDependencies(
        opening=coach_turn_opening_service(),
        attachments=coach_attachment_context_service(),
        dialogue=coach_dialogue_read_service(),
        payload=coach_request_payload_service(),
        response=coach_structured_response_service(),
        rounds=coach_structured_tool_round_service(),
        outcome=coach_structured_outcome_service(),
        final_receipt=coach_final_receipt_service(),
        failure=coach_turn_failure_service(),
        tools=COACH_DIALOGUE_TOOLS,
        read_only_tools=frozenset(STRUCTURED_READ_ONLY_TOOLS),
        logger=LOGGER,
        root=ROOT,
    ))




def coach_chat_turn_service() -> CoachChatTurnService:
    """Compose the session-bound chat turn owner."""
    return CoachChatTurnService(
        database_manager, DB_LOCK, coach_command_receipt_service(), SETTINGS,
        coach_conversation_provision_service, coach_structured_turn_service, utc_now,
        COACH_CONVERSATION_GATE, runtime_maintenance.MAINTENANCE_GATE,
    )


def morning_coach_job_completion_service() -> MorningCoachJobCompletionService:
    return MorningCoachJobCompletionService(
        database_manager(), DB_LOCK, KEY_VALUE_REPOSITORY,
        coach_quick_actions_service, local_now, utc_now,
    )


def coach_background_job_runner() -> CoachBackgroundJobRunner:
    return CoachBackgroundJobRunner(
        coach_job_store(), coach_chat_turn_service, session_auth_service,
        coach_streams.CHAT_STREAM_REGISTRY, manual_morning_checkin_service,
        morning_coach_job_completion_service, coach_turn_failure_service,
        runtime_maintenance.MAINTENANCE_GATE, REDACTOR, LOGGER,
    )


def local_now() -> datetime:
    configured_timezone = timezone_name(profile_service().get().get("timezone"))
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(configured_timezone))
    except Exception:
        return datetime.now().astimezone()


def public_bootstrap_service() -> PublicBootstrapService:
    """Compose the local bootstrap read from its owning backend services."""
    return PublicBootstrapService(
        PublicBootstrapDependencies(
            database_manager=database_manager,
            database_lock=DB_LOCK,
            config=CONFIG,
            app_name=APP_NAME,
            app_version=APP_VERSION,
            key_values=KEY_VALUE_REPOSITORY,
            sync_state_repository=sync_state_repository,
            planned_unit_service=planned_unit_service,
            competition_service=competition_service,
            external_calendar_reader=external_calendar_reader,
            profile_service=profile_service,
            provider_freshness_service=provider_freshness_service,
            garmin_sync_state_service=garmin_sync_state_service,
            garmin_sync_service=garmin_sync_service,
            sync_job_queue_service=sync_job_queue_service,
            state_version_service=state_version_service,
            coach_message_service=coach_message_service,
            training_plan_service=training_plan_service,
            local_calendar_events=calendar_local.local_calendar_events,
            planning_state=planning_season.planning_state,
            adaptive_replan_preview_service=adaptive_replan_preview_service,
            external_calendar_sync_service=external_calendar_sync_service,
            external_calendar_window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
            planned_calendar_history_days=PLANNED_CALENDAR_HISTORY_DAYS,
            planned_calendar_future_days=PLANNED_CALENDAR_FUTURE_DAYS,
            garmin_projection_service=garmin_projection_service,
            diagnostic_capture=DIAGNOSTIC_CAPTURE,
            intervals_public_state=intervals_state.public_state,
            intervals_sync_lock=INTERVALS_SYNC_LOCK,
            workout_library_sync_running=workout_library_sync_running,
            workout_library_sync_state_service=workout_library_sync_state_service,
            full_provider_resync_service=full_provider_resync_service,
            sync_public_state_service=sync_public_state_service,
            sync_period_defaults=SYNC_PERIOD_DEFAULTS,
            all_sync_days=ALL_SYNC_DAYS,
            settings=SETTINGS,
            local_date=lambda: local_now().date(),
            morning_checkin_state_service=morning_checkin_state_service,
            coach_quick_actions_service=coach_quick_actions_service,
            provider_state_service=provider_state_service,
        )
    )


def public_plan_state_service() -> PublicPlanStateService:
    """Compose the public planning projection from its concrete read owners."""
    return PublicPlanStateService(PublicPlanDependencies(
        sync_state=sync_state_repository(),
        planned_units=planned_unit_service(),
        activity_feedback=activity_feedback_service(),
        weather=weather_service(),
        adaptive_followup=adaptive_preview_followup_service(),
        database_manager_factory=database_manager,
        db_lock=DB_LOCK,
        key_values=KEY_VALUE_REPOSITORY,
        training_plans=training_plan_service(),
        external_calendar=external_calendar_reader(),
        external_calendar_sync=external_calendar_sync_service(),
        daily_context=daily_planning_context_service(),
        checkins=checkin_service(),
        competitions=competition_service(),
        adaptive_preview=adaptive_replan_preview_service(),
        coach_quick_actions=coach_quick_actions_service(),
        today=lambda: local_now().date(),
        external_calendar_configured=bool(CONFIG.calendar_ical_url),
        external_calendar_window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        default_workout_name=PLANNED_WORKOUT_LABEL,
    ))


def public_state_local_prelude_service() -> PublicStateLocalPrelude:
    """Compose the local bootstrap read with its existing transaction owner."""
    return PublicStateLocalPrelude(
        sync_state_repository(), activity_feedback_service(),
        planned_unit_service(), weather_service(), database_manager(),
        DB_LOCK, lambda: local_now().date(),
        CalendarWindowRange(PLANNED_CALENDAR_HISTORY_DAYS, PLANNED_CALENDAR_FUTURE_DAYS),
    )


def public_state_weather_prelude_service() -> PublicStateWeatherPrelude:
    """Compose weather refresh after the local bootstrap lock is released."""
    return PublicStateWeatherPrelude(weather_service(), adaptive_preview_followup_service())


def public_state_calendar_projection_service() -> PublicStateCalendarProjection:
    """Compose the calendar portion of the public bootstrap projection."""
    return PublicStateCalendarProjection(
        checkin_service(),
        competition_service(),
        external_calendar_reader(),
        external_calendar_sync_service(),
        daily_planning_context_service(),
        external_calendar_configured=bool(CONFIG.calendar_ical_url),
        external_calendar_window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        default_workout_name=PLANNED_WORKOUT_LABEL,
        today=lambda: local_now().date(),
    )


def public_state_service() -> PublicStateService:
    """Compose the public state projection from concrete backend owners."""
    with DB_LOCK:
        return PublicStateService(
            PublicStateDependencies(
                local_prelude=public_state_local_prelude_service(),
                weather_prelude=public_state_weather_prelude_service(),
                calendar_projection=public_state_calendar_projection_service(),
                database_manager=database_manager,
                database_lock=DB_LOCK,
                key_values=KEY_VALUE_REPOSITORY,
                app_name=APP_NAME,
                app_version=APP_VERSION,
                config=CONFIG,
                settings=SETTINGS,
                coach_messages=coach_message_service(),
                training_plans=training_plan_service(),
                workout_library=workout_library_service(),
                profile=profile_service(),
                public_feedback=public_feedback_state_service(),
                public_performance=public_performance_state_service(),
                sync_state=sync_state_repository(),
                provider_freshness=provider_freshness_service(),
                garmin_sync_state=garmin_sync_state_service(),
                sync_public_state=sync_public_state_service(),
                intervals_sync_lock=INTERVALS_SYNC_LOCK,
                workout_library_sync_running=workout_library_sync_running,
                workout_library_sync_state=workout_library_sync_state_service(),
                garmin_sync=garmin_sync_service(),
                provider_resync=full_provider_resync_service(),
                planning_preview=adaptive_replan_preview_service(),
                morning_checkin=morning_checkin_state_service(),
                coach_quick_actions=coach_quick_actions_service(),
                provider_state=provider_state_service(),
                sync_period_defaults=SYNC_PERIOD_DEFAULTS,
                all_sync_days=ALL_SYNC_DAYS,
                calendar_history_days=PLANNED_CALENDAR_HISTORY_DAYS,
                calendar_future_days=PLANNED_CALENDAR_FUTURE_DAYS,
                local_now=local_now,
            )
        )


def recent_log_entries_service() -> RecentLogEntriesService:
    return RecentLogEntriesService(LOG_PATH, REDACTOR, utc_now)


def coach_diagnostic_history_service() -> CoachDiagnosticHistoryService:
    return CoachDiagnosticHistoryService(
        database=database_manager().unit_of_work,
        db_lock=DB_LOCK,
        redact=REDACTOR.sanitize_log_value,
        receipt_parser=command_receipt,
        allowed_tools={tool["name"] for tool in COACH_DIALOGUE_TOOLS},
    )


def diagnostic_report_service() -> DiagnosticReportService:
    """Compose the privacy-safe diagnostics report from its owning services."""
    return DiagnosticReportService(DiagnosticReportDependencies(
        database_manager=database_manager(),
        db_lock=DB_LOCK,
        key_values=KEY_VALUE_REPOSITORY,
        config=CONFIG,
        settings=SETTINGS,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        utc_now=utc_now,
        sync_state=sync_state_repository(),
        garmin_projection=garmin_projection_service(),
        garmin_client_factory=garmin_client_factory(),
        garmin_fixture_loader=garmin_fixture_loader(),
        provider_state=provider_state_service(),
        coach_history=coach_diagnostic_history_service(),
        redactor=REDACTOR,
        provider_freshness=provider_freshness_service(),
        profile=profile_service(),
        garmin_sync_state=garmin_sync_state_service(),
        external_calendar_sync=external_calendar_sync_service(),
        external_calendar_reader=external_calendar_reader(),
        morning_checkin=morning_checkin_state_service(),
        workout_library_sync_state=workout_library_sync_state_service(),
        recent_logs=recent_log_entries_service(),
        diagnostic_capture=DIAGNOSTIC_CAPTURE,
    ))


def privacy_archive_export_service() -> PrivacyArchiveExportService:
    """Compose the local privacy archive use case."""
    return PrivacyArchiveExportService(
        database_manager(),
        DB_LOCK,
        KEY_VALUE_REPOSITORY,
        profile_service(),
        competition_service(),
        adaptive_replan_preview_service(),
        PrivacyArchiveExportConfig(
            DATA_DIR,
            DB_PATH,
            lambda: local_now().date(),
            utc_now,
            maximum_bytes=MAX_PRIVACY_EXPORT_BYTES,
            minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
            time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
        ),
    )


def database_backup_service() -> DatabaseBackupService:
    """Compose the locked, bounded database-backup resource owner."""
    return DatabaseBackupService(
        database_manager(),
        DB_LOCK,
        DatabaseBackupConfig(
            database_path=DB_PATH,
            data_dir=DATA_DIR,
            maximum_bytes=MAX_BACKUP_BYTES,
            minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
            time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
        ),
        LOGGER,
    )


def export_stream_transport() -> ExportStreamTransport:
    """Wire backup/export use cases into their HTTP download transport."""
    return ExportStreamTransport(
        database_backup_service,
        privacy_archive_export_service,
        monotonic=time.monotonic,
        time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
    )


def database_restore_validation_service() -> DatabaseRestoreValidationService:
    return DatabaseRestoreValidationService(
        DatabaseRestoreValidationConfig(
            data_dir=DATA_DIR,
            maximum_bytes=MAX_BACKUP_BYTES,
            app_password=CONFIG.app_password,
            sqlcipher_available=SQLCIPHER_AVAILABLE,
            sqlite_backend=sqlite_backend,
            configure_cipher=configure_cipher,
            row_factory=database_row_factory,
            schema_is_current=database_schema_is_current,
        )
    )


def database_restore_service() -> DatabaseRestoreService:
    """Compose the validated, maintenance-bound database restore owner."""
    return DatabaseRestoreService(
        database_restore_validation_service(),
        database_backup_service(),
        database_manager,
        DB_LOCK,
        runtime_maintenance.MAINTENANCE_GATE,
        sync_job_queue_service(),
        coach_job_store(),
        coach_turn_failure_service(),
        shared_sync_job_wake_event(),
        COACH_JOB_WORKER.wake_event,
        DatabaseRestoreConfig(DATA_DIR, DB_PATH),
        REDACTOR.redact_text,
    )


def readiness_service() -> ReadinessService:
    """Compose the public readiness probe from its concrete dependencies."""
    return ReadinessService(
        database_manager, DB_LOCK, DATA_DIR, runtime_maintenance.MAINTENANCE_GATE
    )


COACH_GET_ROUTES = CoachGetRoutes(
    session_auth_service,
    chat_history_page_service,
    coach_command_receipt_service,
    coach_job_submission_service,
)
PUBLIC_GET_ROUTES = PublicGetRoutes(
    runtime_maintenance.MAINTENANCE_GATE,
    readiness_service,
    session_auth_service,
    public_bootstrap_service,
)
PLANNING_GET_ROUTES = PlanningGetRoutes(
    session_auth_service,
    public_plan_state_service,
    public_weather_state_service,
    library_page_service,
)
ATHLETE_GET_ROUTES = AthleteGetRoutes(
    session_auth_service,
    public_performance_state_service,
    profile_service,
    competition_service,
    public_feedback_state_service,
    coach_context_preview_service,
    SETTINGS,
)
DIAGNOSTICS_GET_ROUTES = DiagnosticsGetRoutes(
    session_auth_service,
    recent_log_entries_service,
    diagnostic_report_service,
    DIAGNOSTIC_CAPTURE,
)
SYNC_GET_ROUTES = SyncGetRoutes(
    session_auth_service,
    sync_job_queue_service,
    sync_public_state_service,
    activity_read_service,
    lambda: local_now().date(),
    ALL_SYNC_DAYS,
)
HISTORY_GET_ROUTES = HistoryGetRoutes(session_auth_service, change_history_service)
HISTORY_UNDO_POST_ROUTES = HistoryUndoPostRoutes(
    history_undo_service,
    coach_proposal_creation_service,
)
COACH_ACTIONS_POST_ROUTES = CoachActionsPostRoutes(
    coach_proposal_confirmation_service,
    coach_proposal_execution_service,
)
CHAT_POST_ROUTES = ChatPostRoutes(
    coach_job_submission_service,
    coach_conversation_reset_service,
    coach_attachments.MAX_REQUEST_BYTES,
)
CHAT_STREAM_TRANSPORT = CoachChatStreamTransport(
    coach_streams.CHAT_STREAM_REGISTRY,
    coach_job_submission_service,
    coach_command_receipt_service,
    REDACTOR.redact_text,
    LOGGER,
    max_request_bytes=coach_attachments.MAX_REQUEST_BYTES,
    response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
)
TRANSCRIBE_POST_ROUTES = TranscribePostRoutes(SETTINGS, audio_transcription_client)
DIAGNOSTICS_CAPTURE_POST_ROUTES = DiagnosticsCapturePostRoutes(DIAGNOSTIC_CAPTURE)
PRIVACY_DELETE_POST_ROUTES = PrivacyDeletePostRoutes(privacy_delete_service)
PRIVACY_GET_ROUTES = PrivacyGetRoutes(
    session_auth_service, export_stream_transport, privacy_delete_service
)
STATE_EVENTS_GET_ROUTES = StateEventsGetRoutes(
    session_auth_service,
    StateEventTransport(runtime_events.STATE_EVENT_BUFFER),
)
SETTINGS_PUT_ROUTES = SettingsPutRoutes(SETTINGS)
ATHLETE_PUT_ROUTES = AthletePutRoutes(athlete_context_service, profile_service)
PLANNING_COMMANDS_POST_ROUTES = PlanningCommandsPostRoutes(
    coach_planning_command_service,
    lambda: coach_conversation_provision_service(),
)
FEEDBACK_POST_ROUTES = FeedbackPostRoutes(checkin_service)
CHAT_CANCEL_POST_ROUTES = ChatCancelPostRoutes(coach_cancellation_service)
PRIVACY_RESTORE_POST_ROUTES = PrivacyRestorePostRoutes(
    session_auth_service, database_restore_service, MAX_BACKUP_BYTES
)
AUTH_POST_ROUTES = AuthPostRoutes(
    session_auth_service, runtime_maintenance.MAINTENANCE_GATE
)
NUTRITION_GET_ROUTES = NutritionGetRoutes(
    session_auth_service, nutrition_service, local_now
)
NUTRITION_POST_ROUTES = NutritionPostRoutes(
    nutrition_service, intervals_nutrition_sync_service
)
NUTRITION_PUT_ROUTES = NutritionPutRoutes(nutrition_service)
HTTP_ROUTE_DISPATCHER = HttpRouteDispatcher(
    (
        PUBLIC_GET_ROUTES,
        PLANNING_GET_ROUTES,
        SYNC_GET_ROUTES,
        STATE_EVENTS_GET_ROUTES,
        COACH_GET_ROUTES,
        ATHLETE_GET_ROUTES,
        HISTORY_GET_ROUTES,
        DIAGNOSTICS_GET_ROUTES,
        PRIVACY_GET_ROUTES,
        NUTRITION_GET_ROUTES,
    ),
    (SETTINGS_PUT_ROUTES, ATHLETE_PUT_ROUTES, NUTRITION_PUT_ROUTES),
)
SYNC_COMMAND_POST_ROUTE = SyncCommandPostRoute(lambda: sync_command_endpoint())
AUTHENTICATED_POST_ROUTES = HttpAuthenticatedPostRoutes(
    COACH_ACTIONS_POST_ROUTES,
    CHAT_POST_ROUTES,
    TRANSCRIBE_POST_ROUTES,
    PLANNING_COMMANDS_POST_ROUTES,
    FEEDBACK_POST_ROUTES,
    CHAT_STREAM_TRANSPORT,
    SYNC_COMMAND_POST_ROUTE,
    HISTORY_UNDO_POST_ROUTES,
    DIAGNOSTICS_CAPTURE_POST_ROUTES,
    PRIVACY_DELETE_POST_ROUTES,
    NUTRITION_POST_ROUTES,
)
HTTP_POST_DISPATCHER = HttpPostDispatcher(
    AUTH_POST_ROUTES,
    PRIVACY_RESTORE_POST_ROUTES,
    CHAT_CANCEL_POST_ROUTES,
    AUTHENTICATED_POST_ROUTES,
)
HTTP_RESPONSE_TRANSPORT = HttpResponseTransport()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = f"IntervalsCoach/{APP_VERSION}"
    client_disconnect_errors = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)
    static_asset_service: StaticAssetService

    @property
    def auth_service(self) -> SessionAuthService:
        return session_auth_service()

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info(
            fmt % args,
            extra={
                "event": "http_access",
                "context": {"method": self.command, "path": urlparse(self.path).path, "request_id": getattr(self, "request_id", None)},
            },
        )

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def log_client_disconnect(self) -> None:
        context = {
            "method": self.command,
            "path": urlparse(self.path).path,
            "request_id": getattr(self, "request_id", None),
        }
        for attribute, key in (("_response_status", "response_status"), ("_response_bytes", "response_bytes"), ("_response_error_type", "error_type")):
            value = getattr(self, attribute, None)
            if value is not None:
                context[key] = value
        started = getattr(self, "_response_started_at", None)
        if started is not None:
            context["response_duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        LOGGER.info(
            "HTTP client disconnected before response completed",
            extra={
                "event": "http_client_disconnected",
                "context": context,
            },
        )

    def do_GET(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        try:
            path = urlparse(self.path).path
            HTTP_ROUTE_DISPATCHER.handle_get(self, path)
        except AppError as exc:
            if exc.status >= 500:
                LOGGER.exception(
                    exc.message,
                    extra={"event": "http_app_error", "context": {"method": "GET", "path": self.path, "status": exc.status, "request_id": self.request_id}},
                    exc_info=True,
                )
            self.send_json(public_app_error_status(exc), {"error": REDACTOR.redact_text(exc.message)[:1000]})
        except Exception:
            LOGGER.exception(
                "Unhandled GET error",
                extra={"event": "http_unhandled_error", "context": {"method": "GET", "path": self.path, "request_id": self.request_id}},
                exc_info=True,
            )
            self.send_json(500, {"error": INTERNAL_SERVER_ERROR})

    def do_POST(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        try:
            path = urlparse(self.path).path
            if HTTP_POST_DISPATCHER.handle_before_auth(self, path):
                return
            session = self.auth_service.require_auth(self)
            self.auth_service.require_csrf(self, session)
            if HTTP_POST_DISPATCHER.handle_before_maintenance(self, path, session):
                return
            with runtime_maintenance.MAINTENANCE_GATE.operation():
                HTTP_POST_DISPATCHER.handle_authenticated(self, path, session)
        except AppError as exc:
            if exc.status >= 500:
                LOGGER.exception(
                    exc.message,
                    extra={"event": "http_app_error", "context": {"method": "POST", "path": self.path, "status": exc.status, "request_id": self.request_id}},
                    exc_info=True,
                )
            status = public_app_error_status(exc)
            headers = {"WWW-Authenticate": "Session"} if status == 401 else None
            self.send_json(status, {"error": REDACTOR.redact_text(exc.message)[:1000]}, headers)
        except Exception:
            LOGGER.exception(
                "Unhandled POST error",
                extra={"event": "http_unhandled_error", "context": {"method": "POST", "path": self.path, "request_id": self.request_id}},
                exc_info=True,
            )
            self.send_json(500, {"error": INTERNAL_SERVER_ERROR})

    def send_sse_headers(self, *, persistent: bool = True) -> None:
        HTTP_RESPONSE_TRANSPORT.send_sse_headers(self, persistent=persistent)

    def send_sse_event(self, event: str, payload: Any, event_id: int | None = None) -> None:
        HTTP_RESPONSE_TRANSPORT.send_sse_event(self, event, payload, event_id)

    def do_PUT(self) -> None:
        try:
            with runtime_maintenance.MAINTENANCE_GATE.operation():
                self._do_PUT()
        except AppError as exc:
            self.send_json(public_app_error_status(exc), {"error": REDACTOR.redact_text(exc.message)[:1000]})

    def _do_PUT(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        try:
            path = urlparse(self.path).path
            session = self.auth_service.require_auth(self)
            self.auth_service.require_csrf(self, session)
            HTTP_ROUTE_DISPATCHER.handle_put(self, path)
        except AppError as exc:
            if exc.status >= 500:
                LOGGER.exception(
                    exc.message,
                    extra={"event": "http_app_error", "context": {"method": "PUT", "path": self.path, "status": exc.status, "request_id": self.request_id}},
                    exc_info=True,
                )
            self.send_json(public_app_error_status(exc), {"error": REDACTOR.redact_text(exc.message)[:1000]})
        except Exception:
            LOGGER.exception(
                "Unhandled PUT error",
                extra={"event": "http_unhandled_error", "context": {"method": "PUT", "path": self.path, "request_id": self.request_id}},
                exc_info=True,
            )
            self.send_json(500, {"error": INTERNAL_SERVER_ERROR})

    def read_body(self, max_bytes: int = MAX_BODY_BYTES) -> bytes:
        return read_request_body(
            self.headers,
            self.rfile.read,
            max_bytes,
            error=AppError,
            too_large_status_threshold=MAX_BODY_BYTES,
        )

    def read_audio_body(self) -> bytes:
        return read_request_audio_body(
            self.headers,
            self.rfile.read,
            allowed_types=audio_provider.VOICE_AUDIO_TYPES,
            normalize_type=audio_provider.normalized_audio_type,
            max_bytes=MAX_AUDIO_BODY_BYTES,
            error=AppError,
        )

    def read_json(self, max_bytes: int = MAX_BODY_BYTES) -> dict[str, Any]:
        return read_request_json(
            self.headers,
            self.rfile.read,
            max_bytes,
            error=AppError,
            too_large_status_threshold=MAX_BODY_BYTES,
        )

    def send_json(self, status: int, payload: Any, headers: dict[str, str | list[str]] | None = None) -> None:
        HTTP_RESPONSE_TRANSPORT.send_json(self, status, payload, headers)

    def send_file_stream(
        self,
        path: Path,
        content_type: str,
        filename: str,
        *,
        deadline: float | None = None,
        cleanup: bool = False,
    ) -> None:
        HTTP_RESPONSE_TRANSPORT.send_file_stream(
            self,
            path,
            content_type,
            filename,
            deadline=deadline,
            cleanup=cleanup,
        )

    def send_bytes(self, status: int, data: bytes, content_type: str, headers: dict[str, str | list[str]] | None = None) -> None:
        HTTP_RESPONSE_TRANSPORT.send_bytes(self, status, data, content_type, headers)

    def send_static(self, path: str) -> None:
        HTTP_RESPONSE_TRANSPORT.send_static(self, path)


def request_handler_class() -> type[RequestHandler]:
    static_assets = StaticAssetService(PUBLIC_DIR)

    class ComposedRequestHandler(RequestHandler):
        static_asset_service = static_assets

    return ComposedRequestHandler


def daily_sync_loop_service() -> DailySyncLoop:
    return DailySyncLoop(
        daily_sync_scheduler(),
        morning_body_battery_service(),
        sleep=time.sleep,
        logger=LOGGER,
        stop_event=threading.Event(),
    )


def daily_sync_scheduler() -> DailySyncScheduler:
    return DailySyncScheduler(
        profile_service(),
        sync_job_queue_service(),
        daily_sync_marker_service(),
        garmin_sync_service(),
        database_manager(),
        KEY_VALUE_REPOSITORY,
        DB_LOCK,
        sync_state_repository(),
        INTERVALS_RESYNC_GATE,
        runtime_maintenance.MAINTENANCE_GATE,
        config=DailySyncSchedulerConfig(
            calendar_url_enabled=bool(CONFIG.calendar_ical_url),
            intervals_key_enabled=bool(CONFIG.intervals_api_key),
            garmin_automatic_sync_days=GARMIN_AUTOMATIC_SYNC_DAYS,
            auto_update_label=AUTO_UPDATE_LABEL,
            sync_period_defaults=SYNC_PERIOD_DEFAULTS,
            all_sync_days=ALL_SYNC_DAYS,
        ),
    )


def startup_sync_scheduler() -> StartupSyncScheduler:
    return StartupSyncScheduler(
        profile_service(),
        sync_job_queue_service(),
        garmin_sync_service(),
        sync_state_repository(),
        config=StartupSyncSchedulerConfig(
            calendar_enabled=bool(CONFIG.calendar_ical_url),
            intervals_enabled=bool(CONFIG.intervals_api_key),
            garmin_automatic_sync_days=GARMIN_AUTOMATIC_SYNC_DAYS,
            sync_period_defaults=SYNC_PERIOD_DEFAULTS,
            all_sync_days=ALL_SYNC_DAYS,
            sync_chunk_days=SYNC_CHUNK_DAYS,
            sync_earliest_date=SYNC_EARLIEST_DATE,
        ),
    )


def main() -> None:
    observability.configure_logging(LOGGER, DATA_DIR, LOG_PATH, REDACTOR)
    configuration_error = app_config.security_configuration_error(CONFIG, sqlcipher_available=SQLCIPHER_AVAILABLE)
    if configuration_error:
        LOGGER.critical("Secure startup refused", extra={"event": "secure_startup_refused", "context": {"reason": configuration_error}})
        raise SystemExit(configuration_error)
    LOGGER.info(f"{APP_NAME} starting", extra={"event": "server_start", "context": {"version": APP_VERSION, "port": CONFIG.port}})
    initialise_database()
    server = http_server.CoachHTTPServer(("0.0.0.0", CONFIG.port), request_handler_class())
    server.allow_reuse_address = True
    sync_worker: SyncJobWorker | None = None
    daily_loop: DailySyncLoop | None = None
    daily_thread: threading.Thread | None = None
    try:
        sync_job_queue_service().resume_interrupted()
        coach_job_store().resume_interrupted(coach_turn_failure_service())
        sync_worker = sync_job_worker()
        sync_worker.start()
        COACH_JOB_WORKER.start(coach_job_store, coach_background_job_runner, runtime_maintenance.MAINTENANCE_GATE)
        startup_sync_scheduler().schedule()
        daily_loop = daily_sync_loop_service()
        daily_thread = threading.Thread(target=daily_loop.run, daemon=True)
        daily_thread.start()
        LOGGER.info(f"{APP_NAME} listening", extra={"event": "server_ready", "context": {"port": CONFIG.port}})
        server.serve_forever()  # NOSONAR - HTTP is intentionally LAN-only behind the documented HTTPS proxy.
    except KeyboardInterrupt:
        pass
    finally:
        if daily_loop is not None:
            daily_loop.stop()
        if sync_worker is not None:
            sync_worker.stop()
        COACH_JOB_WORKER.stop()
        server.server_close()
        if daily_thread is not None:
            daily_thread.join(timeout=5)
        if sync_worker is not None:
            sync_worker.join(timeout=5)
        COACH_JOB_WORKER.join(timeout=5)


if __name__ == "__main__":
    main()
