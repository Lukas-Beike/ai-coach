from __future__ import annotations
from backend.coach import attachments as coach_attachments
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

from backend.db import row_factory as database_row_factory
from backend.diagnostics.assembly import (
    DiagnosticGarminServices,
    DiagnosticLocalProjections,
    DiagnosticProviderHealth,
    DiagnosticReportSettings,
    DiagnosticRuntimeDependencies,
    DiagnosticsAssembly,
)
from backend.errors import (
    INTERNAL_SERVER_ERROR,
    AppError,
    public_app_error_status,
)
from backend import config as app_config
from backend import observability
from backend.calendar import local as calendar_local
from backend.privacy import (
    PrivacyArchiveSettings,
    PrivacyAssembly,
    PrivacyAthleteSources,
    PrivacyClock,
    PrivacyContextSources,
    PrivacyPlanningSources,
    PrivacyStateDependencies,
)
from backend.athlete.checkins import (
    CHECKIN_SCORE_FIELDS,
    CHECKIN_TEXT_LIMITS,
)
from backend.athlete.clock import AthleteLocalClock
from backend.athlete.assembly import AthleteDataAssembly, AthleteRepositories, AthleteRuntime
from backend.athlete.profile import (
    DEFAULT_PROFILE,
    normalize_profile,
)
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
from backend.sync.assembly import (
    ProviderRefreshRetryPolicy,
    ProviderSyncAssembly,
    ProviderSyncPersistence,
    ProviderSyncRuntime,
)
from backend.sync.queue_assembly import (
    SyncJobQueueAssembly,
    SyncQueuePersistence,
    SyncQueuePolicy,
    SyncQueueWorker,
)
from backend.sync.execution_assembly import (
    CalendarWeatherJobDependencies,
    GarminJobDependencies,
    HistoricalSyncDependencies,
    IntervalsJobDependencies,
    SyncJobExecutionAssembly,
    SyncJobStateDependencies,
)
from backend.sync.worker_assembly import SyncJobWorkerAssembly
from backend.sync.scheduler_assembly import (
    DailySyncLoopSettings,
    SyncScheduleControls,
    SyncScheduleOwners,
    SyncSchedulePersistence,
    SyncSchedulePolicy,
    SyncSchedulerAssembly,
)
from backend.sync.intervals_assembly import (
    IntervalsLibraryDependencies,
    IntervalsOperationDependencies,
    IntervalsPersistenceDependencies,
    IntervalsProviderDependencies,
    IntervalsSyncAssembly,
    IntervalsWaitSettings,
    IntervalsWindowSettings,
)
from backend.sync.external_calendar_assembly import (
    ExternalCalendarAssembly,
    ExternalCalendarSyncOwners,
    ExternalCalendarSyncRuntime,
)
from backend.sync.provider_resync_assembly import (
    CompetitionSyncOwners,
    ProviderResyncAssembly,
    ProviderResyncPersistence,
    ProviderResyncRuntime,
    ResyncProviderOwners,
)
from backend.sync import external_calendar as external_calendar_runtime
from backend.sync.persistence_assembly import SyncPersistenceAssembly
from backend.sync.garmin_assembly import (
    GarminAssembly,
    GarminPersistenceOwners,
    GarminProviderSettings,
    GarminSyncControl,
    GarminSyncTelemetry,
)
from backend.sync.gates import (
    GARMIN_RESYNC_GATE,
    INTERVALS_RESYNC_GATE,
)
from backend.sync import intervals_state
from backend.sync import observation as sync_observation
from backend.sync.intervals_lock import INTERVALS_SYNC_LOCK
from backend.weather.assembly import (
    WeatherAssembly,
    WeatherProviderRuntime,
    WeatherStateOwners,
    WeatherSyncRuntime,
)
from backend.settings import SettingsService
from backend.db.bootstrap import initialize_application_database
from backend.db.key_value import KeyValueService
from backend.db.repositories import ActivityFeedbackRepository, ChatRepository, CheckinRepository, CompetitionRepository, KeyValueRepository, PlanAdjustmentRepository, PlanningStateRepository, ProfileRepository, SnapshotRepository, TrainingPlanRepository
from backend.db import manager as database_manager_runtime
from backend.db.manager import (
    DATABASE_LOCK as DB_LOCK,
    DatabaseManager,
)
from backend.db.schema import configure_cipher, database_schema_is_current
from backend.config import (
    DEFAULT_OPENAI_BASE_URL,
    load_config,
)
from backend.providers import audio as audio_provider
from backend.providers import calendar as calendar_provider
from backend.providers import http as provider_http
from backend.providers import state as provider_state
from backend.providers import weather as weather_provider
from backend.providers.transport_assembly import (
    IntervalsTransportSettings,
    ProviderHttpSettings,
    ProviderOperationContext,
    ProviderTransportAssembly,
)
from backend.providers.model_assembly import (
    AudioTranscriptionSettings,
    ModelBackgroundPolicy,
    ModelEndpointSettings,
    ModelProviderDiagnostics,
    ModelProviderOwners,
    ModelTransportAssembly,
    ModelTransportClock,
)
from backend.http_api import server as http_server
from backend.http_api.assembly import (
    HttpApiAssembly,
    HttpAudioInput,
    HttpCoachRouteServices,
    HttpCoreAndTransport,
    HttpCoreResources,
    HttpDomainRouteServices,
    HttpHandlerErrors,
    HttpHandlerIdentity,
    HttpHandlerServices,
    HttpRequestBodyLimits,
    HttpResponseServices,
    HttpCoachStreamSettings,
    HttpCoachWriteActions,
    HttpReadRouteServices,
    HttpAthleteServices,
    HttpCoachReadServices,
    HttpCoachWriteServices,
    HttpCoreServices,
    HttpDiagnosticsServices,
    HttpHandlerConfiguration,
    HttpHistoryServices,
    HttpNutritionServices,
    HttpPrivacyServices,
    HttpPublicServices,
    HttpSyncServices,
)
from backend.http_api.auth import (
    SessionAuthService,
    get_session_auth_service,
)
from backend.http_api.public_state_assembly import (
    PublicStateAssembly,
    PublicStateCalendarSettings,
    PublicStateCoreInputs,
    PublicStateOperationalServices,
    PublicStateOwnerAssemblies,
    PublicStateProjectionOwners,
)
from backend.nutrition.assembly import (
    NutritionAssembly,
    NutritionPersistence,
    NutritionRuntime,
)
from backend.sync.command_assembly import (
    IllnessPauseDependencies,
    SyncCommandAssembly,
    SyncCommandCore,
)
from backend.sync.adaptive import AdaptivePreviewFollowupService
from backend.sync.planned_calendar_assembly import (
    PlannedCalendarLocalState,
    PlannedCalendarProvider,
    PlannedCalendarSyncAssembly,
)
from backend.sync.planned_unit_assembly import (
    PlannedUnitOwners,
    PlannedUnitRuntime,
    PlannedUnitSyncAssembly,
)
from backend.sync.library import workout_library_sync_running
from backend.sync.library_assembly import (
    WorkoutLibraryProvider,
    WorkoutLibraryState,
    WorkoutLibrarySyncAssembly,
)
from backend.sync.selected_assembly import (
    SelectedWorkoutControls,
    SelectedWorkoutProviders,
    SelectedWorkoutSyncAssembly,
)
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminMorningRemoteReader,
    shared_garmin_sync_lock,
)
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
from backend.sync import worker as sync_worker_runtime
from backend.sync.worker import shared_sync_job_wake_event
from backend.planning import adaptive as planning_adaptive
from backend.planning.assembly import (
    PlanningDataAssembly,
    PlanningMutations,
    PlanningRepositories as PlanningDataRepositories,
    PlanningRuntime as PlanningDataRuntime,
)
from backend.planning.workflows_assembly import (
    DailyPlanningSources,
    PlanningChangeLimits,
    PlanningRepositories,
    PlanningRuntime,
    PlanningServiceOwners,
    PlanningWorkflowAssembly,
)
from backend.planning import competitions as planning_competitions
from backend.planning import library as planning_library
from backend.planning.revision import PlanningRevisionService
from backend.planning import season as planning_season
from backend.planning import training_plans as planning_training_plans
from backend.sync import scheduler as sync_scheduler_runtime
from backend.coach import context as coach_context_module
from backend.coach.context_assembly import (
    CoachContextAssembly,
    CoachContextDialogueSources,
    CoachContextPerformanceSources,
    CoachContextPlanningSources,
)
from backend.coach.read_tools_assembly import (
    CoachActivityReadSources,
    CoachPlanningReadSources,
    CoachReadToolPolicy,
    CoachReadToolsAssembly,
)
from backend.coach.conversation_assembly import (
    CoachConversationAssembly,
    ConversationPersistence,
    ConversationProfile,
    ConversationRuntime,
    ConversationModelDependencies,
)
from backend.coach.local_assembly import (
    CoachLocalAssembly,
    CoachLocalGarmin,
    CoachLocalPlanning,
    CoachLocalState,
)
from backend.coach.conversation_gate import CoachConversationGate
from backend.coach.proposal_assembly import (
    CoachProposalAssembly,
    ProposalClock,
    ProposalExecutionOwners,
    ProposalPersistence,
)
from backend.coach.planning_tools_assembly import (
    CoachAdaptivePlanningDependencies,
    CoachPlanArtifactDependencies,
    CoachPlanningToolsAssembly,
    CoachTrainingPatchDependencies,
)
from backend.coach.tool_dispatch_assembly import (
    CoachPlanningToolOwners,
    CoachProposalToolOwners,
    CoachReadToolOwners,
    CoachSyncToolOwners,
    CoachToolDispatchAssembly,
)
from backend.coach.command_tools_assembly import (
    CoachAthleteToolFactories,
    CoachCommandToolsAssembly,
    CoachProfileToolDependencies,
    CoachSyncAuthorityTools,
    CoachSyncMutationTools,
    CoachSyncProvider,
)
from backend.coach.structured_tool_round_assembly import (
    CoachStructuredToolRoundAssembly,
    StructuredToolRoundContract,
    StructuredToolRoundConversation,
    StructuredToolRoundRuntime,
    StructuredToolRoundServices,
    StructuredToolRoundState,
)
from backend.coach.background_jobs_assembly import (
    CoachBackgroundJobsAssembly,
    CoachJobAthleteServices,
    CoachJobLimits,
    CoachJobPersistence,
    CoachJobTurnServices,
    CoachJobWorkerRuntime,
)
from backend.coach.turn_assembly import (
    ChatEntryServices,
    CoachTurnAssembly,
    StructuredTurnControlServices,
    StructuredTurnDialogueServices,
    TurnLifecycle,
    TurnPersistence,
)
from backend.coach.dialogue import dialogue_tools
from backend.coach import structured_tool_round
from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundLimits,
)
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.coach.tools import build_tool_contracts
from backend.coach.service import command_receipt
from backend.history.assembly import (
    HistoryAssembly,
    HistoryAthleteServices,
    HistoryPersistence,
    HistoryPlanningServices,
)
from backend.http_api.response_transport import HttpResponseTransport
from backend.backup.assembly import (
    BackupAssembly,
    BackupStorageDependencies,
    RestoreLifecycleDependencies,
    RestoreValidationDependencies,
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
PROVIDER_INTERVALS_WELLNESS_NAME = "Intervals.icu Wellness"
JSON_MEDIA_TYPE = "application/json"
OPENAI_RESPONSES_PATH = "/responses"
PLANNED_WORKOUT_LABEL = "Geplante Einheit"
APP_NAME = "Intervals Coach"
SELECT_PLANNED_PAYLOAD_SQL = "SELECT payload FROM planned_units WHERE local_id=?"
APP_VERSION = "1.12.7"
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
    dependencies=ProviderSyncAssembly.Inputs(
        persistence=ProviderSyncPersistence(
            database_manager=database_manager,
            key_values=KEY_VALUE_REPOSITORY,
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
        ),
        runtime=ProviderSyncRuntime(
            config=lambda: CONFIG,
            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
            logger=LOGGER,
            now=lambda: datetime.now(timezone.utc),
        ),
        retry_policy=ProviderRefreshRetryPolicy(
            uuid_factory=lambda: uuid.uuid4().hex,
            retry_base_seconds=PROVIDER_REFRESH_RETRY_BASE_SECONDS,
            retry_max_seconds=PROVIDER_REFRESH_RETRY_MAX_SECONDS,
        ),
    )
)












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


ATHLETE_DATA = AthleteDataAssembly(
    dependencies=AthleteDataAssembly.Inputs(
        database_manager=database_manager,
        repositories=AthleteRepositories(
            activity_feedback=ACTIVITY_FEEDBACK_REPOSITORY,
            checkin=CHECKIN_REPOSITORY,
            profile=PROFILE_REPOSITORY,
            key_values=KEY_VALUE_REPOSITORY,
            snapshot=SNAPSHOT_REPOSITORY,
            competition=COMPETITION_REPOSITORY,
        ),
        runtime=AthleteRuntime(
            utc_now=runtime_clock.utc_now,
            local_date=lambda: ATHLETE_CLOCK.now().date(),
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            normalize_profile=normalize_profile,
            normalize_competition=planning_competitions.normalize_competition,
            uuid_factory=uuid.uuid4,
        ),
    )
)
ATHLETE_PROFILE_SERVICE = ATHLETE_DATA.profile_for(
    database_manager_runtime.DATABASE_MANAGER_CACHE
)
ATHLETE_CLOCK = AthleteLocalClock(ATHLETE_PROFILE_SERVICE)

PLANNING_DATA = PlanningDataAssembly(
    dependencies=PlanningDataAssembly.Inputs(
        database_manager=database_manager,
        repositories=PlanningDataRepositories(
            competition=COMPETITION_REPOSITORY,
            training_plans=TRAINING_PLAN_REPOSITORY,
            key_values=KEY_VALUE_REPOSITORY,
            plan_adjustments=PLAN_ADJUSTMENT_REPOSITORY,
        ),
        runtime=PlanningDataRuntime(
            revision=PLANNING_REVISION_SERVICE,
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            utc_now=runtime_clock.utc_now,
            local_date=lambda: ATHLETE_CLOCK.now().date(),
            uuid_factory=uuid.uuid4,
            redact=REDACTOR.redact_text,
        ),
        mutations=PlanningMutations(
            calendar_conflict_service=lambda: PLANNING_WORKFLOWS.calendar_conflict_service(),
            publish_change=lambda: runtime_events.STATE_EVENT_BUFFER.publish(
                "coach", {"status": "changed"}
            ),
        ),
    ),
)
PLANNING_WORKFLOWS = PlanningWorkflowAssembly(dependencies=PlanningWorkflowAssembly.Inputs(
    owners=PlanningServiceOwners(
        database_manager=database_manager,
        planned_unit_service=PLANNING_DATA.planned_unit,
        workout_library_service=PLANNING_DATA.workout_library,
        competition_service=PLANNING_DATA.competition,
        training_plan_service=PLANNING_DATA.training_plan,
        checkin_service=lambda: ATHLETE_DATA.checkin(),
    ),
    repositories=PlanningRepositories(
        state_repository=PLANNING_STATE_REPOSITORY,
        training_plan_repository=TRAINING_PLAN_REPOSITORY,
        key_values=KEY_VALUE_REPOSITORY,
        revision_service=PLANNING_REVISION_SERVICE,
        plan_adjustment_repository=PLAN_ADJUSTMENT_REPOSITORY,
    ),
    daily_sources=DailyPlanningSources(
        activity_feedback_service=ATHLETE_DATA.activity_feedback,
        external_calendar_reader=lambda: EXTERNAL_CALENDAR.reader(),
        weather_service=lambda: WEATHER_ASSEMBLY.service(),
        morning_body_battery_service=morning_body_battery_service,
        local_date=lambda: ATHLETE_CLOCK.now().date(),
        calendar_window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        checkin_text_limit=CHECKIN_TEXT_LIMITS["illness"],
    ),
    runtime=PlanningRuntime(
        sync_job_queue_service=lambda: SYNC_JOB_QUEUE.service(),
        coach_artifact_refs=lambda: COACH_CONVERSATION.dialogue_read_service().artifact_refs,
        utc_now=runtime_clock.utc_now,
        uuid_factory=uuid.uuid4,
        event_buffer=runtime_events.STATE_EVENT_BUFFER,
        logger=LOGGER,
    ),
    limits=PlanningChangeLimits(
        training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
        default_illness_pause_days=planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS,
        weather_adaptive_max_minutes=planning_adaptive.WEATHER_ADAPTIVE_MAX_MINUTES,
    ),
))

HISTORY = HistoryAssembly(
    dependencies=HistoryAssembly.Inputs(
        persistence=HistoryPersistence(database_manager, PROFILE_REPOSITORY),
        athlete=HistoryAthleteServices(
            profile_service=ATHLETE_DATA.profile,
            competition_service=PLANNING_DATA.competition,
        ),
        planning=HistoryPlanningServices(
            workout_library_service=PLANNING_DATA.workout_library,
            planned_unit_service=PLANNING_DATA.planned_unit,
            training_plan_service=PLANNING_DATA.training_plan,
            planning_revision_service=PLANNING_REVISION_SERVICE,
        ),
    )
)

PRIVACY_ASSEMBLY = PrivacyAssembly(dependencies=PrivacyAssembly.Inputs(
    athlete=PrivacyAthleteSources(
        profile_service=ATHLETE_DATA.profile,
        checkin_service=ATHLETE_DATA.checkin,
        activity_feedback_service=ATHLETE_DATA.activity_feedback,
    ),
    planning=PrivacyPlanningSources(
        workout_library_service=PLANNING_DATA.workout_library,
        competition_service=PLANNING_DATA.competition,
        training_plan_service=PLANNING_DATA.training_plan,
    ),
    context=PrivacyContextSources(
        adaptive_preview_service=lambda: PLANNING_WORKFLOWS.adaptive_replan_preview_service(),
        external_calendar_reader=lambda: EXTERNAL_CALENDAR.reader(),
    ),
    clock=PrivacyClock(
        local_now=lambda: ATHLETE_CLOCK.now(),
        utc_now=runtime_clock.utc_now,
    ),
    state=PrivacyStateDependencies(
        database_manager=database_manager,
        database_lock=lambda: DB_LOCK,
        key_value_repository=KEY_VALUE_REPOSITORY,
        maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
        planning_revision_service=PLANNING_REVISION_SERVICE,
        openai_client=lambda: MODEL_TRANSPORT.openai_responses_client(),
        logger=LOGGER,
    ),
    archive=PrivacyArchiveSettings(
        data_dir=lambda: DATA_DIR,
        database_path=lambda: DB_PATH,
        maximum_export_bytes=MAX_PRIVACY_EXPORT_BYTES,
        minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
        time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
    ),
))
BACKUP_ASSEMBLY = BackupAssembly(dependencies=BackupAssembly.Inputs(
    storage=BackupStorageDependencies(
        database_manager=database_manager,
        database_path=lambda: DB_PATH,
        data_dir=lambda: DATA_DIR,
        database_lock=lambda: DB_LOCK,
        maximum_bytes=MAX_BACKUP_BYTES,
        minimum_free_bytes=MIN_EXPORT_FREE_BYTES,
        time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
        logger=LOGGER,
    ),
    validation=RestoreValidationDependencies(
        app_password=lambda: CONFIG.app_password,
        sqlcipher_available=lambda: SQLCIPHER_AVAILABLE,
        sqlite_backend=sqlite_backend,
        configure_cipher=configure_cipher,
        row_factory=database_row_factory,
        schema_is_current=database_schema_is_current,
    ),
    lifecycle=RestoreLifecycleDependencies(
        maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
        sync_jobs=lambda: SYNC_JOB_QUEUE.service(),
        coach_jobs=lambda: COACH_BACKGROUND_JOBS.job_store(),
        coach_failures=lambda: COACH_BACKGROUND_JOBS.turn_failure_service(),
        sync_wake_event=shared_sync_job_wake_event,
        coach_wake_event=COACH_JOB_WORKER.wake_event,
        redact=REDACTOR.redact_text,
    ),
))


def sync_job_worker() -> sync_worker_runtime.SyncJobWorker:
    """Return the one restartable persistent synchronization worker."""
    global SYNC_JOB_WORKER
    if SYNC_JOB_WORKER is None:
        SYNC_JOB_WORKER = SYNC_JOB_WORKER_ASSEMBLY.create()
    return SYNC_JOB_WORKER









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
    return KeyValueService(database_manager(), KEY_VALUE_REPOSITORY, DB_LOCK)


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
)

SYNC_PERSISTENCE = SyncPersistenceAssembly(
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    snapshots=SNAPSHOT_REPOSITORY,
    utc_now=runtime_clock.utc_now,
    athlete_clock=lambda: ATHLETE_CLOCK,
)


GARMIN_ASSEMBLY = GarminAssembly(dependencies=GarminAssembly.Inputs(
    provider=GarminProviderSettings(
        config=lambda: CONFIG,
        root=ROOT,
        athlete_clock=ATHLETE_CLOCK,
        earliest_date=SYNC_EARLIEST_DATE,
        sync_chunk_days=SYNC_CHUNK_DAYS,
        all_sync_days=ALL_SYNC_DAYS,
    ),
    persistence=GarminPersistenceOwners(
        database_manager=database_manager,
        key_values=KEY_VALUE_REPOSITORY,
        sync_state_repository=SYNC_PERSISTENCE.state_repository,
        daily_sync_marker_service=SYNC_PERSISTENCE.daily_markers,
    ),
    telemetry=GarminSyncTelemetry(
        redactor=REDACTOR,
        logger=LOGGER,
        diagnostic_capture=DIAGNOSTIC_CAPTURE,
        event_buffer=runtime_events.STATE_EVENT_BUFFER,
    ),
    control=GarminSyncControl(
        utc_now=runtime_clock.utc_now,
        datetime_now=lambda: datetime.now(timezone.utc),
        resync_gate=GARMIN_RESYNC_GATE,
        operation_observer=PROVIDER_SYNC.operation_observer,
        lock_wait_seconds=GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS,
        morning_body_battery_service=morning_body_battery_service,
    ),
))

SYNC_JOB_QUEUE = SyncJobQueueAssembly(
    dependencies=SyncJobQueueAssembly.Inputs(
        persistence=SyncQueuePersistence(
            database_manager=database_manager,
            now=runtime_clock.utc_now,
            current_time=lambda: datetime.now(timezone.utc),
            uuid_factory=lambda: uuid.uuid4().hex,
        ),
        worker=SyncQueueWorker(
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
            wake_event=shared_sync_job_wake_event,
            daily_sync_marker_service=SYNC_PERSISTENCE.daily_markers,
        ),
        policy=SyncQueuePolicy(
            all_sync_days=ALL_SYNC_DAYS,
            redact_text=REDACTOR.redact_text,
            logger=LOGGER,
            retry_base_seconds=SYNC_JOB_RETRY_BASE_SECONDS,
            retry_max_seconds=SYNC_JOB_RETRY_MAX_SECONDS,
        ),
    )
)

EXTERNAL_CALENDAR = ExternalCalendarAssembly(dependencies=ExternalCalendarAssembly.Inputs(
    owners=ExternalCalendarSyncOwners(
        config=lambda: CONFIG,
        database_manager=database_manager,
        key_values=KEY_VALUE_REPOSITORY,
        daily_markers=SYNC_PERSISTENCE.daily_markers,
        adaptive_preview_service=lambda: PLANNING_WORKFLOWS.adaptive_replan_preview_service(),
        event_buffer=runtime_events.STATE_EVENT_BUFFER,
    ),
    runtime=ExternalCalendarSyncRuntime(
        operation_observer=PROVIDER_SYNC.operation_observer,
        logger=LOGGER,
        redact_text=REDACTOR.redact_text,
        athlete_clock=lambda: ATHLETE_CLOCK,
        local_date=lambda: ATHLETE_CLOCK.now().date(),
        utc_now=runtime_clock.utc_now,
        app_version=APP_VERSION,
        sync_lock=lambda: external_calendar_runtime.shared_external_calendar_sync_lock(),
    ),
))


INTERVALS_SYNC = IntervalsSyncAssembly(dependencies=IntervalsSyncAssembly.Inputs(
    provider=IntervalsProviderDependencies(
        config=lambda: CONFIG,
        request=lambda: PROVIDER_TRANSPORT.json_http_client().request,
        athlete_clock=lambda: ATHLETE_CLOCK,
        utc_now=runtime_clock.utc_now,
    ),
    persistence=IntervalsPersistenceDependencies(
        database_manager=database_manager,
        key_values=KEY_VALUE_REPOSITORY,
        state_repository=SYNC_PERSISTENCE.state_repository,
        daily_markers=SYNC_PERSISTENCE.daily_markers,
        event_buffer=runtime_events.STATE_EVENT_BUFFER,
        redact_text=REDACTOR.redact_text,
        logger=LOGGER,
    ),
    operations=IntervalsOperationDependencies(
        operation_observer=PROVIDER_SYNC.operation_observer,
        resync_gate=INTERVALS_RESYNC_GATE,
        sync_lock=INTERVALS_SYNC_LOCK,
        sync_job_queue=SYNC_JOB_QUEUE.service,
    ),
    library=IntervalsLibraryDependencies(
        remote_planned_unit_reconciler=lambda: PLANNED_UNIT_SYNC.remote_reconciler(),
        workout_library_refresh_service=lambda: WORKOUT_LIBRARY_SYNC.refresh_service(),
        workout_library_service=PLANNING_DATA.workout_library,
    ),
    window=IntervalsWindowSettings(
        sync_period_defaults=SYNC_PERIOD_DEFAULTS,
        all_sync_days=ALL_SYNC_DAYS,
        sync_chunk_days=SYNC_CHUNK_DAYS,
        sync_earliest_date=SYNC_EARLIEST_DATE,
        calendar_history_days=PLANNED_CALENDAR_HISTORY_DAYS,
        calendar_future_days=PLANNED_CALENDAR_FUTURE_DAYS,
    ),
    waits=IntervalsWaitSettings(
        performance_wait_seconds=INTERVALS_SYNC_WAIT_SECONDS,
        poll_seconds=SYNC_JOB_POLL_SECONDS,
    ),
))


PROVIDER_TRANSPORT = ProviderTransportAssembly(
    dependencies=ProviderTransportAssembly.Inputs(
        http=ProviderHttpSettings(
            app_version=APP_VERSION,
            max_response_bytes=provider_http.MAX_EXTERNAL_RESPONSE_BYTES,
            logger=LOGGER,
            diagnostic_capture=DIAGNOSTIC_CAPTURE,
            redact_text=REDACTOR.redact_text,
            safe_response_headers=partial(
                observability.safe_response_headers, redact=REDACTOR.redact_text
            ),
            opener=lambda: provider_http.urlopen,
        ),
        operation=ProviderOperationContext(
            provider_state=lambda: provider_state.get_provider_state_service(
                database_manager(),
                KEY_VALUE_REPOSITORY,
                DB_LOCK,
                runtime_clock.utc_now,
                lambda: ATHLETE_CLOCK.now().date(),
                LOGGER,
            ),
            now=runtime_clock.utc_now,
            operation_context=sync_observation.operation_context,
        ),
        intervals=IntervalsTransportSettings(
            config=lambda: CONFIG,
            athlete_now=ATHLETE_CLOCK.now,
        ),
    ),
)
NUTRITION_ASSEMBLY = NutritionAssembly(
    dependencies=NutritionAssembly.Inputs(
        persistence=NutritionPersistence(database_manager, DB_LOCK),
        runtime=NutritionRuntime(
            config=lambda: CONFIG,
            utc_now=runtime_clock.utc_now,
            local_now=ATHLETE_CLOCK.now,
            intervals_request=lambda: PROVIDER_TRANSPORT.json_http_client().request,
        ),
    )
)
MODEL_TRANSPORT = ModelTransportAssembly(dependencies=ModelTransportAssembly.Inputs(
    providers=ModelProviderOwners(
        config=lambda: CONFIG,
        selected_thinking_level=SETTINGS.selected_thinking_level,
        http_client=PROVIDER_TRANSPORT.json_http_client,
        state_service=provider_state_service,
    ),
    endpoints=ModelEndpointSettings(
        gemini_base_url=GEMINI_API_BASE_URL,
        default_openai_base_url=DEFAULT_OPENAI_BASE_URL,
        openai_responses_path=OPENAI_RESPONSES_PATH,
        json_media_type=JSON_MEDIA_TYPE,
        response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
    ),
    audio=AudioTranscriptionSettings(max_audio_bytes=MAX_AUDIO_BODY_BYTES),
    diagnostics=ModelProviderDiagnostics(
        diagnostic_capture=DIAGNOSTIC_CAPTURE,
        logger=LOGGER,
        app_version=APP_VERSION,
    ),
    background=ModelBackgroundPolicy(
        background_poll_seconds=OPENAI_BACKGROUND_POLL_SECONDS,
        background_max_seconds=OPENAI_BACKGROUND_MAX_SECONDS,
        max_response_bytes=lambda: provider_http.MAX_EXTERNAL_RESPONSE_BYTES,
    ),
    clock=ModelTransportClock(
        utc_now=runtime_clock.utc_now,
    ),
))
COACH_CONVERSATION = CoachConversationAssembly(
    persistence=ConversationPersistence(
        database_manager=database_manager,
        key_values=KEY_VALUE_REPOSITORY,
        chat_repository=CHAT_REPOSITORY,
        state_event_buffer=runtime_events.STATE_EVENT_BUFFER,
        database_lock=DB_LOCK,
    ),
    runtime=ConversationRuntime(
        streams=coach_streams.CHAT_STREAM_REGISTRY,
        conversation_lock=COACH_CONVERSATION_GATE.lock,
        openai_client=MODEL_TRANSPORT.openai_responses_client,
        utc_now=runtime_clock.utc_now,
        uuid_factory=uuid.uuid4,
        logger=LOGGER,
    ),
    profile=ConversationProfile(
        profile_service=ATHLETE_DATA.profile,
    ),
    model=ConversationModelDependencies(
        settings=SETTINGS,
        model_transport=MODEL_TRANSPORT,
        default_thinking_level=SETTINGS.selected_thinking_level,
        default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
        json_media_type=JSON_MEDIA_TYPE,
        max_gemini_inline_image_bytes=lambda: coach_attachments.MAX_GEMINI_INLINE_IMAGE_BYTES,
    ),
)
COACH_LOCAL = CoachLocalAssembly(
    dependencies=CoachLocalAssembly.Inputs(
        state=CoachLocalState(
            database_manager=database_manager,
            database_lock=DB_LOCK,
            key_values=KEY_VALUE_REPOSITORY,
        ),
        planning=CoachLocalPlanning(
            sync_job_queue=SYNC_JOB_QUEUE.service,
            local_date=lambda: ATHLETE_CLOCK.now().date(),
            adaptive_preview=PLANNING_WORKFLOWS.adaptive_replan_preview_service,
            planned_workout_label=PLANNED_WORKOUT_LABEL,
        ),
        garmin=CoachLocalGarmin(
            sync_service=GARMIN_ASSEMBLY.sync_service,
            payload_service=GARMIN_ASSEMBLY.payload_service,
            morning_body_battery=morning_body_battery_service,
            logger=LOGGER,
        ),
    )
)
PLANNED_UNIT_SYNC = PlannedUnitSyncAssembly(
    dependencies=PlannedUnitSyncAssembly.Inputs(
        owners=PlannedUnitOwners(
            database_manager=database_manager,
            planned_unit_service=PLANNING_DATA.planned_unit,
            planning_revision_service=PLANNING_REVISION_SERVICE,
        ),
        runtime=PlannedUnitRuntime(
            redactor=REDACTOR,
            utc_now=runtime_clock.utc_now,
            today=lambda: ATHLETE_CLOCK.now().date(),
        ),
    )
)
PLANNED_CALENDAR_SYNC = PlannedCalendarSyncAssembly(
    dependencies=PlannedCalendarSyncAssembly.Inputs(
        provider=PlannedCalendarProvider(
            config=lambda: CONFIG,
            database_manager=database_manager,
            intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
        ),
        local_state=PlannedCalendarLocalState(
            state_writer=PLANNED_UNIT_SYNC.state_writer,
            utc_now=runtime_clock.utc_now,
            today=lambda: ATHLETE_CLOCK.now().date(),
        ),
        future_days=PLANNED_CALENDAR_FUTURE_DAYS,
    )
)
WORKOUT_LIBRARY_SYNC = WorkoutLibrarySyncAssembly(
    dependencies=WorkoutLibrarySyncAssembly.Inputs(
        provider=WorkoutLibraryProvider(
            config=lambda: CONFIG,
            database_manager=database_manager,
            intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
            workout_library_service=PLANNING_DATA.workout_library,
        ),
        state=WorkoutLibraryState(
            key_values=KEY_VALUE_REPOSITORY,
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            redactor=REDACTOR,
            utc_now=runtime_clock.utc_now,
        ),
        uuid_factory=uuid.uuid4,
    )
)
SELECTED_WORKOUT_SYNC = SelectedWorkoutSyncAssembly(
    dependencies=SelectedWorkoutSyncAssembly.Inputs(
        providers=SelectedWorkoutProviders(
            config=lambda: CONFIG,
            database_manager=database_manager,
            workout_library_sync_service=WORKOUT_LIBRARY_SYNC.sync_service,
            planned_calendar_sync_service=PLANNED_CALENDAR_SYNC.sync_service,
            planned_calendar_repair_service=PLANNED_CALENDAR_SYNC.repair_service,
        ),
        controls=SelectedWorkoutControls(
            redactor=REDACTOR.redact_text,
            lock=INTERVALS_SYNC_LOCK,
            wait_seconds=INTERVALS_SYNC_WAIT_SECONDS,
            provider_resync_gate=INTERVALS_RESYNC_GATE,
        ),
    )
)
WEATHER_ASSEMBLY = WeatherAssembly(
    dependencies=WeatherAssembly.Inputs(
        state=WeatherStateOwners(
            database_manager=database_manager,
            key_values=KEY_VALUE_REPOSITORY,
            profile_service=ATHLETE_DATA.profile,
        ),
        provider=WeatherProviderRuntime(
            client_factory=lambda: weather_provider.WeatherClient(
                PROVIDER_TRANSPORT.json_http_client().request,
                runtime_clock.utc_now,
                LOGGER,
            ),
            refresh_tracker=PROVIDER_SYNC.refresh_tracker,
            operation_context=sync_observation.OPERATION_CONTEXT,
            operation_id_factory=lambda: uuid.uuid4().hex,
        ),
        sync=WeatherSyncRuntime(
            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
            now=lambda: datetime.now(timezone.utc),
            today=lambda: ATHLETE_CLOCK.now().date(),
            adaptive_preview_service=PLANNING_WORKFLOWS.adaptive_replan_preview_service,
            observer=PROVIDER_SYNC.operation_observer,
            logger=LOGGER,
        ),
    ),
)

COACH_CONTEXT = CoachContextAssembly(dependencies=CoachContextAssembly.Inputs(
    performance=CoachContextPerformanceSources(
        sync_state_repository=SYNC_PERSISTENCE.state_repository,
        weather_service=WEATHER_ASSEMBLY.service,
        garmin_payload_service=GARMIN_ASSEMBLY.payload_service,
        garmin_projection_service=GARMIN_ASSEMBLY.projection_service,
        activity_feedback_service=ATHLETE_DATA.activity_feedback,
        today=lambda: ATHLETE_CLOCK.now().date(),
        local_date=lambda: ATHLETE_CLOCK.now().date(),
        utc_now=lambda: datetime.now(timezone.utc),
    ),
    planning=CoachContextPlanningSources(
        checkin_service=ATHLETE_DATA.checkin,
        planned_unit_service=PLANNING_DATA.planned_unit,
        daily_context_service=PLANNING_WORKFLOWS.daily_planning_context_service,
        external_calendar_reader=EXTERNAL_CALENDAR.reader,
        competition_service=PLANNING_DATA.competition,
        training_plan_service=PLANNING_DATA.training_plan,
        adaptive_preview_service=lambda: PLANNING_WORKFLOWS.adaptive_replan_preview_service(),
        workout_library_service=PLANNING_DATA.workout_library,
    ),
    dialogue=CoachContextDialogueSources(
        profile_service=ATHLETE_DATA.profile,
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
        default_max_output_tokens=lambda: coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
    ),
))
COACH_READ_TOOLS = CoachReadToolsAssembly(
    dependencies=CoachReadToolsAssembly.Inputs(
        activity=CoachActivityReadSources(
            activity_read_service=ATHLETE_DATA.activity_read,
            garmin_payload_service=GARMIN_ASSEMBLY.payload_service,
            profile_service=ATHLETE_DATA.profile,
            today=lambda: ATHLETE_CLOCK.now().date(),
        ),
        planning=CoachPlanningReadSources(
            structured_training_state_service=PLANNING_WORKFLOWS.structured_training_state_service,
            workout_library_service=PLANNING_DATA.workout_library,
            planned_unit_service=PLANNING_DATA.planned_unit,
            change_history_service=HISTORY.change_history_service,
            competition_service=PLANNING_DATA.competition,
            training_plan_service=PLANNING_DATA.training_plan,
        ),
        policy=CoachReadToolPolicy(
            nutrition_service=NUTRITION_ASSEMBLY.service,
            training_change_limit=lambda: coach_limits.COACH_TRAINING_CHANGE_LIMIT,
            context_service=COACH_CONTEXT.structured_context_service,
        ),
    )
)
COACH_PROPOSALS = CoachProposalAssembly(
    dependencies=CoachProposalAssembly.Inputs(
        persistence=ProposalPersistence(
            database_manager=database_manager,
            sync_state_repository=SYNC_PERSISTENCE.state_repository,
            nutrition_service=NUTRITION_ASSEMBLY.service,
        ),
        execution=ProposalExecutionOwners(
            duplicate_activity_service=ATHLETE_DATA.duplicate_activity,
            history_undo_service=HISTORY.undo_service,
            intervals_client_factory=PROVIDER_TRANSPORT.intervals_client,
            maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
            tool_dispatch_service=lambda: COACH_TOOL_DISPATCH.service(),
        ),
        clock=ProposalClock(
            now=lambda: time.time(),
            utc_now=runtime_clock.utc_now,
            uuid_factory=uuid.uuid4,
        ),
    )
)

PROVIDER_RESYNC = ProviderResyncAssembly(dependencies=ProviderResyncAssembly.Inputs(
    competition=CompetitionSyncOwners(
        config=lambda: CONFIG,
        intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
        competition_service=PLANNING_DATA.competition,
    ),
    resync=ResyncProviderOwners(
        config=lambda: CONFIG,
        intervals_sync_service=INTERVALS_SYNC.sync_service,
        garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
        intervals_resync_gate=INTERVALS_RESYNC_GATE,
        garmin_resync_gate=GARMIN_RESYNC_GATE,
        all_sync_days=ALL_SYNC_DAYS,
    ),
    persistence=ProviderResyncPersistence(
        database_manager=database_manager,
        key_values=KEY_VALUE_REPOSITORY,
        event_buffer=runtime_events.STATE_EVENT_BUFFER,
        redactor=REDACTOR,
    ),
    runtime=ProviderResyncRuntime(
        logger=LOGGER,
        utc_now=runtime_clock.utc_now,
        uuid_factory=lambda: uuid.uuid4().hex,
        monotonic=time.perf_counter,
        operation_observer=PROVIDER_SYNC.operation_observer,
    ),
))


SYNC_JOB_EXECUTION = SyncJobExecutionAssembly(dependencies=SyncJobExecutionAssembly.Inputs(
    historical=HistoricalSyncDependencies(
        local_now=ATHLETE_CLOCK.now,
        sync_period_defaults=SYNC_PERIOD_DEFAULTS,
        all_sync_days=ALL_SYNC_DAYS,
        sync_chunk_days=SYNC_CHUNK_DAYS,
        sync_earliest_date=SYNC_EARLIEST_DATE,
    ),
    state=SyncJobStateDependencies(
        sync_state_repository=SYNC_PERSISTENCE.state_repository,
        queue_service=SYNC_JOB_QUEUE.service,
        outcome_service=SYNC_JOB_QUEUE.outcome_service,
    ),
    intervals=IntervalsJobDependencies(
        sync_service=INTERVALS_SYNC.sync_service,
        performance_refresh_service=INTERVALS_SYNC.performance_service,
        selected_workout_sync_service=SELECTED_WORKOUT_SYNC.service,
        competition_sync_service=PROVIDER_RESYNC.competition_sync_service,
        nutrition_sync_service=NUTRITION_ASSEMBLY.intervals_sync_service,
        operation_observer=PROVIDER_SYNC.operation_observer,
        resync_gate=INTERVALS_RESYNC_GATE,
    ),
    garmin=GarminJobDependencies(
        sync_service=GARMIN_ASSEMBLY.sync_service,
        morning_body_battery_service=morning_body_battery_service,
        fixture_loader=GARMIN_ASSEMBLY.fixture_loader,
    ),
    calendar_weather=CalendarWeatherJobDependencies(
        calendar_sync_service=EXTERNAL_CALENDAR.sync_service,
        weather_sync_service=WEATHER_ASSEMBLY.sync_service,
    ),
))


SYNC_JOB_WORKER_ASSEMBLY = SyncJobWorkerAssembly(
    store=SYNC_JOB_QUEUE.store,
    executor=SYNC_JOB_EXECUTION.executor,
    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
    poll_seconds=SYNC_JOB_POLL_SECONDS,
    wake_event=shared_sync_job_wake_event,
)


SYNC_SCHEDULERS = SyncSchedulerAssembly(dependencies=SyncSchedulerAssembly.Inputs(
    owners=SyncScheduleOwners(
        profile_service=ATHLETE_DATA.profile,
        queue_service=SYNC_JOB_QUEUE.service,
        daily_sync_marker_service=SYNC_PERSISTENCE.daily_markers,
        garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
    ),
    persistence=SyncSchedulePersistence(
        database_manager=database_manager,
        key_values=KEY_VALUE_REPOSITORY,
        database_lock=DB_LOCK,
        sync_state_repository=SYNC_PERSISTENCE.state_repository,
    ),
    controls=SyncScheduleControls(
        intervals_resync_gate=INTERVALS_RESYNC_GATE,
        maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
        sleep=time.sleep,
    ),
    policy=SyncSchedulePolicy(
        config=lambda: CONFIG,
        garmin_automatic_sync_days=GARMIN_AUTOMATIC_SYNC_DAYS,
        auto_update_label=sync_scheduler_runtime.AUTO_UPDATE_LABEL,
        sync_period_defaults=SYNC_PERIOD_DEFAULTS,
        all_sync_days=ALL_SYNC_DAYS,
        sync_chunk_days=SYNC_CHUNK_DAYS,
        sync_earliest_date=SYNC_EARLIEST_DATE,
    ),
    daily_loop=DailySyncLoopSettings(
        morning_body_battery_service=morning_body_battery_service,
        logger=LOGGER,
    ),
))

SYNC_COMMANDS = SyncCommandAssembly(
    core=SyncCommandCore(
        database_manager=database_manager,
        queue_service=SYNC_JOB_QUEUE.service,
        intervals_sync=INTERVALS_SYNC.sync_service,
        planned_unit_service=PLANNING_DATA.planned_unit,
        competition_service=PLANNING_DATA.competition,
        workout_library_sync_state=WORKOUT_LIBRARY_SYNC.sync_state_service,
        planning_revision=PLANNING_REVISION_SERVICE,
        utc_now=runtime_clock.utc_now,
        training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
        all_sync_days=ALL_SYNC_DAYS,
    ),
    illness_pause=IllnessPauseDependencies(
        config=lambda: CONFIG,
        intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
        adaptive_replan_apply=PLANNING_DATA.adaptive_apply,
        adaptive_replan_preview=PLANNING_WORKFLOWS.adaptive_replan_preview_service,
        redactor=REDACTOR,
        today=lambda: ATHLETE_CLOCK.now().date(),
    ),
)










CHAT_PAGE_MAX = 100




COACH_CANONICAL_TOOL_NAMES, COACH_STRUCTURED_TOOLS, STRUCTURED_READ_ONLY_TOOLS, COACH_DIALOGUE_TOOLS, COACH_TOOL_CAPABILITIES = build_tool_contracts(
    default_profile=DEFAULT_PROFILE,
    checkin_text_limits=CHECKIN_TEXT_LIMITS,
    checkin_score_fields=CHECKIN_SCORE_FIELDS,
    training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
    library_bulk_max_entries=planning_library.LIBRARY_BULK_MAX_ENTRIES,
    training_plan_statuses=planning_training_plans.TRAINING_PLAN_STATUSES,
    dialogue_tools=dialogue_tools,
)


COACH_PLANNING_TOOLS = CoachPlanningToolsAssembly(dependencies=CoachPlanningToolsAssembly.Inputs(
    database_manager=database_manager,
    artifacts=CoachPlanArtifactDependencies(
        local_plan_creation_service=PLANNING_WORKFLOWS.local_plan_creation_service,
        athlete_date=lambda: ATHLETE_CLOCK.now().date(),
        utc_now=runtime_clock.utc_now,
        uuid_factory=uuid.uuid4,
    ),
    workout_library_plan_service=PLANNING_WORKFLOWS.workout_library_plan_service,
    training_patch=CoachTrainingPatchDependencies(
        database_lock=DB_LOCK,
        training_change_validator=PLANNING_WORKFLOWS.structured_training_change_validator,
        training_change_service=PLANNING_WORKFLOWS.structured_training_change_service,
        calendar_conflict_service=PLANNING_WORKFLOWS.calendar_conflict_service,
        key_value_repository=KEY_VALUE_REPOSITORY,
        event_buffer=runtime_events.STATE_EVENT_BUFFER,
        training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
    ),
    adaptive=CoachAdaptivePlanningDependencies(
        adaptive_preview_service=lambda: PLANNING_WORKFLOWS.adaptive_replan_preview_service(),
        illness_pause_sync_service=SYNC_COMMANDS.illness_pause,
    ),
))


COACH_COMMAND_TOOLS = CoachCommandToolsAssembly(
    sync_authority=CoachSyncAuthorityTools(
        sync_job_queue=lambda: SYNC_JOB_QUEUE.service(),
        planning_authority=SYNC_COMMANDS.authority,
        sync_conflict_commands=SYNC_COMMANDS.conflicts,
        structured_plan_sync=SYNC_COMMANDS.structured_plan_sync,
    ),
    sync_mutations=CoachSyncMutationTools(
        plan_repair_manifest=SYNC_COMMANDS.repair_manifest,
        plan_push_command=SYNC_COMMANDS.plan_push,
        provider_refresh_command=SYNC_COMMANDS.provider_refresh,
        duplicate_activity=ATHLETE_DATA.duplicate_activity,
    ),
    sync_provider=CoachSyncProvider(
        intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
    ),
    athlete_tools=CoachAthleteToolFactories(
        checkin_service=lambda: ATHLETE_DATA.checkin(),
        activity_feedback_service=lambda: ATHLETE_DATA.activity_feedback(),
        competition_service=lambda: PLANNING_DATA.competition(),
        nutrition_service=NUTRITION_ASSEMBLY.service,
    ),
    profile_tools=CoachProfileToolDependencies(
        profile_service=lambda: ATHLETE_DATA.profile(),
        database_manager=lambda: database_manager(),
        database_lock=DB_LOCK,
    ),
)


COACH_TOOL_DISPATCH = CoachToolDispatchAssembly(dependencies=CoachToolDispatchAssembly.Inputs(
    reads=CoachReadToolOwners(
        read_tools=COACH_READ_TOOLS.read_service,
        profile_update=COACH_COMMAND_TOOLS.profile_update_service,
        athlete_records=COACH_COMMAND_TOOLS.athlete_record_tool_service,
    ),
    planning=CoachPlanningToolOwners(
        training_plan_artifacts=COACH_PLANNING_TOOLS.training_plan_artifact_service,
        training_plan_replacement=PLANNING_WORKFLOWS.structured_training_plan_replacement_service,
        training_changes=PLANNING_WORKFLOWS.structured_training_change_service,
        database_manager=database_manager,
        database_lock=DB_LOCK,
        workout_library_service=PLANNING_DATA.workout_library,
        training_plan_service=PLANNING_DATA.training_plan,
    ),
    sync=CoachSyncToolOwners(
        library_plan_tools=COACH_PLANNING_TOOLS.library_plan_tool_service,
        sync_tools=COACH_COMMAND_TOOLS.sync_tool_service,
        history_undo=HISTORY.undo_service,
    ),
    proposals=CoachProposalToolOwners(
        adaptive_preview=PLANNING_WORKFLOWS.adaptive_replan_preview_service,
        adaptive_apply=COACH_PLANNING_TOOLS.adaptive_apply_service,
        proposal_creation=COACH_PROPOSALS.creation_service,
    ),
))


COACH_TOOL_ROUNDS = CoachStructuredToolRoundAssembly(dependencies=CoachStructuredToolRoundAssembly.Inputs(
    runtime=StructuredToolRoundRuntime(
        database_manager=lambda: database_manager(),
        database_lock=DB_LOCK,
        key_value_repository=KEY_VALUE_REPOSITORY,
        root=ROOT,
        logger=LOGGER,
    ),
    contract=StructuredToolRoundContract(
        tool_names=lambda: (tool["name"] for tool in COACH_DIALOGUE_TOOLS),
        read_only_tools=lambda: STRUCTURED_READ_ONLY_TOOLS,
        sync_period_defaults=SYNC_PERIOD_DEFAULTS,
        all_sync_days=ALL_SYNC_DAYS,
        limits=lambda: CoachStructuredToolRoundLimits(
            max_rounds=structured_tool_round.COACH_TOOL_MAX_ROUNDS,
            background_horizon_days=coach_limits.COACH_BACKGROUND_HORIZON_DAYS,
            default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
            long_plan_max_output_tokens=coach_limits.COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
        ),
    ),
    services=StructuredToolRoundServices(
        clarification_service=COACH_LOCAL.clarification_service,
        training_patch_service=lambda: COACH_PLANNING_TOOLS.training_patch_service(),
        proposal_creation_service=lambda: COACH_PROPOSALS.creation_service(),
        tool_dispatch_service=lambda: COACH_TOOL_DISPATCH.service(),
        dialogue_action_service=COACH_LOCAL.dialogue_action_service,
        planning_authority_service=SYNC_COMMANDS.authority,
    ),
    state=StructuredToolRoundState(
        sync_state_repository=lambda: SYNC_PERSISTENCE.state_repository(),
        job_store=lambda: COACH_BACKGROUND_JOBS.job_store(),
    ),
    conversation=StructuredToolRoundConversation(
        training_context_service=lambda: COACH_CONTEXT.training_context_service(),
        response_service=lambda: COACH_TURNS.structured_response_service(),
    ),
))


COACH_BACKGROUND_JOBS = CoachBackgroundJobsAssembly(dependencies=CoachBackgroundJobsAssembly.Inputs(
    persistence=CoachJobPersistence(
        database_manager=lambda: database_manager(),
        database_lock=DB_LOCK,
        chat_repository=CHAT_REPOSITORY,
        key_value_repository=KEY_VALUE_REPOSITORY,
        event_buffer=runtime_events.STATE_EVENT_BUFFER,
    ),
    worker=CoachJobWorkerRuntime(
        worker_wake_event=lambda: COACH_JOB_WORKER.wake_event,
        maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
        utc_now=runtime_clock.utc_now,
        redactor=REDACTOR,
        repository_root=ROOT,
        logger=LOGGER,
    ),
    turn=CoachJobTurnServices(
        read_only_tools=lambda: STRUCTURED_READ_ONLY_TOOLS,
        settings=SETTINGS,
        stream_registry=lambda: coach_streams.CHAT_STREAM_REGISTRY,
        session_auth_service=session_auth_service,
        chat_turn_service=lambda: COACH_TURNS.chat_turn_service(),
    ),
    athlete=CoachJobAthleteServices(
        manual_morning_checkin_service=COACH_LOCAL.manual_morning_checkin_service,
        quick_actions_service=COACH_LOCAL.quick_actions_service,
        athlete_clock=lambda: ATHLETE_CLOCK.now,
    ),
    limits=CoachJobLimits(
        background_horizon_days=lambda: coach_limits.COACH_BACKGROUND_HORIZON_DAYS,
        max_attachment_storage_bytes=lambda: coach_attachments.MAX_ATTACHMENT_STORAGE_BYTES,
        max_gemini_inline_image_bytes=lambda: coach_attachments.MAX_GEMINI_INLINE_IMAGE_BYTES,
    ),
))


COACH_TURNS = CoachTurnAssembly(
    dependencies=CoachTurnAssembly.Inputs(
        persistence=TurnPersistence(
            database_manager=database_manager,
            database_lock=DB_LOCK,
            chat_repository=CHAT_REPOSITORY,
            key_value_repository=KEY_VALUE_REPOSITORY,
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            utc_now=runtime_clock.utc_now,
            uuid_factory=uuid.uuid4,
        ),
        lifecycle=TurnLifecycle(
            root=ROOT,
            logger=LOGGER,
            conversation_gate=COACH_CONVERSATION_GATE,
            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
        ),
        chat_entry=ChatEntryServices(
            settings=SETTINGS,
            conversation_provision_service=lambda: COACH_CONVERSATION.provision_service,
        ),
        dialogue=StructuredTurnDialogueServices(
            attachment_context_service=lambda: COACH_CONVERSATION.attachment_context_service(),
            dialogue_read_service=lambda: COACH_CONVERSATION.dialogue_read_service(),
            request_payload_service=lambda: COACH_CONTEXT.request_payload_service(),
            response_transport=lambda: COACH_CONVERSATION.response_transport(),
            tool_round_service=lambda: COACH_TOOL_ROUNDS.service(),
        ),
        controls=StructuredTurnControlServices(
            tools=lambda: COACH_DIALOGUE_TOOLS,
            read_only_tools=lambda: STRUCTURED_READ_ONLY_TOOLS,
            job_store=lambda: COACH_BACKGROUND_JOBS.job_store(),
            turn_failure_service=lambda: COACH_BACKGROUND_JOBS.turn_failure_service(),
            tool_dispatch_service=COACH_TOOL_DISPATCH.service,
        ),
    )
)
































PUBLIC_STATE = PublicStateAssembly(dependencies=PublicStateAssembly.Inputs(
    core=PublicStateCoreInputs(
        database_manager=lambda: database_manager(),
        database_lock=lambda: DB_LOCK,
        config=lambda: CONFIG,
        settings=lambda: SETTINGS,
        maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        key_values=lambda: KEY_VALUE_REPOSITORY,
    ),
    owners=PublicStateOwnerAssemblies(
        snapshot_repository=SNAPSHOT_REPOSITORY,
        sync_persistence=lambda: SYNC_PERSISTENCE,
        planning_data=lambda: PLANNING_DATA,
        athlete_data=lambda: ATHLETE_DATA,
        external_calendar=lambda: EXTERNAL_CALENDAR,
        provider_sync=lambda: PROVIDER_SYNC,
        garmin=lambda: GARMIN_ASSEMBLY,
        sync_job_queue=lambda: SYNC_JOB_QUEUE,
    ),
    projections=PublicStateProjectionOwners(
        weather=lambda: WEATHER_ASSEMBLY,
        workout_library_sync=lambda: WORKOUT_LIBRARY_SYNC,
        provider_resync=lambda: PROVIDER_RESYNC,
        coach_conversation=lambda: COACH_CONVERSATION,
        calendar_local=lambda: calendar_local,
        planning_season=lambda: planning_season,
        intervals_state=lambda: intervals_state,
        diagnostic_capture=lambda: DIAGNOSTIC_CAPTURE,
    ),
    operations=PublicStateOperationalServices(
        intervals_sync_lock=lambda: INTERVALS_SYNC_LOCK,
        workout_library_sync_running=lambda: workout_library_sync_running,
        daily_planning_context_service=PLANNING_WORKFLOWS.daily_planning_context_service,
        adaptive_preview_followup_service=lambda: AdaptivePreviewFollowupService(PLANNING_WORKFLOWS.adaptive_replan_preview_service(), LOGGER),
        adaptive_replan_preview_service=PLANNING_WORKFLOWS.adaptive_replan_preview_service,
        morning_checkin_state_service=COACH_LOCAL.morning_checkin_state_service,
        coach_quick_actions_service=COACH_LOCAL.quick_actions_service,
        provider_state_service=provider_state_service,
    ),
    calendar=PublicStateCalendarSettings(
        local_date=lambda: ATHLETE_CLOCK.now().date(),
        local_now=lambda: ATHLETE_CLOCK.now,
        external_calendar_window_days=lambda: calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
        calendar_history_days=lambda: PLANNED_CALENDAR_HISTORY_DAYS,
        calendar_future_days=lambda: PLANNED_CALENDAR_FUTURE_DAYS,
        sync_period_defaults=lambda: SYNC_PERIOD_DEFAULTS,
        all_sync_days=lambda: ALL_SYNC_DAYS,
        planned_workout_label=lambda: PLANNED_WORKOUT_LABEL,
    ),
))

DIAGNOSTICS_ASSEMBLY = DiagnosticsAssembly(dependencies=DiagnosticsAssembly.Inputs(
    runtime=DiagnosticRuntimeDependencies(
        database_manager=database_manager,
        database_lock=DB_LOCK,
        key_values=KEY_VALUE_REPOSITORY,
        config=lambda: CONFIG,
        settings=SETTINGS,
        app_name=APP_NAME,
        app_version=APP_VERSION,
    ),
    provider_health=DiagnosticProviderHealth(
        sync_state=SYNC_PERSISTENCE.state_repository,
        provider_state=provider_state_service,
        provider_freshness=PROVIDER_SYNC.freshness_service,
        redactor=REDACTOR,
    ),
    garmin=DiagnosticGarminServices(
        projection=GARMIN_ASSEMBLY.projection_service,
        client_factory=GARMIN_ASSEMBLY.client_factory,
        fixture_loader=GARMIN_ASSEMBLY.fixture_loader,
        sync_state=GARMIN_ASSEMBLY.sync_state_service,
    ),
    local_projections=DiagnosticLocalProjections(
        profile=ATHLETE_DATA.profile,
        external_calendar_sync=EXTERNAL_CALENDAR.sync_service,
        external_calendar_reader=EXTERNAL_CALENDAR.reader,
        morning_checkin=COACH_LOCAL.morning_checkin_state_service,
        workout_library_sync_state=WORKOUT_LIBRARY_SYNC.sync_state_service,
    ),
    report=DiagnosticReportSettings(
        utc_now=runtime_clock.utc_now,
        diagnostic_capture=DIAGNOSTIC_CAPTURE,
        log_path=lambda: LOG_PATH,
        receipt_parser=command_receipt,
        allowed_tools=lambda: (tool["name"] for tool in COACH_DIALOGUE_TOOLS),
    ),
))


HTTP_API = HttpApiAssembly(
    dependencies=HttpApiAssembly.Inputs(
        core=HttpCoreAndTransport(
            services=HttpCoreServices(
                resources=HttpCoreResources(
                    database_manager=lambda: database_manager(),
                    database_lock=lambda: DB_LOCK,
                    data_dir=lambda: DATA_DIR,
                    readiness_maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
                ),
                handler=HttpHandlerServices(
                    handler_configuration=lambda: HttpHandlerConfiguration(
                        identity=HttpHandlerIdentity(
                            app_version=APP_VERSION,
                            logger=LOGGER,
                            session_auth_service=session_auth_service,
                            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
                        ),
                        errors=HttpHandlerErrors(
                            redact_text=REDACTOR.redact_text,
                            public_app_error_status=public_app_error_status,
                            internal_server_error=INTERNAL_SERVER_ERROR,
                        ),
                        body_limits=HttpRequestBodyLimits(
                            max_body_bytes=MAX_BODY_BYTES,
                            max_audio_body_bytes=MAX_AUDIO_BODY_BYTES,
                        ),
                        audio=HttpAudioInput(
                            voice_audio_types=audio_provider.VOICE_AUDIO_TYPES,
                            normalize_audio_type=audio_provider.normalized_audio_type,
                        ),
                        public_dir=PUBLIC_DIR,
                    ),
                    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
                    session_auth_service=session_auth_service,
                    settings=SETTINGS,
                    redact_text=REDACTOR.redact_text,
                    logger=LOGGER,
                ),
                response=HttpResponseServices(HttpResponseTransport(), LOGGER),
            ),
            openai_response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
        ),
        coach=HttpCoachRouteServices(
            reads=HttpCoachReadServices(
                conversation_history_service=COACH_CONVERSATION.history_service,
                proposal_read_service=COACH_PROPOSALS.read_service,
                chat_page_max=CHAT_PAGE_MAX,
                command_receipt_service=COACH_TURNS.command_receipt_service,
                job_submission_service=COACH_BACKGROUND_JOBS.job_submission_service,
            ),
            writes=HttpCoachWriteServices(
                actions=HttpCoachWriteActions(
                    job_cancellation_service=COACH_BACKGROUND_JOBS.cancellation_service,
                    context_preview_service=COACH_CONTEXT.preview_service,
                    proposal_creation_service=COACH_PROPOSALS.creation_service,
                    proposal_confirmation_service=COACH_PROPOSALS.confirmation_service,
                    proposal_execution_service=COACH_PROPOSALS.execution_service,
                    reset_service=COACH_CONVERSATION.reset_service,
                    provision_service=lambda: COACH_CONVERSATION.provision_service(),
                    planning_command_service=COACH_TURNS.planning_command_service,
                ),
                stream=HttpCoachStreamSettings(
                    max_chat_request_bytes=coach_attachments.MAX_REQUEST_BYTES,
                    chat_stream_registry=coach_streams.CHAT_STREAM_REGISTRY,
                ),
            ),
        ),
        reads=HttpReadRouteServices(
            public=HttpPublicServices(
                bootstrap=PUBLIC_STATE.bootstrap_service,
                plan_state=PUBLIC_STATE.plan_state_service,
                weather_state=PUBLIC_STATE.weather_state_service,
                performance_state=PUBLIC_STATE.performance_state_service,
                feedback_state=PUBLIC_STATE.feedback_state_service,
                sync_state=PUBLIC_STATE.sync_public_state_service,
            ),
            athlete=HttpAthleteServices(
                profile=ATHLETE_DATA.profile,
                competition=PLANNING_DATA.competition,
                activity_read=ATHLETE_DATA.activity_read,
                checkin=ATHLETE_DATA.checkin,
                context_service=ATHLETE_DATA.context,
                clock=ATHLETE_CLOCK,
                local_today=lambda: ATHLETE_CLOCK.now().date(),
                state_event_buffer=runtime_events.STATE_EVENT_BUFFER,
            ),
            diagnostics=HttpDiagnosticsServices(
                recent_logs=DIAGNOSTICS_ASSEMBLY.recent_log_entries_service,
                report=DIAGNOSTICS_ASSEMBLY.report_service,
            ),
            history=HttpHistoryServices(
                change_history=HISTORY.change_history_service,
                undo=HISTORY.undo_service,
            ),
        ),
        domains=HttpDomainRouteServices(
            privacy=HttpPrivacyServices(
                backup=BACKUP_ASSEMBLY.backup_service,
                export=PRIVACY_ASSEMBLY.archive_export_service,
                monotonic=time.monotonic,
                export_time_limit_seconds=EXPORT_TIME_LIMIT_SECONDS,
                delete=PRIVACY_ASSEMBLY.delete_service,
                restore=BACKUP_ASSEMBLY.restore_service,
                max_backup_bytes=MAX_BACKUP_BYTES,
            ),
            sync=HttpSyncServices(
                job_queue=SYNC_JOB_QUEUE.service,
                state_repository=SYNC_PERSISTENCE.state_repository,
                performance_refresh=INTERVALS_SYNC.performance_service,
                full_resync=PROVIDER_RESYNC.full_resync_service,
                period_defaults=SYNC_PERIOD_DEFAULTS,
                all_sync_days=ALL_SYNC_DAYS,
                uuid_factory=lambda: uuid.uuid4().hex,
            ),
            nutrition=HttpNutritionServices(
                nutrition=NUTRITION_ASSEMBLY.service,
                intervals_sync=NUTRITION_ASSEMBLY.intervals_sync_service,
                audio_transcription=MODEL_TRANSPORT.audio_transcription_client,
            ),
        ),
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
    server = http_server.CoachHTTPServer(("0.0.0.0", CONFIG.port), HTTP_API.request_handler_class())
    server.allow_reuse_address = True
    sync_worker: sync_worker_runtime.SyncJobWorker | None = None
    daily_loop: sync_scheduler_runtime.DailySyncLoop | None = None
    daily_thread: threading.Thread | None = None
    try:
        SYNC_JOB_QUEUE.service().resume_interrupted()
        COACH_BACKGROUND_JOBS.job_store().resume_interrupted(COACH_BACKGROUND_JOBS.turn_failure_service())
        sync_worker = sync_job_worker()
        sync_worker.start()
        COACH_JOB_WORKER.start(
            COACH_BACKGROUND_JOBS.job_store,
            COACH_BACKGROUND_JOBS.background_job_runner,
            runtime_maintenance.MAINTENANCE_GATE,
            lambda: COACH_BACKGROUND_JOBS.job_store().resume_interrupted(
                COACH_BACKGROUND_JOBS.turn_failure_service()
            ),
        )
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
