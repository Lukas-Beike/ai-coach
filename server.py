from __future__ import annotations
from backend.coach import attachments as coach_attachments
from backend.coach.profile_update import CoachProfileUpdateService
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
    public_app_error_status,
)
from backend import config as app_config
from backend import observability
from backend.calendar import local as calendar_local
from backend.privacy import PrivacyAssembly
from backend.athlete.checkins import (
    CHECKIN_SCORE_FIELDS,
    CHECKIN_TEXT_LIMITS,
)
from backend.athlete.context import AthleteContextService
from backend.athlete.clock import AthleteLocalClock
from backend.athlete.assembly import AthleteDataAssembly
from backend.athlete.profile import DEFAULT_PROFILE, normalize_profile, timezone_name
from backend.performance import morning_battery as performance_morning_battery
from backend.performance.morning_battery_service import (
    MorningBatteryClock,
    MorningBatteryEvents,
    MorningBatteryExecutionGate,
    MorningBatteryRetryPolicy,
    MorningBatterySource,
    MorningBatteryStore,
    MorningBodyBatteryService,
    MORNING_BODY_BATTERY_SERVICE_CACHE,
)
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance
from backend.runtime import clock as runtime_clock
from backend.sync.assembly import ProviderSyncAssembly
from backend.sync.queue_assembly import SyncJobQueueAssembly
from backend.sync.execution_assembly import SyncJobExecutionAssembly
from backend.sync.worker_assembly import SyncJobWorkerAssembly
from backend.sync.scheduler_assembly import SyncSchedulerAssembly
from backend.sync.intervals_assembly import IntervalsSyncAssembly
from backend.sync.external_calendar_assembly import ExternalCalendarAssembly
from backend.sync.provider_resync_assembly import ProviderResyncAssembly
from backend.sync import external_calendar as external_calendar_runtime
from backend.sync.persistence_assembly import SyncPersistenceAssembly
from backend.sync.garmin_assembly import GarminAssembly
from backend.sync.gates import (
    GARMIN_RESYNC_GATE,
    INTERVALS_RESYNC_GATE,
)
from backend.sync import intervals_state
from backend.sync import observation as sync_observation
from backend.sync.intervals_lock import INTERVALS_SYNC_LOCK
from backend.weather.assembly import WeatherAssembly
from backend.settings import SettingsService
from backend.db.bootstrap import initialize_application_database
from backend.db.key_value import KeyValueService
from backend.db.repositories import ActivityFeedbackRepository, ChatRepository, CheckinRepository, CompetitionRepository, KeyValueRepository, NutritionRepository, PlanAdjustmentRepository, PlanningStateRepository, ProfileRepository, SnapshotRepository, TrainingPlanRepository
from backend.db import manager as database_manager_runtime
from backend.db.manager import (
    DATABASE_LOCK as DB_LOCK,
    DatabaseManager,
)
from backend.db.schema import configure_cipher, database_schema_is_current
from backend.config import Config, DEFAULT_OPENAI_BASE_URL, load_config
from backend.providers.intervals import IntervalsApiClient
from backend.providers import audio as audio_provider
from backend.providers import calendar as calendar_provider
from backend.providers import http as provider_http
from backend.providers import state as provider_state
from backend.providers import weather as weather_provider
from backend.providers.transport_assembly import ProviderTransportAssembly
from backend.providers.model_assembly import ModelTransportAssembly
from backend.http_api import server as http_server
from backend.http_api.handler import HttpRequestHandlerDependencies, create_request_handler
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
from backend.http_api.public_get import PublicGetRoutes
from backend.http_api.planning_get import PlanningGetRoutes
from backend.http_api.readiness import ReadinessService
from backend.http_api.auth import (
    SessionAuthService,
    get_session_auth_service,
)
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
from backend.sync.status import SyncPublicStateService
from backend.sync.authority import PlanningAuthorityService
from backend.sync.adaptive import AdaptivePreviewFollowupService, IllnessPauseSyncService
from backend.sync.commands import ProviderRefreshCommandService
from backend.sync.conflict_commands import SyncConflictCommandService
from backend.sync.plan_commands import PlanPushCommandService
from backend.sync.plan_selection import StructuredPlanSyncService
from backend.sync.plan_repair import PlanRepairManifestService
from backend.sync.planned_calendar_assembly import PlannedCalendarSyncAssembly
from backend.sync.planned_unit_assembly import PlannedUnitSyncAssembly
from backend.sync.library import workout_library_sync_running
from backend.sync.library_assembly import WorkoutLibrarySyncAssembly
from backend.sync.selected_assembly import SelectedWorkoutSyncAssembly
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminMorningRemoteReader,
    shared_garmin_sync_lock,
)
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
from backend.sync import worker as sync_worker_runtime
from backend.sync.worker import shared_sync_job_wake_event
from backend.planning import adaptive as planning_adaptive
from backend.planning.assembly import PlanningDataAssembly
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.calendar_service import CalendarConflictService
from backend.planning import changes as planning_changes
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.planning import competitions as planning_competitions
from backend.planning import library as planning_library
from backend.planning.library_plan_service import WorkoutLibraryPlanService
from backend.planning.local_plan_creation_service import LocalTrainingPlanCreationService
from backend.planning.replacement_service import StructuredTrainingPlanReplacementService
from backend.planning.revision import PlanningRevisionService
from backend.planning import season as planning_season
from backend.planning.state_service import StructuredTrainingStateService
from backend.planning import training_plans as planning_training_plans
from backend.http_api.bootstrap_calendar import PublicStateCalendarProjection
from backend.http_api.public_state import PublicStateDependencies, PublicStateService
from backend.sync import scheduler as sync_scheduler_runtime
from backend.coach.athlete_record_tools import CoachAthleteRecordToolService
from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.plan_artifact_tools import CoachPlanArtifactToolService
from backend.coach.tool_replay import CoachStructuredToolReplayService
from backend.coach.tool_preparation import CoachStructuredToolPreparationService
from backend.coach.planning_change_tools import CoachPlanningChangeToolService
from backend.coach.tool_dispatch import CoachToolDispatchService
from backend.coach import context as coach_context_module
from backend.coach.context import CoachQuickActionsService
from backend.coach.context_assembly import CoachContextAssembly
from backend.coach.read_tools_assembly import CoachReadToolsAssembly
from backend.coach.request_payload import CoachRequestPayloadService
from backend.coach.sync_tools import CoachSyncToolService
from backend.coach.conversation import (
    CoachAttachmentContextService,
    GeminiConversationResponseService,
    GeminiRequestPayloadService,
    GeminiResponseNormalizationService,
)
from backend.coach.conversation_assembly import CoachConversationAssembly
from backend.coach.conversation_gate import CoachConversationGate
from backend.coach.proposal_assembly import CoachProposalAssembly
from backend.coach.planning_tools_assembly import CoachPlanningToolsAssembly
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.turn_opening import CoachTurnOpeningService
from backend.coach.dialogue import CoachDialogueReadService, dialogue_tools
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.coach.clarification import CoachClarificationService
from backend.coach.turn_outcome import CoachStructuredOutcomeService
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
from backend.backup.assembly import BackupAssembly

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
PROVIDER_INTERVALS_WELLNESS_NAME = "Intervals.icu Wellness"
JSON_MEDIA_TYPE = "application/json"
OPENAI_RESPONSES_PATH = "/responses"
PLANNED_WORKOUT_LABEL = "Geplante Einheit"
APP_NAME = "Intervals Coach"
SELECT_PLANNED_PAYLOAD_SQL = "SELECT payload FROM planned_units WHERE local_id=?"
APP_VERSION = "1.11.14"
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
COACH_CONVERSATION_GATE = CoachConversationGate()
SYNC_JOB_WORKER: sync_worker_runtime.SyncJobWorker | None = None


CONFIG = load_config(ROOT, DATA_DIR)


LOGGER = logging.getLogger("intervals_coach")
REDACTOR = observability.Redactor(lambda: CONFIG)


KEY_VALUE_REPOSITORY = KeyValueRepository(runtime_clock.utc_now)
PROFILE_REPOSITORY = ProfileRepository(KEY_VALUE_REPOSITORY)
COMPETITION_REPOSITORY = CompetitionRepository()
TRAINING_PLAN_REPOSITORY = TrainingPlanRepository()
PLANNING_STATE_REPOSITORY = PlanningStateRepository()
PLANNING_REVISION_SERVICE = PlanningRevisionService(
    PLANNING_STATE_REPOSITORY, runtime_clock.utc_now
)
PLAN_ADJUSTMENT_REPOSITORY = PlanAdjustmentRepository()
CHAT_REPOSITORY = ChatRepository(runtime_clock.utc_now)
CHECKIN_REPOSITORY = CheckinRepository(runtime_clock.utc_now)
ACTIVITY_FEEDBACK_REPOSITORY = ActivityFeedbackRepository(runtime_clock.utc_now)
SNAPSHOT_REPOSITORY = SnapshotRepository()


PROVIDER_REFRESH_RETRY_BASE_SECONDS = 15 * 60
PROVIDER_REFRESH_RETRY_MAX_SECONDS = 6 * 60 * 60
SYNC_JOB_RETRY_BASE_SECONDS = 15 * 60
SYNC_JOB_RETRY_MAX_SECONDS = 6 * 60 * 60
SYNC_JOB_POLL_SECONDS = 1.0
GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS = 120


def database_manager() -> DatabaseManager:
    """Return the manager for the active path and secure configuration."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signature = (str(DB_PATH.resolve()), CONFIG.app_password, SQLCIPHER_AVAILABLE)
    if CONFIG.app_password and not SQLCIPHER_AVAILABLE:
        database_manager_runtime.DATABASE_MANAGER_CACHE.reset()
        raise RuntimeError("SQLCipher ist fÃ¼r eine verschlÃ¼sselte Datenbank erforderlich.")
    return database_manager_runtime.DATABASE_MANAGER_CACHE.get(
        signature,
        DB_PATH,
        sqlite_backend if CONFIG.app_password else sqlite3,
        password=CONFIG.app_password,
        configure=configure_cipher,
        row_factory=database_row_factory,
        reader_count=4,
        timeout=20,
        persist_connections=bool(CONFIG.app_password),
    )


def session_auth_service() -> SessionAuthService:
    """Compose the HTTP session owner from the active persistence and security configuration."""
    return get_session_auth_service(
        database_manager(), DB_LOCK, CONFIG, SQLCIPHER_AVAILABLE
    )


def provider_state_service() -> provider_state.ProviderStateService:
    """Return provider observability state bound to the active database manager."""
    return provider_state.get_provider_state_service(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        DB_LOCK,
        runtime_clock.utc_now,
        lambda: ATHLETE_CLOCK.now().date(),
        LOGGER,
    )


PROVIDER_SYNC = ProviderSyncAssembly(
    database_manager=database_manager,
    config=lambda: CONFIG,
    key_values=KEY_VALUE_REPOSITORY,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
    logger=LOGGER,
    now=lambda: datetime.now(timezone.utc),
    uuid_factory=lambda: uuid.uuid4().hex,
    retry_base_seconds=PROVIDER_REFRESH_RETRY_BASE_SECONDS,
    retry_max_seconds=PROVIDER_REFRESH_RETRY_MAX_SECONDS,
)


def sync_command_endpoint() -> SyncCommandEndpoint:
    """Compose authenticated manual synchronization POST commands."""
    return SyncCommandEndpoint(
        SYNC_JOB_QUEUE.service(), SYNC_PERSISTENCE.state_repository(),
        INTERVALS_SYNC.performance_service(), PROVIDER_RESYNC.full_resync_service(),
        lambda: uuid.uuid4().hex, SYNC_PERIOD_DEFAULTS, ALL_SYNC_DAYS,
    )


def provider_refresh_command_service() -> ProviderRefreshCommandService:
    """Compose authorized Coach refresh command execution."""
    return ProviderRefreshCommandService(
        SYNC_JOB_QUEUE.service(), INTERVALS_SYNC.sync_service(), ALL_SYNC_DAYS
    )


def sync_conflict_command_service() -> SyncConflictCommandService:
    """Compose local conflict decisions and explicitly authorized job retry."""
    return SyncConflictCommandService(
        database_manager(),
        PLANNING_DATA.planned_unit(),
        PLANNING_DATA.competition(),
        SYNC_JOB_QUEUE.service(),
    )


def plan_push_command_service() -> PlanPushCommandService:
    """Compose explicit Coach plan-push chunking and queue persistence."""
    return PlanPushCommandService(SYNC_JOB_QUEUE.service())


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
        SYNC_JOB_QUEUE.service(), planning_authority_service(),
        sync_conflict_command_service(), structured_plan_sync_service(),
        plan_repair_manifest_service(), plan_push_command_service(),
        provider_refresh_command_service(),
        duplicate_activity=duplicate_activity_service(),
        intervals_client_factory=intervals_client,
    )


def nutrition_service() -> NutritionService:
    """Compose nutrition and calorie tracking for the active database manager."""
    return NutritionService(
        database_manager=database_manager(),
        db_lock=DB_LOCK,
        nutrition_repository=NutritionRepository(runtime_clock.utc_now),
        utc_now=runtime_clock.utc_now,
        local_now=ATHLETE_CLOCK.now,
    )


def intervals_nutrition_sync_service() -> IntervalsNutritionSyncService:
    """Compose nutrition sync to Intervals.icu wellness."""
    api_client = IntervalsApiClient(
        api_key=CONFIG.intervals_api_key,
        request=PROVIDER_TRANSPORT.json_http_client().request,
    )
    return IntervalsNutritionSyncService(
        config=CONFIG,
        api_client=api_client,
        nutrition_service=nutrition_service(),
    )


def coach_athlete_record_tool_service() -> CoachAthleteRecordToolService:
    """Compose concrete local services for Coach athlete-record mutations."""
    return CoachAthleteRecordToolService(
        ATHLETE_DATA.checkin(),
        ATHLETE_DATA.activity_feedback(),
        PLANNING_DATA.competition(),
        nutrition_service(),
    )


def state_version_service() -> StateVersionService:
    """Compose the read-only browser version projection."""
    return StateVersionService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        SNAPSHOT_REPOSITORY,
        ATHLETE_DATA.profile(),
    )


def public_performance_state_service() -> PublicPerformanceStateService:
    """Compose the read-only performance projection."""
    return PublicPerformanceStateService(
        SYNC_PERSISTENCE.state_repository(),
        GARMIN_ASSEMBLY.payload_service(),
        ATHLETE_DATA.profile(),
        GARMIN_ASSEMBLY.projection_service(),
        lambda: ATHLETE_CLOCK.now().date(),
    )


def public_feedback_state_service() -> PublicFeedbackStateService:
    """Compose the read-only feedback projection."""
    return PublicFeedbackStateService(ATHLETE_DATA.checkin(), ATHLETE_DATA.activity_feedback())


def sync_public_state_service() -> SyncPublicStateService:
    """Compose the public sync-status projection."""
    return SyncPublicStateService(
        CONFIG,
        database_manager(),
        KEY_VALUE_REPOSITORY,
        PROVIDER_SYNC.freshness_service(),
        ATHLETE_DATA.profile(),
        GARMIN_ASSEMBLY.sync_state_service(),
        runtime_maintenance.MAINTENANCE_GATE,
        SYNC_JOB_QUEUE.service(),
        state_version_service(),
        INTERVALS_SYNC_LOCK,
    )


def public_weather_state_service() -> PublicWeatherStateService:
    """Compose the public weather endpoint projection."""
    return PublicWeatherStateService(WEATHER_ASSEMBLY.service())


def morning_body_battery_service() -> MorningBodyBatteryService:
    """Compose morning recovery orchestration from concrete runtime resources."""
    manager = database_manager()
    config_id = id(CONFIG)
    return MORNING_BODY_BATTERY_SERVICE_CACHE.get(
        manager,
        config_id,
        MorningBatteryStore(manager, KEY_VALUE_REPOSITORY),
        MorningBatterySource(
            GARMIN_ASSEMBLY.fixture_loader(),
            GarminMorningRemoteReader(
                CONFIG,
                GARMIN_ASSEMBLY.client_factory(),
                ATHLETE_DATA.profile(),
                ATHLETE_CLOCK,
                DIAGNOSTIC_CAPTURE,
                LOGGER,
            ),
            observability.safe_diagnostic_error,
        ),
        MorningBatteryExecutionGate(
            shared_garmin_sync_lock(),
            runtime_maintenance.MAINTENANCE_GATE,
            GARMIN_RESYNC_GATE,
            GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS,
        ),
        MorningBatteryClock(lambda: datetime.now(timezone.utc), ATHLETE_CLOCK.now),
        MorningBatteryEvents(runtime_events.STATE_EVENT_BUFFER.publish, LOGGER),
        MorningBatteryRetryPolicy(),
    )


def calendar_conflict_service() -> CalendarConflictService:
    """Compose local and external planning-conflict reads."""
    return CalendarConflictService(database_manager(), EXTERNAL_CALENDAR.reader())


ATHLETE_DATA = AthleteDataAssembly(
    database_manager=database_manager,
    activity_feedback_repository=ACTIVITY_FEEDBACK_REPOSITORY,
    checkin_repository=CHECKIN_REPOSITORY,
    profile_repository=PROFILE_REPOSITORY,
    key_value_repository=KEY_VALUE_REPOSITORY,
    snapshot_repository=SNAPSHOT_REPOSITORY,
    utc_now=runtime_clock.utc_now,
    local_date=lambda: ATHLETE_CLOCK.now().date(),
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
)
ATHLETE_PROFILE_SERVICE = ATHLETE_DATA.profile_for(
    database_manager_runtime.DATABASE_MANAGER_CACHE
)
ATHLETE_CLOCK = AthleteLocalClock(ATHLETE_PROFILE_SERVICE)

PLANNING_DATA = PlanningDataAssembly(
    database_manager=database_manager,
    competition_repository=COMPETITION_REPOSITORY,
    training_plan_repository=TRAINING_PLAN_REPOSITORY,
    key_value_repository=KEY_VALUE_REPOSITORY,
    planning_revision_service=PLANNING_REVISION_SERVICE,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    utc_now=runtime_clock.utc_now,
    local_date=lambda: ATHLETE_CLOCK.now().date(),
    uuid_factory=uuid.uuid4,
    redact=REDACTOR.redact_text,
    calendar_conflict_service=lambda: calendar_conflict_service(),
    publish_change=lambda: runtime_events.STATE_EVENT_BUFFER.publish(
        "coach", {"status": "changed"}
    ),
    plan_adjustment_repository=PLAN_ADJUSTMENT_REPOSITORY,
)
PRIVACY_ASSEMBLY = PrivacyAssembly(
    database_manager=database_manager,
    database_lock=lambda: DB_LOCK,
    key_value_repository=KEY_VALUE_REPOSITORY,
    profile_service=ATHLETE_DATA.profile,
    workout_library_service=PLANNING_DATA.workout_library,
    competition_service=PLANNING_DATA.competition,
    training_plan_service=PLANNING_DATA.training_plan,
    checkin_service=ATHLETE_DATA.checkin,
    activity_feedback_service=ATHLETE_DATA.activity_feedback,
    adaptive_preview_service=lambda: adaptive_replan_preview_service(),
    external_calendar_reader=lambda: EXTERNAL_CALENDAR.reader(),
    local_now=lambda: ATHLETE_CLOCK.now(),
    utc_now=runtime_clock.utc_now,
    maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
    planning_revision_service=PLANNING_REVISION_SERVICE,
    openai_client=lambda: MODEL_TRANSPORT.openai_responses_client(),
    logger=LOGGER,
    data_dir=lambda: DATA_DIR,
    database_path=lambda: DB_PATH,
    maximum_export_bytes=MAX_PRIVACY_EXPORT_BYTES,
    minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
    time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
)
BACKUP_ASSEMBLY = BackupAssembly(
    database_manager=database_manager,
    database_path=lambda: DB_PATH,
    data_dir=lambda: DATA_DIR,
    database_lock=lambda: DB_LOCK,
    maximum_bytes=MAX_BACKUP_BYTES,
    minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
    time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
    logger=LOGGER,
    app_password=lambda: CONFIG.app_password,
    sqlcipher_available=lambda: SQLCIPHER_AVAILABLE,
    sqlite_backend=sqlite_backend,
    configure_cipher=configure_cipher,
    row_factory=database_row_factory,
    schema_is_current=database_schema_is_current,
    maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
    sync_jobs=lambda: SYNC_JOB_QUEUE.service(),
    coach_jobs=lambda: coach_job_store(),
    coach_failures=lambda: coach_turn_failure_service(),
    sync_wake_event=shared_sync_job_wake_event,
    coach_wake_event=COACH_JOB_WORKER.wake_event,
    redact=REDACTOR.redact_text,
)


def coach_profile_update_service() -> CoachProfileUpdateService:
    """Compose the scoped transactional Coach profile update owner."""
    return CoachProfileUpdateService(ATHLETE_DATA.profile(), database_manager(), DB_LOCK)


def change_history_service() -> ChangeHistoryService:
    """Compose local change-history reads for the active database manager."""
    return ChangeHistoryService(database_manager(), PROFILE_REPOSITORY)


def history_undo_service() -> HistoryUndoService:
    """Compose transactional local history undo orchestration."""
    return HistoryUndoService(
        database_manager(),
        change_history_service(),
        ATHLETE_DATA.profile(),
        PLANNING_DATA.workout_library(),
        PLANNING_DATA.competition(),
        PLANNING_DATA.planned_unit(),
        PLANNING_DATA.training_plan(),
        PLANNING_REVISION_SERVICE,
    )


def planning_authority_service() -> PlanningAuthorityService:
    """Compose explicit local-authority decisions before provider sync."""
    return PlanningAuthorityService(
        database_manager(),
        WORKOUT_LIBRARY_SYNC.sync_state_service(),
        PLANNING_REVISION_SERVICE,
        runtime_clock.utc_now,
    )


def sync_job_worker() -> sync_worker_runtime.SyncJobWorker:
    """Return the one restartable persistent synchronization worker."""
    global SYNC_JOB_WORKER
    if SYNC_JOB_WORKER is None:
        SYNC_JOB_WORKER = SYNC_JOB_WORKER_ASSEMBLY.create()
    return SYNC_JOB_WORKER


def workout_library_plan_service() -> WorkoutLibraryPlanService:
    """Compose atomic local planning from saved workout templates."""
    return WorkoutLibraryPlanService(
        database_manager(),
        PLANNING_DATA.planned_unit(),
        calendar_conflict_service(),
        lambda: runtime_events.STATE_EVENT_BUFFER.publish(
            "coach", {"status": "changed"}
        ),
    )


def local_plan_creation_service() -> LocalTrainingPlanCreationService:
    """Compose atomic local plan creation and template reuse."""
    return LocalTrainingPlanCreationService(
        database_manager(),
        TRAINING_PLAN_REPOSITORY,
        PLANNING_DATA.planned_unit(),
        PLANNING_DATA.workout_library(),
        calendar_conflict_service(),
        PLANNING_REVISION_SERVICE,
        lambda: ATHLETE_CLOCK.now().date(),
        runtime_clock.utc_now,
        uuid.uuid4,
        LOGGER,
    )


def daily_planning_context_service() -> DailyPlanningContextService:
    """Compose the date-specific planning read model."""
    return DailyPlanningContextService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        ATHLETE_DATA.checkin(),
        EXTERNAL_CALENDAR.reader(),
        morning_body_battery_service(),
        ATHLETE_DATA.activity_feedback(),
        lambda: ATHLETE_CLOCK.now().date(),
        calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
    )


def structured_training_state_service() -> StructuredTrainingStateService:
    """Compose read-only structured planning-state projection."""
    return StructuredTrainingStateService(
        database_manager(),
        PLANNING_STATE_REPOSITORY,
        PLANNING_DATA.competition(),
        PLANNING_DATA.training_plan(),
        coach_dialogue_read_service().artifact_refs,
        SYNC_JOB_QUEUE.service().list,
        lambda: ATHLETE_CLOCK.now().date(),
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
        PLANNING_DATA.planned_unit(),
        PLANNING_REVISION_SERVICE,
        PLANNING_DATA.training_plan(),
        lambda: ATHLETE_CLOCK.now().date(),
        coach_limits.COACH_TRAINING_CHANGE_LIMIT,
        lambda: runtime_events.STATE_EVENT_BUFFER.publish(
            "planning", {"status": "changed"}
        ),
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
        PLANNING_DATA.planned_unit(),
        lambda: ATHLETE_CLOCK.now().date(),
        runtime_clock.utc_now,
        uuid.uuid4,
    )


def illness_pause_sync_service() -> IllnessPauseSyncService:
    """Compose the explicitly approved illness-pause remote sync use case."""
    return IllnessPauseSyncService(
        CONFIG,
        PROVIDER_TRANSPORT.intervals_client(),
        adaptive_replan_apply_service=PLANNING_DATA.adaptive_apply(),
        competition_service=PLANNING_DATA.competition(),
        adaptive_replan_preview_service=adaptive_replan_preview_service(),
        redactor=REDACTOR,
        today=lambda: ATHLETE_CLOCK.now().date(),
    )


def adaptive_preview_followup_service() -> AdaptivePreviewFollowupService:
    """Compose the local preview check after a provider refresh."""
    return AdaptivePreviewFollowupService(adaptive_replan_preview_service(), LOGGER)


def adaptive_replan_preview_service() -> AdaptiveReplanPreviewService:
    """Compose adaptive preview creation and read state."""
    return AdaptiveReplanPreviewService(
        database_manager(),
        PLAN_ADJUSTMENT_REPOSITORY,
        ATHLETE_DATA.checkin(),
        PLANNING_DATA.planned_unit(),
        EXTERNAL_CALENDAR.reader(),
        WEATHER_ASSEMBLY.service(),
        lambda: ATHLETE_CLOCK.now().date(),
        runtime_clock.utc_now,
        uuid.uuid4,
        calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        CHECKIN_TEXT_LIMITS["illness"],
        planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS,
        planning_adaptive.WEATHER_ADAPTIVE_MAX_MINUTES,
    )






def athlete_context_service() -> AthleteContextService:
    """Compose atomic athlete profile and competition persistence."""
    return AthleteContextService(
        database_manager(),
        ATHLETE_DATA.profile(),
        COMPETITION_REPOSITORY,
        normalize_profile,
        planning_competitions.normalize_competition,
        runtime_clock.utc_now,
        uuid.uuid4,
    )


def initialise_database() -> None:
    with DB_LOCK, database_manager().unit_of_work() as db:
        initialize_application_database(
            db,
            key_values=KEY_VALUE_REPOSITORY,
            now=runtime_clock.utc_now(),
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
    runtime_clock.utc_now,
)

SYNC_PERSISTENCE = SyncPersistenceAssembly(
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    snapshots=SNAPSHOT_REPOSITORY,
    utc_now=runtime_clock.utc_now,
    athlete_clock=lambda: ATHLETE_CLOCK,
)


GARMIN_ASSEMBLY = GarminAssembly(
    config=lambda: CONFIG,
    root=ROOT,
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    sync_state_repository=SYNC_PERSISTENCE.state_repository,
    daily_sync_marker_service=SYNC_PERSISTENCE.daily_markers,
    redactor=REDACTOR,
    logger=LOGGER,
    diagnostic_capture=DIAGNOSTIC_CAPTURE,
    athlete_clock=ATHLETE_CLOCK,
    utc_now=runtime_clock.utc_now,
    datetime_now=lambda: datetime.now(timezone.utc),
    earliest_date=SYNC_EARLIEST_DATE,
    sync_chunk_days=SYNC_CHUNK_DAYS,
    all_sync_days=ALL_SYNC_DAYS,
    resync_gate=GARMIN_RESYNC_GATE,
    operation_observer=PROVIDER_SYNC.operation_observer,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    lock_wait_seconds=GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS,
    morning_body_battery_service=morning_body_battery_service,
)

SYNC_JOB_QUEUE = SyncJobQueueAssembly(
    database_manager=database_manager,
    now=runtime_clock.utc_now,
    current_time=lambda: datetime.now(timezone.utc),
    uuid_factory=lambda: uuid.uuid4().hex,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
    wake_event=shared_sync_job_wake_event,
    all_sync_days=ALL_SYNC_DAYS,
    daily_sync_marker_service=SYNC_PERSISTENCE.daily_markers,
    redact_text=REDACTOR.redact_text,
    logger=LOGGER,
    retry_base_seconds=SYNC_JOB_RETRY_BASE_SECONDS,
    retry_max_seconds=SYNC_JOB_RETRY_MAX_SECONDS,
)

EXTERNAL_CALENDAR = ExternalCalendarAssembly(
    config=lambda: CONFIG,
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    daily_markers=SYNC_PERSISTENCE.daily_markers,
    operation_observer=PROVIDER_SYNC.operation_observer,
    adaptive_preview_service=lambda: adaptive_replan_preview_service(),
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    logger=LOGGER,
    redact_text=REDACTOR.redact_text,
    athlete_clock=lambda: ATHLETE_CLOCK,
    local_date=lambda: ATHLETE_CLOCK.now().date(),
    utc_now=runtime_clock.utc_now,
    app_version=APP_VERSION,
    sync_lock=lambda: external_calendar_runtime.shared_external_calendar_sync_lock(),
)


INTERVALS_SYNC = IntervalsSyncAssembly(
    config=lambda: CONFIG,
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    state_repository=SYNC_PERSISTENCE.state_repository,
    daily_markers=SYNC_PERSISTENCE.daily_markers,
    request=lambda: PROVIDER_TRANSPORT.json_http_client().request,
    athlete_clock=lambda: ATHLETE_CLOCK,
    utc_now=runtime_clock.utc_now,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    redact_text=REDACTOR.redact_text,
    logger=LOGGER,
    operation_observer=PROVIDER_SYNC.operation_observer,
    intervals_resync_gate=INTERVALS_RESYNC_GATE,
    intervals_sync_lock=INTERVALS_SYNC_LOCK,
    sync_job_queue=SYNC_JOB_QUEUE.service,
    remote_planned_unit_reconciler=lambda: PLANNED_UNIT_SYNC.remote_reconciler(),
    workout_library_refresh_service=lambda: WORKOUT_LIBRARY_SYNC.refresh_service(),
    workout_library_service=PLANNING_DATA.workout_library,
    sync_period_defaults=SYNC_PERIOD_DEFAULTS,
    all_sync_days=ALL_SYNC_DAYS,
    sync_chunk_days=SYNC_CHUNK_DAYS,
    sync_earliest_date=SYNC_EARLIEST_DATE,
    calendar_history_days=PLANNED_CALENDAR_HISTORY_DAYS,
    calendar_future_days=PLANNED_CALENDAR_FUTURE_DAYS,
    performance_wait_seconds=INTERVALS_SYNC_WAIT_SECONDS,
    poll_seconds=SYNC_JOB_POLL_SECONDS,
)


PROVIDER_TRANSPORT = ProviderTransportAssembly(
    app_version=APP_VERSION,
    max_response_bytes=provider_http.MAX_EXTERNAL_RESPONSE_BYTES,
    logger=LOGGER,
    diagnostic_capture=DIAGNOSTIC_CAPTURE,
    provider_state=lambda: provider_state.get_provider_state_service(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        DB_LOCK,
        runtime_clock.utc_now,
        lambda: ATHLETE_CLOCK.now().date(),
        LOGGER,
    ),
    redact_text=REDACTOR.redact_text,
    safe_response_headers=partial(
        observability.safe_response_headers, redact=REDACTOR.redact_text
    ),
    now=runtime_clock.utc_now,
    operation_context=sync_observation.operation_context,
    opener=lambda: provider_http.urlopen,
    config=lambda: CONFIG,
    athlete_now=ATHLETE_CLOCK.now,
)
MODEL_TRANSPORT = ModelTransportAssembly(
    config=lambda: CONFIG,
    selected_thinking_level=SETTINGS.selected_thinking_level,
    provider_http_client=PROVIDER_TRANSPORT.json_http_client,
    provider_state_service=provider_state_service,
    diagnostic_capture=DIAGNOSTIC_CAPTURE,
    logger=LOGGER,
    app_version=APP_VERSION,
    gemini_base_url=GEMINI_API_BASE_URL,
    default_openai_base_url=DEFAULT_OPENAI_BASE_URL,
    openai_responses_path=OPENAI_RESPONSES_PATH,
    json_media_type=JSON_MEDIA_TYPE,
    max_audio_bytes=MAX_AUDIO_BODY_BYTES,
    response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
    background_poll_seconds=OPENAI_BACKGROUND_POLL_SECONDS,
    background_max_seconds=OPENAI_BACKGROUND_MAX_SECONDS,
    max_response_bytes=lambda: provider_http.MAX_EXTERNAL_RESPONSE_BYTES,
    utc_now=runtime_clock.utc_now,
    monotonic=time.perf_counter,
    wall_time=time.monotonic,
    wait=time.sleep,
)
COACH_CONVERSATION = CoachConversationAssembly(
    settings=SETTINGS,
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    chat_repository=CHAT_REPOSITORY,
    state_event_buffer=runtime_events.STATE_EVENT_BUFFER,
    database_lock=DB_LOCK,
    streams=coach_streams.CHAT_STREAM_REGISTRY,
    conversation_lock=COACH_CONVERSATION_GATE.lock,
    openai_client=MODEL_TRANSPORT.openai_responses_client,
    utc_now=runtime_clock.utc_now,
    uuid_factory=uuid.uuid4,
    logger=LOGGER,
    max_gemini_inline_image_bytes=lambda: coach_attachments.MAX_GEMINI_INLINE_IMAGE_BYTES,
)
PLANNED_UNIT_SYNC = PlannedUnitSyncAssembly(
    database_manager=database_manager,
    planned_unit_service=PLANNING_DATA.planned_unit,
    planning_revision_service=PLANNING_REVISION_SERVICE,
    redactor=REDACTOR,
    utc_now=runtime_clock.utc_now,
    today=lambda: ATHLETE_CLOCK.now().date(),
)
PLANNED_CALENDAR_SYNC = PlannedCalendarSyncAssembly(
    config=lambda: CONFIG,
    database_manager=database_manager,
    intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
    state_writer=PLANNED_UNIT_SYNC.state_writer,
    utc_now=runtime_clock.utc_now,
    today=lambda: ATHLETE_CLOCK.now().date(),
    future_days=PLANNED_CALENDAR_FUTURE_DAYS,
)
WORKOUT_LIBRARY_SYNC = WorkoutLibrarySyncAssembly(
    config=lambda: CONFIG,
    database_manager=database_manager,
    intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
    workout_library_service=PLANNING_DATA.workout_library,
    key_values=KEY_VALUE_REPOSITORY,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    redactor=REDACTOR,
    utc_now=runtime_clock.utc_now,
    uuid_factory=uuid.uuid4,
)
SELECTED_WORKOUT_SYNC = SelectedWorkoutSyncAssembly(
    config=lambda: CONFIG,
    database_manager=database_manager,
    workout_library_sync_service=WORKOUT_LIBRARY_SYNC.sync_service,
    planned_calendar_sync_service=PLANNED_CALENDAR_SYNC.sync_service,
    planned_calendar_repair_service=PLANNED_CALENDAR_SYNC.repair_service,
    redactor=REDACTOR.redact_text,
    lock=INTERVALS_SYNC_LOCK,
    wait_seconds=INTERVALS_SYNC_WAIT_SECONDS,
    provider_resync_gate=INTERVALS_RESYNC_GATE,
)
WEATHER_ASSEMBLY = WeatherAssembly(
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    profile_service=ATHLETE_DATA.profile,
    client_factory=lambda: weather_provider.WeatherClient(
        PROVIDER_TRANSPORT.json_http_client().request,
        runtime_clock.utc_now,
        LOGGER,
    ),
    refresh_tracker=PROVIDER_SYNC.refresh_tracker,
    operation_context=sync_observation.OPERATION_CONTEXT,
    operation_id_factory=lambda: uuid.uuid4().hex,
    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
    now=lambda: datetime.now(timezone.utc),
    today=lambda: ATHLETE_CLOCK.now().date(),
    adaptive_preview_service=adaptive_replan_preview_service,
    observer=PROVIDER_SYNC.operation_observer,
    logger=LOGGER,
)

COACH_CONTEXT = CoachContextAssembly(
    sync_state_repository=SYNC_PERSISTENCE.state_repository,
    checkin_service=ATHLETE_DATA.checkin,
    weather_service=WEATHER_ASSEMBLY.service,
    activity_feedback_service=ATHLETE_DATA.activity_feedback,
    planned_unit_service=PLANNING_DATA.planned_unit,
    daily_context_service=daily_planning_context_service,
    external_calendar_reader=EXTERNAL_CALENDAR.reader,
    competition_service=PLANNING_DATA.competition,
    training_plan_service=PLANNING_DATA.training_plan,
    adaptive_preview_service=adaptive_replan_preview_service,
    today=lambda: ATHLETE_CLOCK.now().date(),
    profile_service=ATHLETE_DATA.profile,
    garmin_payload_service=GARMIN_ASSEMBLY.payload_service,
    garmin_projection_service=GARMIN_ASSEMBLY.projection_service,
    local_date=lambda: ATHLETE_CLOCK.now().date(),
    workout_library_service=PLANNING_DATA.workout_library,
    message_service=COACH_CONVERSATION.message_service,
    settings=SETTINGS,
    limits=lambda: {
        "local_planned_limit": coach_context_module.COACH_LOCAL_PLANNED_LIMIT,
        "library_limit": coach_context_module.COACH_LIBRARY_LIMIT,
        "library_description_limit": coach_context_module.COACH_LIBRARY_DESCRIPTION_LIMIT,
        "section_limits": coach_context_module.COACH_CONTEXT_SECTION_LIMITS,
        "total_char_limit": coach_context_module.COACH_CONTEXT_TOTAL_CHAR_LIMIT,
        "activity_limit_per_sport": coach_context_module.COACH_RECENT_ACTIVITIES_PER_SPORT,
        "planned_event_limit": coach_context_module.COACH_PLANNED_EVENT_LIMIT,
    },
    long_plan_max_output_tokens=lambda: coach_limits.COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
    utc_now=lambda: datetime.now(timezone.utc),
)
COACH_READ_TOOLS = CoachReadToolsAssembly(
    activity_read_service=ATHLETE_DATA.activity_read,
    garmin_payload_service=GARMIN_ASSEMBLY.payload_service,
    profile_service=ATHLETE_DATA.profile,
    today=lambda: ATHLETE_CLOCK.now().date(),
    structured_training_state_service=structured_training_state_service,
    workout_library_service=PLANNING_DATA.workout_library,
    planned_unit_service=PLANNING_DATA.planned_unit,
    change_history_service=change_history_service,
    competition_service=PLANNING_DATA.competition,
    training_plan_service=PLANNING_DATA.training_plan,
    nutrition_service=nutrition_service,
    training_change_limit=lambda: coach_limits.COACH_TRAINING_CHANGE_LIMIT,
)
COACH_PROPOSALS = CoachProposalAssembly(
    database_manager=database_manager,
    sync_state_repository=SYNC_PERSISTENCE.state_repository,
    duplicate_activity_service=ATHLETE_DATA.duplicate_activity,
    history_undo_service=history_undo_service,
    intervals_client_factory=PROVIDER_TRANSPORT.intervals_client,
    maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
    now=lambda: time.time(),
    utc_now=runtime_clock.utc_now,
    uuid_factory=uuid.uuid4,
)

PROVIDER_RESYNC = ProviderResyncAssembly(
    config=lambda: CONFIG,
    intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
    competition_service=PLANNING_DATA.competition,
    intervals_sync_service=INTERVALS_SYNC.sync_service,
    garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    redactor=REDACTOR,
    logger=LOGGER,
    utc_now=runtime_clock.utc_now,
    uuid_factory=lambda: uuid.uuid4().hex,
    monotonic=time.perf_counter,
    operation_observer=PROVIDER_SYNC.operation_observer,
    intervals_resync_gate=INTERVALS_RESYNC_GATE,
    garmin_resync_gate=GARMIN_RESYNC_GATE,
    all_sync_days=ALL_SYNC_DAYS,
)


SYNC_JOB_EXECUTION = SyncJobExecutionAssembly(
    sync_state_repository=SYNC_PERSISTENCE.state_repository,
    queue_service=SYNC_JOB_QUEUE.service,
    local_now=ATHLETE_CLOCK.now,
    sync_period_defaults=SYNC_PERIOD_DEFAULTS,
    all_sync_days=ALL_SYNC_DAYS,
    sync_chunk_days=SYNC_CHUNK_DAYS,
    sync_earliest_date=SYNC_EARLIEST_DATE,
    intervals_sync_service=INTERVALS_SYNC.sync_service,
    performance_refresh_service=INTERVALS_SYNC.performance_service,
    selected_workout_sync_service=SELECTED_WORKOUT_SYNC.service,
    competition_sync_service=PROVIDER_RESYNC.competition_sync_service,
    operation_observer=PROVIDER_SYNC.operation_observer,
    intervals_resync_gate=INTERVALS_RESYNC_GATE,
    garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
    morning_body_battery_service=morning_body_battery_service,
    garmin_fixture_loader=GARMIN_ASSEMBLY.fixture_loader,
    external_calendar_sync_service=EXTERNAL_CALENDAR.sync_service,
    weather_sync_service=WEATHER_ASSEMBLY.sync_service,
    outcome_service=SYNC_JOB_QUEUE.outcome_service,
)


SYNC_JOB_WORKER_ASSEMBLY = SyncJobWorkerAssembly(
    store=SYNC_JOB_QUEUE.store,
    executor=SYNC_JOB_EXECUTION.executor,
    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
    poll_seconds=SYNC_JOB_POLL_SECONDS,
    wake_event=shared_sync_job_wake_event,
)


SYNC_SCHEDULERS = SyncSchedulerAssembly(
    config=lambda: CONFIG,
    profile_service=ATHLETE_DATA.profile,
    queue_service=SYNC_JOB_QUEUE.service,
    daily_sync_marker_service=SYNC_PERSISTENCE.daily_markers,
    garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    database_lock=DB_LOCK,
    sync_state_repository=SYNC_PERSISTENCE.state_repository,
    intervals_resync_gate=INTERVALS_RESYNC_GATE,
    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
    morning_body_battery_service=morning_body_battery_service,
    sleep=time.sleep,
    logger=LOGGER,
    garmin_automatic_sync_days=GARMIN_AUTOMATIC_SYNC_DAYS,
    auto_update_label=sync_scheduler_runtime.AUTO_UPDATE_LABEL,
    sync_period_defaults=SYNC_PERIOD_DEFAULTS,
    all_sync_days=ALL_SYNC_DAYS,
    sync_chunk_days=SYNC_CHUNK_DAYS,
    sync_earliest_date=SYNC_EARLIEST_DATE,
)










def coach_quick_actions_service() -> CoachQuickActionsService:
    """Compose local quick-action reads and their public Coach projection."""
    return CoachQuickActionsService(
        database_manager(), KEY_VALUE_REPOSITORY, adaptive_replan_preview_service(),
        lambda: ATHLETE_CLOCK.now().date(), PLANNED_WORKOUT_LABEL,
    )


def coach_job_store() -> CoachJobStore:
    """Compose durable Coach background-job persistence."""
    return CoachJobStore(
        database_manager, DB_LOCK, COACH_JOB_WORKER.wake_event,
        runtime_maintenance.MAINTENANCE_GATE, runtime_clock.utc_now,
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
            utc_now=runtime_clock.utc_now,
            repository_root=ROOT,
            read_only_tools=frozenset(STRUCTURED_READ_ONLY_TOOLS),
        )
    )


def coach_job_submission_service() -> CoachJobSubmissionService:
    """Compose validation and committed side effects for background submissions."""
    return CoachJobSubmissionService(
        database_manager, CHAT_REPOSITORY, DB_LOCK, SETTINGS,
        runtime_events.STATE_EVENT_BUFFER, coach_streams.CHAT_STREAM_REGISTRY,
        COACH_JOB_WORKER.wake_event, runtime_clock.utc_now,
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
        manager, COACH_CONVERSATION.message_service(), KEY_VALUE_REPOSITORY, ATHLETE_DATA.profile()
    )


def coach_dialogue_action_service() -> CoachDialogueActionService:
    """Compose live dialogue authorization with its existing state owners."""
    manager = database_manager()
    return CoachDialogueActionService(
        manager,
        DB_LOCK,
        SYNC_JOB_QUEUE.service,
        CoachDialoguePlanScopeService(manager, DB_LOCK),
        lambda: ATHLETE_CLOCK.now().date(),
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
        GARMIN_ASSEMBLY.sync_service(), GARMIN_ASSEMBLY.payload_service(), morning_body_battery_service(),
        lambda: ATHLETE_CLOCK.now().date(), LOGGER,
    )


def morning_checkin_state_service() -> MorningCheckinStateService:
    """Compose the local morning check-in state projection."""
    return MorningCheckinStateService(
        database_manager(), KEY_VALUE_REPOSITORY, lambda: ATHLETE_CLOCK.now().date()
    )


def gemini_request_payload_service() -> GeminiRequestPayloadService:
    """Compose Gemini's bounded, persisted request-history builder."""
    return GeminiRequestPayloadService(
        COACH_CONVERSATION.gemini_history_service(), COACH_CONVERSATION.gemini_local_history_service(),
        database_manager(), KEY_VALUE_REPOSITORY,
    )


def gemini_response_normalization_service() -> GeminiResponseNormalizationService:
    """Compose Gemini response and durable function-call normalization."""
    return GeminiResponseNormalizationService(
        COACH_CONVERSATION.gemini_history_service(), database_manager(), KEY_VALUE_REPOSITORY,
        uuid.uuid4,
    )


def gemini_conversation_response_service() -> GeminiConversationResponseService:
    """Compose Gemini conversation response orchestration."""
    return GeminiConversationResponseService(
        gemini_request_payload_service(),
        gemini_response_normalization_service(),
        MODEL_TRANSPORT.gemini_json_client(),
        MODEL_TRANSPORT.gemini_stream_client(),
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
        COACH_CONVERSATION.history_service(),
        COACH_PROPOSALS.read_service(),
        maximum=CHAT_PAGE_MAX,
    )


def coach_command_receipt_service() -> CoachCommandReceiptService:
    """Compose session-bound Coach command receipt reads."""
    return CoachCommandReceiptService(
        database_manager, DB_LOCK, now=time.time,
    )


def coach_turn_opening_service() -> CoachTurnOpeningService:
    """Compose atomic creation and session binding for a new Coach turn."""
    return CoachTurnOpeningService(
        database_manager(), DB_LOCK, CHAT_REPOSITORY,
        coach_command_receipt_service(), runtime_clock.utc_now, uuid.uuid4,
    )


def coach_response_transport() -> CoachResponseTransport:
    """Compose concrete OpenAI and Gemini response adapters."""
    return CoachResponseTransport(
        SETTINGS, MODEL_TRANSPORT.openai_responses_client, MODEL_TRANSPORT.openai_stream_client,
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


COACH_PLANNING_TOOLS = CoachPlanningToolsAssembly(
    database_manager=database_manager,
    database_lock=DB_LOCK,
    local_plan_creation_service=local_plan_creation_service,
    athlete_date=lambda: ATHLETE_CLOCK.now().date(),
    utc_now=runtime_clock.utc_now,
    uuid_factory=uuid.uuid4,
    workout_library_plan_service=workout_library_plan_service,
    training_change_validator=structured_training_change_validator,
    training_change_service=structured_training_change_service,
    calendar_conflict_service=calendar_conflict_service,
    key_value_repository=KEY_VALUE_REPOSITORY,
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
    adaptive_preview_service=adaptive_replan_preview_service,
    illness_pause_sync_service=illness_pause_sync_service,
)


def coach_tool_dispatch_service() -> CoachToolDispatchService:
    """Compose the concrete Coach tool owners without retaining tool logic."""
    return CoachToolDispatchService(
        COACH_READ_TOOLS.read_service,
        coach_profile_update_service,
        coach_athlete_record_tool_service,
        CoachPlanArtifactToolService(COACH_PLANNING_TOOLS.training_plan_artifact_service),
        CoachPlanningChangeToolService(
            structured_training_plan_replacement_service,
            structured_training_change_service,
        ),
        TrainingTemplateToolService(
            database_manager, DB_LOCK, PLANNING_DATA.workout_library
        ),
        COACH_PLANNING_TOOLS.library_plan_tool_service,
        coach_sync_tool_service,
        CoachPlanningActionToolService(
            adaptive_replan_preview_service,
            COACH_PLANNING_TOOLS.adaptive_apply_service,
            PLANNING_DATA.training_plan,
            history_undo_service,
            COACH_PROPOSALS.creation_service,
        ),
    )


def coach_structured_tool_execution_service() -> CoachStructuredToolExecutionService:
    """Compose the concrete owners used for structured Coach tool execution."""
    return CoachStructuredToolExecutionService(
        database_manager(),
        DB_LOCK,
        KEY_VALUE_REPOSITORY,
        coach_clarification_service(),
        COACH_PLANNING_TOOLS.training_patch_service(),
        SYNC_PERSISTENCE.state_repository(),
        COACH_PROPOSALS.creation_service(),
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
        coach_tool_dispatch_service(), coach_turn_failure_service(), runtime_clock.utc_now,
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
        SYNC_PERSISTENCE.state_repository(),
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
        coach_structured_tool_round_journal(), coach_job_store(), COACH_CONTEXT.training_context_service(),
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
        runtime_events.STATE_EVENT_BUFFER, runtime_clock.utc_now,
    )


def coach_structured_turn_service() -> CoachStructuredTurnService:
    """Compose the complete structured turn from concrete Coach owners."""
    return CoachStructuredTurnService(CoachStructuredTurnDependencies(
        opening=coach_turn_opening_service(),
        attachments=coach_attachment_context_service(),
        dialogue=coach_dialogue_read_service(),
        payload=COACH_CONTEXT.request_payload_service(),
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
        COACH_CONVERSATION.provision_service, coach_structured_turn_service, runtime_clock.utc_now,
        COACH_CONVERSATION_GATE, runtime_maintenance.MAINTENANCE_GATE,
    )


def morning_coach_job_completion_service() -> MorningCoachJobCompletionService:
    return MorningCoachJobCompletionService(
        database_manager(), DB_LOCK, KEY_VALUE_REPOSITORY,
        coach_quick_actions_service, ATHLETE_CLOCK.now, runtime_clock.utc_now,
    )


def coach_background_job_runner() -> CoachBackgroundJobRunner:
    return CoachBackgroundJobRunner(
        coach_job_store(), coach_chat_turn_service, session_auth_service,
        coach_streams.CHAT_STREAM_REGISTRY, manual_morning_checkin_service,
        morning_coach_job_completion_service, coach_turn_failure_service,
        runtime_maintenance.MAINTENANCE_GATE, REDACTOR, LOGGER,
    )


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
            sync_state_repository=SYNC_PERSISTENCE.state_repository,
            planned_unit_service=PLANNING_DATA.planned_unit,
            competition_service=PLANNING_DATA.competition,
            external_calendar_reader=EXTERNAL_CALENDAR.reader,
            profile_service=ATHLETE_DATA.profile,
            provider_freshness_service=PROVIDER_SYNC.freshness_service,
            garmin_sync_state_service=GARMIN_ASSEMBLY.sync_state_service,
            garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
            sync_job_queue_service=SYNC_JOB_QUEUE.service,
            state_version_service=state_version_service,
            coach_message_service=COACH_CONVERSATION.message_service,
            training_plan_service=PLANNING_DATA.training_plan,
            local_calendar_events=calendar_local.local_calendar_events,
            planning_state=planning_season.planning_state,
            adaptive_replan_preview_service=adaptive_replan_preview_service,
            external_calendar_sync_service=EXTERNAL_CALENDAR.sync_service,
            external_calendar_window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
            planned_calendar_history_days=PLANNED_CALENDAR_HISTORY_DAYS,
            planned_calendar_future_days=PLANNED_CALENDAR_FUTURE_DAYS,
            garmin_projection_service=GARMIN_ASSEMBLY.projection_service,
            diagnostic_capture=DIAGNOSTIC_CAPTURE,
            intervals_public_state=intervals_state.public_state,
            intervals_sync_lock=INTERVALS_SYNC_LOCK,
            workout_library_sync_running=workout_library_sync_running,
            workout_library_sync_state_service=WORKOUT_LIBRARY_SYNC.sync_state_service,
            full_provider_resync_service=PROVIDER_RESYNC.full_resync_service,
            sync_public_state_service=sync_public_state_service,
            sync_period_defaults=SYNC_PERIOD_DEFAULTS,
            all_sync_days=ALL_SYNC_DAYS,
            settings=SETTINGS,
            local_date=lambda: ATHLETE_CLOCK.now().date(),
            morning_checkin_state_service=morning_checkin_state_service,
            coach_quick_actions_service=coach_quick_actions_service,
            provider_state_service=provider_state_service,
        )
    )


def public_plan_state_service() -> PublicPlanStateService:
    """Compose the public planning projection from its concrete read owners."""
    return PublicPlanStateService(PublicPlanDependencies(
        sync_state=SYNC_PERSISTENCE.state_repository(),
        planned_units=PLANNING_DATA.planned_unit(),
        activity_feedback=ATHLETE_DATA.activity_feedback(),
        weather=WEATHER_ASSEMBLY.service(),
        adaptive_followup=adaptive_preview_followup_service(),
        database_manager_factory=database_manager,
        db_lock=DB_LOCK,
        key_values=KEY_VALUE_REPOSITORY,
        training_plans=PLANNING_DATA.training_plan(),
        external_calendar=EXTERNAL_CALENDAR.reader(),
        external_calendar_sync=EXTERNAL_CALENDAR.sync_service(),
        daily_context=daily_planning_context_service(),
        checkins=ATHLETE_DATA.checkin(),
        competitions=PLANNING_DATA.competition(),
        adaptive_preview=adaptive_replan_preview_service(),
        coach_quick_actions=coach_quick_actions_service(),
        today=lambda: ATHLETE_CLOCK.now().date(),
        external_calendar_configured=bool(CONFIG.calendar_ical_url),
        external_calendar_window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        default_workout_name=PLANNED_WORKOUT_LABEL,
    ))


def public_state_local_prelude_service() -> PublicStateLocalPrelude:
    """Compose the local bootstrap read with its existing transaction owner."""
    return PublicStateLocalPrelude(
        SYNC_PERSISTENCE.state_repository(), ATHLETE_DATA.activity_feedback(),
        PLANNING_DATA.planned_unit(), WEATHER_ASSEMBLY.service(), database_manager(),
        DB_LOCK, lambda: ATHLETE_CLOCK.now().date(),
        CalendarWindowRange(PLANNED_CALENDAR_HISTORY_DAYS, PLANNED_CALENDAR_FUTURE_DAYS),
    )


def public_state_weather_prelude_service() -> PublicStateWeatherPrelude:
    """Compose weather refresh after the local bootstrap lock is released."""
    return PublicStateWeatherPrelude(WEATHER_ASSEMBLY.service(), adaptive_preview_followup_service())


def public_state_calendar_projection_service() -> PublicStateCalendarProjection:
    """Compose the calendar portion of the public bootstrap projection."""
    return PublicStateCalendarProjection(
        ATHLETE_DATA.checkin(),
        PLANNING_DATA.competition(),
        EXTERNAL_CALENDAR.reader(),
        EXTERNAL_CALENDAR.sync_service(),
        daily_planning_context_service(),
        external_calendar_configured=bool(CONFIG.calendar_ical_url),
        external_calendar_window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        default_workout_name=PLANNED_WORKOUT_LABEL,
        today=lambda: ATHLETE_CLOCK.now().date(),
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
                coach_messages=COACH_CONVERSATION.message_service(),
                training_plans=PLANNING_DATA.training_plan(),
                workout_library=PLANNING_DATA.workout_library(),
                profile=ATHLETE_DATA.profile(),
                public_feedback=public_feedback_state_service(),
                public_performance=public_performance_state_service(),
                sync_state=SYNC_PERSISTENCE.state_repository(),
                provider_freshness=PROVIDER_SYNC.freshness_service(),
                garmin_sync_state=GARMIN_ASSEMBLY.sync_state_service(),
                sync_public_state=sync_public_state_service(),
                intervals_sync_lock=INTERVALS_SYNC_LOCK,
                workout_library_sync_running=workout_library_sync_running,
                workout_library_sync_state=WORKOUT_LIBRARY_SYNC.sync_state_service(),
                garmin_sync=GARMIN_ASSEMBLY.sync_service(),
                provider_resync=PROVIDER_RESYNC.full_resync_service(),
                planning_preview=adaptive_replan_preview_service(),
                morning_checkin=morning_checkin_state_service(),
                coach_quick_actions=coach_quick_actions_service(),
                provider_state=provider_state_service(),
                sync_period_defaults=SYNC_PERIOD_DEFAULTS,
                all_sync_days=ALL_SYNC_DAYS,
                calendar_history_days=PLANNED_CALENDAR_HISTORY_DAYS,
                calendar_future_days=PLANNED_CALENDAR_FUTURE_DAYS,
                local_now=ATHLETE_CLOCK.now,
            )
        )


def recent_log_entries_service() -> RecentLogEntriesService:
    return RecentLogEntriesService(LOG_PATH, REDACTOR, runtime_clock.utc_now)


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
        utc_now=runtime_clock.utc_now,
        sync_state=SYNC_PERSISTENCE.state_repository(),
        garmin_projection=GARMIN_ASSEMBLY.projection_service(),
        garmin_client_factory=GARMIN_ASSEMBLY.client_factory(),
        garmin_fixture_loader=GARMIN_ASSEMBLY.fixture_loader(),
        provider_state=provider_state_service(),
        coach_history=coach_diagnostic_history_service(),
        redactor=REDACTOR,
        provider_freshness=PROVIDER_SYNC.freshness_service(),
        profile=ATHLETE_DATA.profile(),
        garmin_sync_state=GARMIN_ASSEMBLY.sync_state_service(),
        external_calendar_sync=EXTERNAL_CALENDAR.sync_service(),
        external_calendar_reader=EXTERNAL_CALENDAR.reader(),
        morning_checkin=morning_checkin_state_service(),
        workout_library_sync_state=WORKOUT_LIBRARY_SYNC.sync_state_service(),
        recent_logs=recent_log_entries_service(),
        diagnostic_capture=DIAGNOSTIC_CAPTURE,
    ))






def export_stream_transport() -> ExportStreamTransport:
    """Wire backup/export use cases into their HTTP download transport."""
    return ExportStreamTransport(
        BACKUP_ASSEMBLY.backup_service,
        PRIVACY_ASSEMBLY.archive_export_service,
        monotonic=time.monotonic,
        time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
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
    ATHLETE_DATA.profile,
    PLANNING_DATA.competition,
    public_feedback_state_service,
    COACH_CONTEXT.preview_service,
    SETTINGS,
)
DIAGNOSTICS_GET_ROUTES = DiagnosticsGetRoutes(
    session_auth_service,
    recent_log_entries_service,
    diagnostic_report_service,
)
SYNC_GET_ROUTES = SyncGetRoutes(
    session_auth_service,
    SYNC_JOB_QUEUE.service,
    sync_public_state_service,
    ATHLETE_DATA.activity_read,
    lambda: ATHLETE_CLOCK.now().date(),
    ALL_SYNC_DAYS,
)
HISTORY_GET_ROUTES = HistoryGetRoutes(session_auth_service, change_history_service)
HISTORY_UNDO_POST_ROUTES = HistoryUndoPostRoutes(
    history_undo_service,
    COACH_PROPOSALS.creation_service,
)
COACH_ACTIONS_POST_ROUTES = CoachActionsPostRoutes(
    COACH_PROPOSALS.confirmation_service,
    COACH_PROPOSALS.execution_service,
)
CHAT_POST_ROUTES = ChatPostRoutes(
    coach_job_submission_service,
    COACH_CONVERSATION.reset_service,
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
TRANSCRIBE_POST_ROUTES = TranscribePostRoutes(SETTINGS, MODEL_TRANSPORT.audio_transcription_client)
DIAGNOSTICS_CAPTURE_POST_ROUTES = DiagnosticsCapturePostRoutes(DIAGNOSTIC_CAPTURE)
PRIVACY_DELETE_POST_ROUTES = PrivacyDeletePostRoutes(PRIVACY_ASSEMBLY.delete_service)
PRIVACY_GET_ROUTES = PrivacyGetRoutes(
    session_auth_service, export_stream_transport, PRIVACY_ASSEMBLY.delete_service
)
STATE_EVENTS_GET_ROUTES = StateEventsGetRoutes(
    session_auth_service,
    StateEventTransport(runtime_events.STATE_EVENT_BUFFER),
)
SETTINGS_PUT_ROUTES = SettingsPutRoutes(SETTINGS)
ATHLETE_PUT_ROUTES = AthletePutRoutes(athlete_context_service, ATHLETE_DATA.profile)
PLANNING_COMMANDS_POST_ROUTES = PlanningCommandsPostRoutes(
    coach_planning_command_service,
    lambda: COACH_CONVERSATION.provision_service(),
)
FEEDBACK_POST_ROUTES = FeedbackPostRoutes(ATHLETE_DATA.checkin)
CHAT_CANCEL_POST_ROUTES = ChatCancelPostRoutes(coach_cancellation_service)
PRIVACY_RESTORE_POST_ROUTES = PrivacyRestorePostRoutes(
    session_auth_service, BACKUP_ASSEMBLY.restore_service, MAX_BACKUP_BYTES
)
AUTH_POST_ROUTES = AuthPostRoutes(
    session_auth_service, runtime_maintenance.MAINTENANCE_GATE
)
NUTRITION_GET_ROUTES = NutritionGetRoutes(
    session_auth_service, nutrition_service, ATHLETE_CLOCK.now
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


def request_handler_class() -> type[BaseHTTPRequestHandler]:
    return create_request_handler(
        HttpRequestHandlerDependencies(
            app_version=APP_VERSION,
            logger=LOGGER,
            session_auth_service=session_auth_service,
            route_dispatcher=HTTP_ROUTE_DISPATCHER,
            post_dispatcher=HTTP_POST_DISPATCHER,
            response_transport=HTTP_RESPONSE_TRANSPORT,
            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
            redact_text=REDACTOR.redact_text,
            public_app_error_status=public_app_error_status,
            internal_server_error=INTERNAL_SERVER_ERROR,
            max_body_bytes=MAX_BODY_BYTES,
            max_audio_body_bytes=MAX_AUDIO_BODY_BYTES,
            voice_audio_types=audio_provider.VOICE_AUDIO_TYPES,
            normalize_audio_type=audio_provider.normalized_audio_type,
            static_asset_service=StaticAssetService(PUBLIC_DIR),
        )
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
    sync_worker: sync_worker_runtime.SyncJobWorker | None = None
    daily_loop: sync_scheduler_runtime.DailySyncLoop | None = None
    daily_thread: threading.Thread | None = None
    try:
        SYNC_JOB_QUEUE.service().resume_interrupted()
        coach_job_store().resume_interrupted(coach_turn_failure_service())
        sync_worker = sync_job_worker()
        sync_worker.start()
        COACH_JOB_WORKER.start(coach_job_store, coach_background_job_runner, runtime_maintenance.MAINTENANCE_GATE)
        SYNC_SCHEDULERS.startup_scheduler().schedule()
        daily_loop = SYNC_SCHEDULERS.daily_loop()
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
