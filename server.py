from __future__ import annotations

import faulthandler
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from backend import config as app_config
from backend import observability
from backend.activities.route_store import ActivityRouteService
from backend.app.context import AppContext
from backend.athlete.checkins import (
    CHECKIN_SCORE_FIELDS,
    CHECKIN_TEXT_LIMITS,
)
from backend.athlete.clock import AthleteLocalClock
from backend.athlete.profile import DEFAULT_PROFILE
from backend.athlete.sessions import AthleteSessionService
from backend.backup.database import (
    MAX_BACKUP_BYTES,
)
from backend.backup.staging_sweep import remove_orphaned_staging_files
from backend.backup.wiring import build_backup
from backend.calendar import local as calendar_local
from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.coach import attachments as coach_attachments
from backend.coach import context as coach_context_module
from backend.coach import limits as coach_limits
from backend.coach import streams as coach_streams
from backend.coach import structured_tool_round
from backend.coach.background_jobs_assembly import (
    CoachBackgroundJobsAssembly,
    CoachJobAthleteServices,
    CoachJobLimits,
    CoachJobPersistence,
    CoachJobTurnServices,
    CoachJobWorkerRuntime,
)
from backend.coach.command_tools_assembly import (
    CoachAthleteToolFactories,
    CoachCommandToolsAssembly,
    CoachProfileToolDependencies,
    CoachSyncAuthorityTools,
    CoachSyncMutationTools,
    CoachSyncProvider,
)
from backend.coach.context_assembly import (
    CoachContextAssembly,
    CoachContextDialogueSources,
    CoachContextPerformanceSources,
    CoachContextPlanningSources,
)
from backend.coach.conversation_assembly import (
    CoachConversationAssembly,
    ConversationModelDependencies,
    ConversationPersistence,
    ConversationProfile,
    ConversationRuntime,
)
from backend.coach.conversation_gate import CoachConversationGate
from backend.coach.dialogue import dialogue_tools
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.coach.local_assembly import (
    CoachLocalAssembly,
    CoachLocalGarmin,
    CoachLocalPlanning,
    CoachLocalState,
)
from backend.coach.planning_tools_assembly import (
    CoachAdaptivePlanningDependencies,
    CoachPlanArtifactDependencies,
    CoachPlanningToolsAssembly,
    CoachTrainingPatchDependencies,
)
from backend.coach.proposal_assembly import (
    CoachProposalAssembly,
    ProposalClock,
    ProposalExecutionOwners,
    ProposalPersistence,
)
from backend.coach.read_tools_assembly import (
    CoachActivityReadSources,
    CoachPlanningReadSources,
    CoachReadToolPolicy,
    CoachReadToolsAssembly,
)
from backend.coach.structured_tool_round import (
    CoachStructuredToolRoundLimits,
)
from backend.coach.structured_tool_round_assembly import (
    CoachStructuredToolRoundAssembly,
    StructuredToolRoundContract,
    StructuredToolRoundConversation,
    StructuredToolRoundRuntime,
    StructuredToolRoundServices,
    StructuredToolRoundState,
)
from backend.coach.tool_dispatch_assembly import (
    CoachPlanningToolOwners,
    CoachProposalToolOwners,
    CoachReadToolOwners,
    CoachSyncToolOwners,
    CoachToolDispatchAssembly,
)
from backend.coach.tool_registry import build_tool_contracts
from backend.coach.turn_assembly import (
    ChatEntryServices,
    CoachTurnAssembly,
    StructuredTurnControlServices,
    StructuredTurnDialogueServices,
    TurnLifecycle,
    TurnPersistence,
)
from backend.config import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_OPENAI_BASE_URL,
    load_config,
)
from backend.db import manager as database_manager_runtime
from backend.db import row_factory as database_row_factory
from backend.db.bootstrap import (
    initialize_application_database,
)
from backend.db.key_value import KeyValueService
from backend.db.manager import (
    DATABASE_LOCK as DB_LOCK,
)
from backend.db.manager import (
    DatabaseManager,
    background_writer,
)
from backend.db.repositories import (
    ActivityFeedbackRepository,
    ChatRepository,
    CheckinRepository,
    KeyValueRepository,
    PlanAdjustmentRepository,
    PlanningStateRepository,
    ProfileRepository,
    TrainingPlanRepository,
)
from backend.db.schema import configure_cipher
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.wiring import build_diagnostics
from backend.errors import INTERNAL_SERVER_ERROR
from backend.history.wiring import build_history
from backend.http_api import server as http_server
from backend.http_api.activity_assembly import (
    ActivityReadAssembly,
    ActivityReadSources,
)
from backend.http_api.assembly import (
    HttpApiAssembly,
    HttpAthleteServices,
    HttpAudioInput,
    HttpCoachReadServices,
    HttpCoachRouteServices,
    HttpCoachStreamSettings,
    HttpCoachWriteActions,
    HttpCoachWriteServices,
    HttpCoreAndTransport,
    HttpCoreResources,
    HttpCoreServices,
    HttpDiagnosticsServices,
    HttpDomainRouteServices,
    HttpHandlerConfiguration,
    HttpHandlerErrors,
    HttpHandlerIdentity,
    HttpHandlerServices,
    HttpHistoryServices,
    HttpNutritionServices,
    HttpPrivacyServices,
    HttpPublicServices,
    HttpReadRouteServices,
    HttpRequestBodyLimits,
    HttpResponseServices,
    HttpSyncServices,
)
from backend.http_api.athlete_assembly import (
    AthleteDataAssembly,
    AthleteRepositories,
    AthleteRuntime,
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
from backend.http_api.response_transport import HttpResponseTransport
from backend.nutrition.wiring import NutritionServices, build_nutrition
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.performance.morning_battery_service import (
    MORNING_BODY_BATTERY_SERVICE_CACHE,
    MorningBatteryClock,
    MorningBatteryEvents,
    MorningBatteryExecutionGate,
    MorningBatteryRetryPolicy,
    MorningBatterySource,
    MorningBatteryStore,
    MorningBodyBatteryService,
)
from backend.performance.source_policy import preferences_from_profile
from backend.performance.threshold_staleness import ThresholdStalenessService
from backend.performance.wiring import build_performance
from backend.planning import library as planning_library
from backend.planning import season as planning_season
from backend.planning import training_plans as planning_training_plans
from backend.planning.block_review import block_review, last_completed_test
from backend.planning.compact_activities import ActivitySummarySource
from backend.planning.plan_guard_service import (
    read_load_thresholds,
)
from backend.planning.revision import PlanningRevisionService
from backend.planning.run_lthr import RunLthr
from backend.planning.season_preparation import season_preparation
from backend.planning.wiring import (
    build_plan_guard,
    build_planning_data,
    build_planning_workflows,
)
from backend.privacy import build_privacy
from backend.provider_credentials import (
    GARMIN_SOURCE_DB,
    GARMIN_TOKENS_KEY,
    GARMIN_TOKENSTORE_STATE_KEY,
    PROVIDER_CREDENTIALS_KEY,
    WAHOO_TOKENS_KEY,
    ProviderCredentialService,
)
from backend.providers import activity_weather as activity_weather_provider
from backend.providers import audio as audio_provider
from backend.providers import calendar as calendar_provider
from backend.providers import state as provider_state
from backend.providers.connection_check_probes import (
    build_probes as build_connection_probes,
)
from backend.providers.connection_checks import ProviderConnectionChecks
from backend.providers.model_wiring import (
    JSON_MEDIA_TYPE,
    OPENAI_RESPONSE_TIMEOUT_SECONDS,
    ModelTransportServices,
    build_model_transport,
)
from backend.providers.observed_opener import Opener, observed_opener
from backend.providers.transport_wiring import build_provider_transport
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance
from backend.settings import SettingsService
from backend.sync import external_calendar as external_calendar_runtime
from backend.sync import intervals_state
from backend.sync import observation as sync_observation
from backend.sync import scheduler as sync_scheduler_runtime
from backend.sync import worker as sync_worker_runtime
from backend.sync.adaptive import AdaptivePreviewFollowupService
from backend.sync.canonical_backfill_assembly import build_canonical_backfill
from backend.sync.canonical_read_assembly import build_canonical_read
from backend.sync.canonical_read_selector import CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.daily import DailySyncMarkerService
from backend.sync.execution_assembly import (
    CalendarWeatherJobDependencies,
    GarminJobDependencies,
    HistoricalSyncDependencies,
    IntervalsJobDependencies,
    SyncJobExecutionAssembly,
    SyncJobStateDependencies,
    WahooJobDependencies,
    configured_for_job,
    provider_configured_checks,
)
from backend.sync.executor import chained_after_job
from backend.sync.external_calendar_assembly import (
    ExternalCalendarAssembly,
    ExternalCalendarSyncOwners,
    ExternalCalendarSyncRuntime,
)
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
from backend.sync.garmin_login import (
    GarminLoginService,
    GarminSecretRegistry,
    GarminTokenStore,
)
from backend.sync.garmin_service import (
    GARMIN_AUTOMATIC_SYNC_DAYS,
    GarminMorningRemoteReader,
    shared_garmin_sync_lock,
)
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.garmin_wiring import GarminServices, build_garmin
from backend.sync.gates import (
    GARMIN_RESYNC_GATE,
    INTERVALS_RESYNC_GATE,
    WAHOO_RESYNC_GATE,
)
from backend.sync.library import workout_library_sync_running
from backend.sync.library_assembly import (
    WorkoutLibraryProvider,
    WorkoutLibraryState,
    WorkoutLibrarySyncAssembly,
)
from backend.sync.local_load import refresh_after_job
from backend.sync.metric_export import MetricExportService
from backend.sync.metric_export_assembly import (
    build_metric_export_service,
    export_thresholds_reader,
)
from backend.sync.metric_export_runner import MetricExportRunner
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
from backend.sync.profile_weekly_plan_removal import ProfileWeeklyPlanRemoval
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_resync_assembly import (
    CompetitionSyncOwners,
    ProviderResyncAssembly,
    ProviderResyncPersistence,
    ProviderResyncRuntime,
    ResyncProviderOwners,
)
from backend.sync.rating_backfill_removal import RatingBackfillRemoval
from backend.sync.retry_hold import ProviderRetryHold
from backend.sync.scheduler_assembly import (
    DailySyncLoopSettings,
    SyncScheduleControls,
    SyncScheduleOwners,
    SyncSchedulePersistence,
    SyncSchedulePolicy,
    SyncScheduleProviders,
    SyncSchedulerAssembly,
)
from backend.sync.selected_assembly import (
    SelectedWorkoutControls,
    SelectedWorkoutProviders,
    SelectedWorkoutSyncAssembly,
)
from backend.sync.session_focus_backfill import SessionFocusBackfill
from backend.sync.session_rebundle import SessionRebundle
from backend.sync.state import SyncStateRepository
from backend.sync.wahoo_connection import WahooSecretRegistry
from backend.sync.wahoo_wiring import build_wahoo_connection, build_wahoo_sync
from backend.sync.weather import build_weather_sync
from backend.sync.wiring import (
    build_provider_sync,
    build_sync_commands,
    build_sync_job_queue,
    build_sync_persistence,
    build_sync_worker,
    coach_synchronous_refreshes,
)
from backend.weather.activity_weather_store import home_coordinates
from backend.weather.recommendations import PLANNED_WORKOUT_LABEL
from backend.weather.wiring import WeatherServices, build_weather

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
APP_NAME = "Pacecraft · AI Coach"
APP_VERSION = "2.1.5"
MAX_BODY_BYTES = 1_000_000
MAX_AUDIO_BODY_BYTES = 8_000_000
COACH_CONVERSATION_GATE = CoachConversationGate()
SYNC_JOB_WORKER: sync_worker_runtime.SyncJobWorker | None = None


ENV_CONFIG = load_config(ROOT, DATA_DIR)
# Runtime configuration: environment values overlaid with stored credentials.
CONFIG = ENV_CONFIG
# Bumped whenever CONFIG is replaced so cached services rebuild with new values.
CONFIG_GENERATION = 0


LOGGER = logging.getLogger("intervals_coach")
GARMIN_SECRET_REGISTRY = GarminSecretRegistry()
WAHOO_SECRET_REGISTRY = WahooSecretRegistry()


def _nutrition_secret_values() -> tuple[str, ...]:
    # Logging starts before NUTRITION_SERVICES exists.
    nutrition = globals().get("NUTRITION_SERVICES")
    return () if nutrition is None else nutrition.secret_values()


# Environment secrets stay redacted while a stored credential overrides them.
REDACTOR = observability.Redactor(
    lambda: CONFIG,
    extra_secrets=lambda: (
        *GARMIN_SECRET_REGISTRY.values(),
        *WAHOO_SECRET_REGISTRY.values(),
        *_nutrition_secret_values(),
        *observability.config_secret_values(ENV_CONFIG),
    ),
)


KEY_VALUE_REPOSITORY = KeyValueRepository(runtime_clock.utc_now)
ATHLETE_SESSION_SERVICE = AthleteSessionService()
PROFILE_REPOSITORY = ProfileRepository(KEY_VALUE_REPOSITORY)
TRAINING_PLAN_REPOSITORY = TrainingPlanRepository()
PLANNING_STATE_REPOSITORY = PlanningStateRepository()
PLANNING_REVISION_SERVICE = PlanningRevisionService(
    PLANNING_STATE_REPOSITORY, runtime_clock.utc_now
)
PLAN_ADJUSTMENT_REPOSITORY = PlanAdjustmentRepository()
CHAT_REPOSITORY = ChatRepository(runtime_clock.utc_now)
CHECKIN_REPOSITORY = CheckinRepository(runtime_clock.utc_now)
ACTIVITY_FEEDBACK_REPOSITORY = ActivityFeedbackRepository(runtime_clock.utc_now)


GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS = 120


def database_manager() -> DatabaseManager:
    """Return the manager for the active path and secure configuration."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signature = (str(DB_PATH.resolve()), CONFIG.app_password, SQLCIPHER_AVAILABLE)
    if CONFIG.app_password and not SQLCIPHER_AVAILABLE:
        database_manager_runtime.DATABASE_MANAGER_CACHE.reset()
        raise RuntimeError(
            "SQLCipher ist für eine verschlüsselte Datenbank erforderlich."
        )
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
        database_manager(),
        DB_LOCK,
        CONFIG,
        SQLCIPHER_AVAILABLE,
        ATHLETE_SESSION_SERVICE,
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


def morning_body_battery_service() -> MorningBodyBatteryService:
    """Compose morning recovery orchestration from concrete runtime resources."""
    manager = database_manager()
    # The generation guards against a reused id after CONFIG is replaced.
    config_id = (id(CONFIG), CONFIG_GENERATION)
    return MORNING_BODY_BATTERY_SERVICE_CACHE.get(
        manager,
        config_id,
        MorningBatteryStore(
            manager,
            KEY_VALUE_REPOSITORY,
            GarminSnapshotWriter(
                KEY_VALUE_REPOSITORY, lambda: ATHLETE_CLOCK.now().tzinfo
            ),
            CanonicalTableReader(),
        ),
        MorningBatterySource(
            GARMIN_ASSEMBLY.fixture_loader(),
            GarminMorningRemoteReader(
                CONFIG,
                GARMIN_ASSEMBLY.client_factory(),
                ATHLETE_DATA.profile(),
                ATHLETE_CLOCK,
                DIAGNOSTIC_CAPTURE,
                LOGGER,
                garmin_tokens=GARMIN_TOKENS,
            ),
            observability.safe_diagnostic_error,
        ),
        MorningBatteryExecutionGate(
            shared_garmin_sync_lock(),
            runtime_maintenance.MAINTENANCE_GATE,
            GARMIN_RESYNC_GATE,
            GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS,
        ),
        MorningBatteryClock(lambda: datetime.now(UTC), ATHLETE_CLOCK.now),
        MorningBatteryEvents(runtime_events.STATE_EVENT_BUFFER.publish, LOGGER),
        MorningBatteryRetryPolicy(),
    )


PROFILE_MUTATION_COORDINATOR = threading.RLock()

# Declared ahead of its first lambda reference; assigned before the plan guard.
RUN_LTHR: RunLthr

# Declared ahead of its first lambda reference; assigned after METRIC_EXPORT below.
METRIC_EXPORT_RUNNER: MetricExportRunner
# Declared ahead of its first lambda reference; assigned after METRIC_EXPORT_RUNNER.
THRESHOLD_WARNINGS: ThresholdStalenessService
ATHLETE_DATA = AthleteDataAssembly(
    dependencies=AthleteDataAssembly.Inputs(
        database_manager=database_manager,
        profile_mutation_coordinator=PROFILE_MUTATION_COORDINATOR,
        repositories=AthleteRepositories(
            activity_feedback=ACTIVITY_FEEDBACK_REPOSITORY,
            checkin=CHECKIN_REPOSITORY,
            profile=PROFILE_REPOSITORY,
            key_values=KEY_VALUE_REPOSITORY,
            activity_rows=lambda: CANONICAL_READ,
            table_serving=lambda: CANONICAL_READ,
        ),
        runtime=AthleteRuntime(
            utc_now=runtime_clock.utc_now,
            local_date=lambda: ATHLETE_CLOCK.now().date(),
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            read_planned_units=lambda: PLANNING_DATA.planned_unit().list(500),
            load_inputs_changed=lambda: start_canonical_backfill(),
            thresholds_changed=lambda: METRIC_EXPORT_RUNNER.request(),
            threshold_warnings=lambda: THRESHOLD_WARNINGS.read(),
            run_lthr_on=lambda day: RUN_LTHR.on(day),
            run_lthr_resolver=lambda: RUN_LTHR.day_resolver(),
        ),
    )
)
ATHLETE_PROFILE_SERVICE = ATHLETE_DATA.profile_for(
    database_manager_runtime.DATABASE_MANAGER_CACHE
)
# Declared ahead of its first lambda reference; assigned by build_canonical_read below.
CANONICAL_READ: CanonicalReadSelector

# Renames a recognised route of outdoor sessions (#1868); only the label is exposed.
ACTIVITY_ROUTES = ActivityRouteService(database_manager, DB_LOCK, KEY_VALUE_REPOSITORY)

ACTIVITY_READS = ActivityReadAssembly(
    database_manager,
    ActivityReadSources(
        lambda: CANONICAL_READ,
        observation_reader=lambda: CANONICAL_READ,
        coverage=lambda: CANONICAL_READ,
        serving=lambda: CANONICAL_READ,
        source_preferences=lambda db: preferences_from_profile(
            ATHLETE_DATA.profile().get_from_db(db)
        ),
    ),
    ATHLETE_DATA.activity_feedback,
    lambda activity_id: ATHLETE_DATA.equipment().read(activity_id=activity_id),
    refreshable_providers=lambda: configured_for_job(
        PROVIDER_CONFIGURED, "activity_details"
    ),
)
ATHLETE_CLOCK = AthleteLocalClock(ATHLETE_PROFILE_SERVICE)

# The application context the domain builders read (#2069). Owners whose
# builder step has not run yet are set as they are created.
APP = AppContext(
    config=lambda: CONFIG,
    database=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    clock=ATHLETE_CLOCK,
    ids=lambda: uuid.uuid4().hex,
    logger=LOGGER,
    maintenance=runtime_maintenance.MAINTENANCE_GATE,
    redactor=REDACTOR,
    operation_context=sync_observation.OPERATION_CONTEXT,
    database_lock=DB_LOCK,
    data_dir=lambda: DATA_DIR,
    database_path=lambda: DB_PATH,
    sqlcipher_available=lambda: SQLCIPHER_AVAILABLE,
    sqlite_backend=sqlite_backend,
    profile_mutation_coordinator=PROFILE_MUTATION_COORDINATOR,
    # Defined below; looked up when a provider client is built or on use.
    refresh_config=lambda: refresh_runtime_config(),
    observed_opener=lambda service: observed_provider_opener(service),
    log_path=lambda: LOG_PATH,
    app_name=APP_NAME,
    app_version=APP_VERSION,
    provider_state=provider_state_service,
    athlete=ATHLETE_DATA,
    athlete_profile=ATHLETE_PROFILE_SERVICE,
    planning_revision=PLANNING_REVISION_SERVICE,
    morning_body_battery_service=morning_body_battery_service,
)
PROVIDER_SYNC = build_provider_sync(APP)
APP.provider_sync = PROVIDER_SYNC
PLANNING_DATA = build_planning_data(APP)
APP.planning = PLANNING_DATA
PLANNING_WORKFLOWS = build_planning_workflows(APP)
APP.planning_workflows = PLANNING_WORKFLOWS
PERFORMANCE = build_performance(
    APP,
    session_activities=CanonicalTableReader().session_activities,
    # Defined below; the HTTP public-state projections the reports read.
    plan_state=lambda: PUBLIC_STATE.plan_state_service(),
    performance_state=lambda: PUBLIC_STATE.performance_state_service(),
    canonical_performance_source=lambda: PUBLIC_STATE.canonical_performance_source(),
    season_source=lambda: PUBLIC_STATE.season_source(),
    block_review=block_review,
    last_completed_test=last_completed_test,
    season_preparation=season_preparation,
)
APP.performance = PERFORMANCE
PLAN_GUARD = build_plan_guard(APP)
HISTORY = build_history(APP)


def start_canonical_backfill() -> None:
    return CANONICAL_BACKFILL.worker.start()


def server_log_files() -> RecentLogEntriesService:
    return DIAGNOSTICS.recent_log_entries_service()


PRIVACY = build_privacy(
    database_manager=database_manager,
    profile_service=ATHLETE_DATA.profile,
    competition_service=PLANNING_DATA.competition,
    adaptive_preview_service=lambda: (
        PLANNING_WORKFLOWS.adaptive_replan_preview_service()
    ),
    planning_revision_service=PLANNING_REVISION_SERVICE,
    openai_client=lambda: MODEL_TRANSPORT.openai_responses_client(),
    local_now=lambda: ATHLETE_CLOCK.now(),
    diagnostics_suspended=lambda: APP.diagnostic_capture.suspended(),
    refresh_credentials=lambda: refresh_runtime_config(),
    cancel_garmin_login=lambda: GARMIN_LOGIN.cancel(),
    disconnect_wahoo=lambda: disconnect_wahoo_grant(),
    cancel_coach_turns=lambda: (
        APP.coach_conversation.reset_service().cancel_running_turns()
    ),
    log_files=server_log_files,
)
BACKUP = build_backup(APP)


def sync_job_worker() -> sync_worker_runtime.SyncJobWorker:
    """Return the one restartable persistent synchronization worker."""
    global SYNC_JOB_WORKER
    if SYNC_JOB_WORKER is None:
        SYNC_JOB_WORKER = SYNC_WORKERS.create()
    return SYNC_JOB_WORKER


def initialise_database() -> None:
    with DB_LOCK, database_manager().unit_of_work() as db:
        initialize_application_database(
            db,
            key_values=KEY_VALUE_REPOSITORY,
            now=runtime_clock.utc_now(),
            current_time=datetime.now(UTC),
            default_profile_json=json.dumps(DEFAULT_PROFILE),
            provider_resync_keys=PROVIDER_RESYNC_KEYS.values(),
            retention_days=int(getattr(CONFIG, "data_retention_days", -1)),
        )
    refresh_runtime_config()


def key_value_service() -> KeyValueService:
    return KeyValueService(database_manager, KEY_VALUE_REPOSITORY, DB_LOCK)


SYNC_PERIOD_DEFAULTS = DEFAULT_PROVIDER_REGISTRY.sync_period_defaults()
ALL_SYNC_DAYS = -1
SYNC_CHUNK_DAYS = 90
SYNC_EARLIEST_DATE = CONFIG.sync_history_earliest_date
PLANNED_CALENDAR_FUTURE_DAYS = 35
SETTINGS = SettingsService(
    lambda: CONFIG,
    lambda key: key_value_service().get(key),
    lambda key, value: key_value_service().set(key, value),
    claude_models=lambda: MODEL_TRANSPORT.claude_models().status(),
)


def apply_runtime_config(config: app_config.Config) -> None:
    """Swap the runtime configuration; lambda readers see the new value at once."""
    global CONFIG, CONFIG_GENERATION
    if config is CONFIG:
        return
    CONFIG = config
    CONFIG_GENERATION += 1


PROVIDER_CREDENTIAL_SERVICE = ProviderCredentialService(
    env_config=ENV_CONFIG,
    database_manager=database_manager,
    database_lock=lambda: DB_LOCK,
    key_values=KEY_VALUE_REPOSITORY,
    apply_config=apply_runtime_config,
    garmin_connection=lambda: GARMIN_LOGIN.status(),
    current_config=lambda: CONFIG,
)


def refresh_runtime_config() -> app_config.Config:
    """Recompute CONFIG from the environment plus stored credentials."""
    return PROVIDER_CREDENTIAL_SERVICE.refresh()


# Each flush rewrites the whole capture (at most 2 MiB), so captures are merged
# on a timer and written as background work that yields to Coach and athlete writes.
DIAGNOSTIC_CAPTURE_FLUSH_DELAY_SECONDS = 30.0
DIAGNOSTIC_CAPTURE = observability.DiagnosticCapture(
    lambda key: key_value_service().get(key),
    lambda key, value: key_value_service().set(key, value),
    REDACTOR,
    flush_delay_seconds=DIAGNOSTIC_CAPTURE_FLUSH_DELAY_SECONDS,
    timer_context=background_writer,
)
APP.diagnostic_capture = DIAGNOSTIC_CAPTURE

SYNC_PERSISTENCE = build_sync_persistence(APP)


def sync_state_repository() -> SyncStateRepository:
    """Return the sync state repository bound to the active database."""
    return SYNC_PERSISTENCE.state_repository()


def sync_daily_markers() -> DailySyncMarkerService:
    """Return the daily sync marker service bound to the active database."""
    return SYNC_PERSISTENCE.daily_markers()


GARMIN_TOKENS = GarminTokenStore(
    database_manager=database_manager,
    database_lock=lambda: DB_LOCK,
    key_values=KEY_VALUE_REPOSITORY,
    tokenstore_path=lambda: CONFIG.garmin_tokenstore,
    registry=GARMIN_SECRET_REGISTRY,
    env_credentials=lambda: bool(CONFIG.garmin_email and CONFIG.garmin_password),
)
GARMIN_LOGIN: GarminLoginService = GarminLoginService(
    config=lambda: CONFIG,
    client_factory=lambda email, password, **options: (
        GARMIN_ASSEMBLY.client_factory().create(email, password, **options)
    ),
    tokens=GARMIN_TOKENS,
    registry=GARMIN_SECRET_REGISTRY,
    on_connected=lambda: SYNC_SCHEDULERS.backfill_resumer().resume_provider(
        GARMIN_ID, requested_by="connection"
    ),
)
GARMIN_ASSEMBLY: GarminServices = build_garmin(
    APP,
    root=ROOT,
    earliest_date=SYNC_EARLIEST_DATE,
    sync_chunk_days=SYNC_CHUNK_DAYS,
    all_sync_days=ALL_SYNC_DAYS,
    sync_state_repository=sync_state_repository,
    daily_sync_markers=sync_daily_markers,
    resync_gate=GARMIN_RESYNC_GATE,
    lock_wait_seconds=GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS,
    metric_export=lambda: (
        METRIC_EXPORT.sync_automatic() if _intervals_export_configured() else None
    ),
    tokens=GARMIN_TOKENS,
    run_zones=lambda: RUN_LTHR.zones_resolver(),
)
APP.garmin = GARMIN_ASSEMBLY


SYNC_JOB_QUEUE = build_sync_job_queue(
    APP, all_sync_days=ALL_SYNC_DAYS, daily_sync_markers=sync_daily_markers
)
APP.sync_job_queue = SYNC_JOB_QUEUE

EXTERNAL_CALENDAR = ExternalCalendarAssembly(
    dependencies=ExternalCalendarAssembly.Inputs(
        owners=ExternalCalendarSyncOwners(
            config=lambda: CONFIG,
            database_manager=database_manager,
            key_values=KEY_VALUE_REPOSITORY,
            daily_markers=sync_daily_markers,
            adaptive_preview_service=lambda: (
                PLANNING_WORKFLOWS.adaptive_replan_preview_service()
            ),
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
            sync_lock=lambda: (
                external_calendar_runtime.shared_external_calendar_sync_lock()
            ),
        ),
    )
)
APP.external_calendar = EXTERNAL_CALENDAR


PROVIDER_TRANSPORT = build_provider_transport(
    app_version=APP_VERSION,
    logger=LOGGER,
    diagnostic_capture=DIAGNOSTIC_CAPTURE,
    redact_text=REDACTOR.redact_text,
    provider_state=provider_state_service,
    operation_context=sync_observation.operation_context,
    current_config=lambda: CONFIG,
    athlete_now=ATHLETE_CLOCK.now,
    intervals_operation=INTERVALS_RESYNC_GATE.operation,
)
APP.provider_transport = PROVIDER_TRANSPORT
WAHOO_CONNECTION = build_wahoo_connection(
    APP,
    secret_registry=WAHOO_SECRET_REGISTRY,
    on_connected=lambda: SYNC_SCHEDULERS.backfill_resumer().resume_provider(
        WAHOO_ID, requested_by="connection"
    ),
)


def observed_provider_opener(service: str, *, include_path: bool = True) -> Opener:
    """Observe a raw provider request in the log and the diagnostic capture."""
    return observed_opener(
        service,
        logger=LOGGER,
        diagnostic_capture=DIAGNOSTIC_CAPTURE,
        operation_context=sync_observation.operation_context,
        include_path=include_path,
    )


def disconnect_wahoo_grant() -> dict[str, object]:
    """Revoke the Wahoo grant best effort and drop its tokens (privacy purge)."""
    return WAHOO_CONNECTION.service().disconnect()


# The thresholds every outbound export sends (Intervals.icu metrics, Wahoo plan
# headers): local zones, then Garmin, then Wahoo, current on the athlete's today.
EXPORT_THRESHOLDS = export_thresholds_reader(
    lambda: CANONICAL_READ,
    source_preferences=lambda db: preferences_from_profile(
        ATHLETE_DATA.profile().get_from_db(db)
    ),
    today=lambda: ATHLETE_CLOCK.now().date(),
)
WAHOO_SYNC = build_wahoo_sync(
    APP,
    connection=WAHOO_CONNECTION.service,
    daily_markers=sync_daily_markers,
    resync_gate=WAHOO_RESYNC_GATE,
    export_thresholds=EXPORT_THRESHOLDS,
    history_earliest_date=SYNC_EARLIEST_DATE,
    fit_opener=lambda: observed_provider_opener(WAHOO_ID, include_path=False),
)
APP.settings = SETTINGS
NUTRITION_SERVICES: NutritionServices = build_nutrition(APP)
APP.nutrition = NUTRITION_SERVICES
MODEL_TRANSPORT: ModelTransportServices = build_model_transport(
    config=lambda: CONFIG,
    selected_thinking_level=SETTINGS.selected_thinking_level,
    service_tier=SETTINGS.service_tier,
    http_client=PROVIDER_TRANSPORT.json_http_client,
    provider_state=provider_state_service,
    read_value=lambda key: key_value_service().get(key),
    write_value=lambda key, value: key_value_service().set(key, value),
    logger=LOGGER,
    diagnostic_capture=DIAGNOSTIC_CAPTURE,
    app_version=APP_VERSION,
    max_audio_bytes=MAX_AUDIO_BODY_BYTES,
)
APP.model_transport = MODEL_TRANSPORT
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
        model_transport=MODEL_TRANSPORT,
        default_thinking_level=SETTINGS.selected_thinking_level,
        default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
        json_media_type=JSON_MEDIA_TYPE,
    ),
)
APP.coach_conversation = COACH_CONVERSATION
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
            observations=lambda: CANONICAL_READ,
        ),
    )
)
APP.coach_local = COACH_LOCAL
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
            run_lthr_for=lambda unit: RUN_LTHR.resolver()(unit),
            key_values=KEY_VALUE_REPOSITORY,
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
            wahoo_export=WAHOO_SYNC.workout_export,
            workout_library_service=PLANNING_DATA.workout_library,
            calendar_conflict_service=PLANNING_WORKFLOWS.calendar_conflict_service,
        ),
        state=WorkoutLibraryState(
            key_values=KEY_VALUE_REPOSITORY,
            event_buffer=runtime_events.STATE_EVENT_BUFFER,
            redactor=REDACTOR,
            utc_now=runtime_clock.utc_now,
            local_today=lambda: ATHLETE_CLOCK.now().date(),
            hr_cap_resync=lambda db, payloads: RUN_LTHR.resync(db, payloads),
        ),
        uuid_factory=uuid.uuid4,
    )
)
APP.workout_library_sync = WORKOUT_LIBRARY_SYNC
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
            provider_resync_gate=INTERVALS_RESYNC_GATE,
        ),
    )
)
WEATHER: WeatherServices = build_weather(APP)
APP.weather = WEATHER
WEATHER_SYNC = build_weather_sync(APP, WEATHER)

COACH_CONTEXT = CoachContextAssembly(
    dependencies=CoachContextAssembly.Inputs(
        performance=CoachContextPerformanceSources(
            weather_service=WEATHER.service,
            garmin_payload_service=GARMIN_ASSEMBLY.payload_service,
            garmin_projection_service=GARMIN_ASSEMBLY.projection_service,
            activity_feedback_service=ATHLETE_DATA.activity_feedback,
            today=lambda: ATHLETE_CLOCK.now().date(),
            local_date=lambda: ATHLETE_CLOCK.now().date(),
            utc_now=lambda: datetime.now(UTC),
            canonical=CanonicalPerformanceSource(
                database_manager=lambda: database_manager(),
                observation_reader=lambda: CANONICAL_READ,
                serving=lambda: CANONICAL_READ,
                activity_summaries=lambda: CANONICAL_READ,
                coverage=lambda: CANONICAL_READ,
                source_preferences=lambda db: preferences_from_profile(
                    ATHLETE_DATA.profile().get_from_db(db)
                ),
            ),
            activity_rows=ActivitySummarySource(
                database_manager=lambda: database_manager(),
                reader=lambda: CANONICAL_READ,
                coverage=lambda: CANONICAL_READ,
            ),
            zone_configurations=lambda: ATHLETE_DATA.zones().configurations(),
            threshold_warnings=lambda: THRESHOLD_WARNINGS.read(),
            first_threshold_estimate=lambda: ATHLETE_DATA.first_threshold().estimate(),
            lt1_session_records=lambda days: (
                PERFORMANCE.training_reports().profiles.curve_records(days)
            ),
        ),
        planning=CoachContextPlanningSources(
            checkin_service=ATHLETE_DATA.checkin,
            planned_unit_service=PLANNING_DATA.planned_unit,
            daily_context_service=PLANNING_WORKFLOWS.daily_planning_context_service,
            external_calendar_reader=EXTERNAL_CALENDAR.reader,
            competition_service=PLANNING_DATA.competition,
            training_plan_service=PLANNING_DATA.training_plan,
            adaptive_preview_service=lambda: (
                PLANNING_WORKFLOWS.adaptive_replan_preview_service()
            ),
            workout_library_service=PLANNING_DATA.workout_library,
            nutrition_meal_library=NUTRITION_SERVICES.meal_library_service,
            planning_brief=lambda: PLAN_GUARD.plan_guard_service().brief(),
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
            default_max_output_tokens=lambda: (
                coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS
            ),
        ),
    )
)
COACH_READ_TOOLS = CoachReadToolsAssembly(
    dependencies=CoachReadToolsAssembly.Inputs(
        activity=CoachActivityReadSources(
            activity_read_service=ACTIVITY_READS.activity_read,
            garmin_payload_service=GARMIN_ASSEMBLY.payload_service,
            profile_service=ATHLETE_DATA.profile,
            today=lambda: ATHLETE_CLOCK.now().date(),
            report_services=PERFORMANCE.training_reports,
            session_corrections=ATHLETE_DATA.session_corrections,
        ),
        planning=CoachPlanningReadSources(
            structured_training_state_service=PLANNING_WORKFLOWS.structured_training_state_service,
            workout_library_service=PLANNING_DATA.workout_library,
            planned_unit_service=PLANNING_DATA.planned_unit,
            unit_thresholds=PLAN_GUARD.planned_unit_estimator,
            change_history_service=HISTORY.change_history_service,
            competition_service=PLANNING_DATA.competition,
            training_plan_service=PLANNING_DATA.training_plan,
        ),
        policy=CoachReadToolPolicy(
            nutrition_diary=NUTRITION_SERVICES.diary_service,
            nutrition_meal_library=NUTRITION_SERVICES.meal_library_service,
            training_change_limit=lambda: coach_limits.COACH_TRAINING_CHANGE_LIMIT,
            context_service=COACH_CONTEXT.structured_context_service,
        ),
    )
)
COACH_PROPOSALS = CoachProposalAssembly(
    dependencies=CoachProposalAssembly.Inputs(
        persistence=ProposalPersistence(
            database_manager=database_manager,
            nutrition_diary_service=NUTRITION_SERVICES.diary_service,
        ),
        execution=ProposalExecutionOwners(
            history_undo_service=HISTORY.undo_service,
            intervals_client_factory=PROVIDER_TRANSPORT.intervals_client,
            maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
            tool_dispatch_service=lambda: COACH_TOOL_DISPATCH.service(),
        ),
        clock=ProposalClock(
            now=lambda: time.time(),
            utc_now=runtime_clock.utc_now,
            uuid_factory=uuid.uuid4,
            today=lambda: ATHLETE_CLOCK.now().date(),
        ),
    )
)

# Derived passes (local load, canonical backfill, Wahoo metric export) after any
# provider read: a queued job, a Coach request that waits and a full resync.
DERIVED_PASS_HOOK = chained_after_job(
    refresh_after_job(lambda: start_canonical_backfill()),
    lambda job: METRIC_EXPORT_RUNNER.after_job(job),
)

PROVIDER_RESYNC = ProviderResyncAssembly(
    dependencies=ProviderResyncAssembly.Inputs(
        competition=CompetitionSyncOwners(
            config=lambda: CONFIG,
            intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
            competition_service=PLANNING_DATA.competition,
        ),
        resync=ResyncProviderOwners(
            garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
            garmin_resync_gate=GARMIN_RESYNC_GATE,
            wahoo_sync_service=WAHOO_SYNC.sync_service,
            wahoo_resync_gate=WAHOO_RESYNC_GATE,
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
            after_resync=DERIVED_PASS_HOOK,
        ),
    ),
)


# Shared by the executor, scheduler, Coach refreshes and configured checks.
SYNC_JOB_DEPENDENCIES = SyncJobExecutionAssembly.Inputs(
    historical=HistoricalSyncDependencies(
        local_now=ATHLETE_CLOCK.now,
        sync_period_defaults=SYNC_PERIOD_DEFAULTS,
        all_sync_days=ALL_SYNC_DAYS,
        sync_chunk_days=SYNC_CHUNK_DAYS,
        sync_earliest_date=SYNC_EARLIEST_DATE,
    ),
    state=SyncJobStateDependencies(
        sync_state_repository=sync_state_repository,
        queue_service=SYNC_JOB_QUEUE.service,
        outcome_service=SYNC_JOB_QUEUE.outcome_service,
    ),
    intervals=IntervalsJobDependencies(
        selected_workout_sync_service=SELECTED_WORKOUT_SYNC.service,
        competition_sync_service=PROVIDER_RESYNC.competition_sync_service,
        nutrition_sync_service=NUTRITION_SERVICES.intervals_sync_service,
        operation_observer=PROVIDER_SYNC.operation_observer,
        resync_gate=INTERVALS_RESYNC_GATE,
    ),
    garmin=GarminJobDependencies(
        sync_service=GARMIN_ASSEMBLY.sync_service,
        morning_body_battery_service=morning_body_battery_service,
        fixture_loader=GARMIN_ASSEMBLY.fixture_loader,
        activity_detail_service=GARMIN_ASSEMBLY.activity_detail_service,
        strength_push_service=GARMIN_ASSEMBLY.strength_push_service,
        wellness_history_service=GARMIN_ASSEMBLY.wellness_history_service,
        stream_backfill_service=GARMIN_ASSEMBLY.stream_backfill_service,
        change_check=GARMIN_ASSEMBLY.change_check,
    ),
    calendar_weather=CalendarWeatherJobDependencies(
        calendar_sync_service=EXTERNAL_CALENDAR.sync_service,
        weather_sync_service=WEATHER_SYNC,
    ),
    wahoo=WahooJobDependencies(
        sync_service=WAHOO_SYNC.sync_service,
        plan_push_service=WAHOO_SYNC.plan_push_service,
        resync_gate=WAHOO_RESYNC_GATE,
        stream_backfill_service=WAHOO_SYNC.stream_backfill_service,
    ),
)

PROVIDER_CONFIGURED: dict[str, Callable[[], bool]] = provider_configured_checks(
    SYNC_JOB_DEPENDENCIES, config=lambda: CONFIG, profile=ATHLETE_DATA.profile
)

SYNC_JOB_EXECUTION = SyncJobExecutionAssembly(
    dependencies=SYNC_JOB_DEPENDENCIES,
    after_job=DERIVED_PASS_HOOK,
)


SYNC_WORKERS = build_sync_worker(APP, executor=SYNC_JOB_EXECUTION.executor)


# The daily schedule follows the history's next_retry_at; an auth failure waits
# for the athlete (manual refresh, restart or changed credentials).
PROVIDER_RETRY_HOLD = ProviderRetryHold(
    lambda: database_manager(),
    lambda: datetime.now(UTC),
    credential_keys={
        GARMIN_ID: (
            PROVIDER_CREDENTIALS_KEY,
            GARMIN_TOKENS_KEY,
            GARMIN_TOKENSTORE_STATE_KEY,
        ),
        WAHOO_ID: (PROVIDER_CREDENTIALS_KEY, WAHOO_TOKENS_KEY),
    },
)

SYNC_SCHEDULERS: SyncSchedulerAssembly = SyncSchedulerAssembly(
    dependencies=SyncSchedulerAssembly.Inputs(
        owners=SyncScheduleOwners(
            profile_service=ATHLETE_DATA.profile,
            queue_service=SYNC_JOB_QUEUE.service,
            daily_sync_marker_service=sync_daily_markers,
            garmin_sync_service=GARMIN_ASSEMBLY.sync_service,
        ),
        persistence=SyncSchedulePersistence(
            sync_state_repository=sync_state_repository,
            retry_held=PROVIDER_RETRY_HOLD.held,
        ),
        controls=SyncScheduleControls(
            maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
            sleep=time.sleep,
        ),
        policy=SyncSchedulePolicy(
            config=lambda: CONFIG,
            garmin_automatic_sync_days=GARMIN_AUTOMATIC_SYNC_DAYS,
            auto_update_label=sync_scheduler_runtime.AUTO_UPDATE_LABEL,
            sync_chunk_days=SYNC_CHUNK_DAYS,
            sync_earliest_date=SYNC_EARLIEST_DATE,
        ),
        daily_loop=DailySyncLoopSettings(
            morning_body_battery_service=morning_body_battery_service,
            logger=LOGGER,
            database_manager=database_manager,
            morning_due=lambda: GARMIN_ASSEMBLY.change_check().morning_due(),
        ),
        providers=SyncScheduleProviders(
            garmin_resync_gate=GARMIN_RESYNC_GATE,
            weather_refresh_due=lambda: WEATHER_SYNC().refresh_due(),
            wahoo=SYNC_JOB_DEPENDENCIES.wahoo,
            sync_period_defaults=SYNC_PERIOD_DEFAULTS,
            all_sync_days=ALL_SYNC_DAYS,
            garmin_change_check=GARMIN_ASSEMBLY.change_check,
        ),
    ),
)

SYNC_COMMANDS = build_sync_commands(
    APP,
    intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
    synchronous_refreshes=lambda: coach_synchronous_refreshes(SYNC_JOB_DEPENDENCIES),
    after_refresh=DERIVED_PASS_HOOK,
    training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
)


CHAT_PAGE_MAX = 100


(
    COACH_CANONICAL_TOOL_NAMES,
    COACH_STRUCTURED_TOOLS,
    STRUCTURED_READ_ONLY_TOOLS,
    COACH_DIALOGUE_TOOLS,
    COACH_TOOL_CAPABILITIES,
) = build_tool_contracts(
    default_profile=DEFAULT_PROFILE,
    checkin_text_limits=CHECKIN_TEXT_LIMITS,
    checkin_score_fields=CHECKIN_SCORE_FIELDS,
    training_change_limit=coach_limits.COACH_TRAINING_CHANGE_LIMIT,
    library_bulk_max_entries=planning_library.LIBRARY_BULK_MAX_ENTRIES,
    training_plan_statuses=planning_training_plans.TRAINING_PLAN_STATUSES,
    dialogue_tools=dialogue_tools,
)
APP.coach_dialogue_tools = COACH_DIALOGUE_TOOLS


RUN_LTHR = RunLthr(
    thresholds=lambda: read_load_thresholds(
        database_manager(),
        CANONICAL_READ,
        ATHLETE_CLOCK.now().date(),
        ATHLETE_DATA.zones().configurations(),
        lambda db: preferences_from_profile(ATHLETE_DATA.profile().get_from_db(db)),
    ),
    today=lambda: ATHLETE_CLOCK.now().date(),
    key_values=KEY_VALUE_REPOSITORY,
)
APP.run_lthr = RUN_LTHR


COACH_PLANNING_TOOLS = CoachPlanningToolsAssembly(
    dependencies=CoachPlanningToolsAssembly.Inputs(
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
            adaptive_preview_service=lambda: (
                PLANNING_WORKFLOWS.adaptive_replan_preview_service()
            ),
            illness_pause_sync_service=SYNC_COMMANDS.illness_pause,
            plan_guard=PLAN_GUARD.plan_guard_service,
        ),
    )
)


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
    ),
    sync_provider=CoachSyncProvider(
        intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
    ),
    athlete_tools=CoachAthleteToolFactories(
        checkin_service=lambda: ATHLETE_DATA.checkin(),
        activity_feedback_service=lambda: ATHLETE_DATA.activity_feedback(),
        competition_service=lambda: PLANNING_DATA.competition(),
        nutrition_diary_service=NUTRITION_SERVICES.diary_service,
        nutrition_meal_library_service=NUTRITION_SERVICES.meal_library_service,
        equipment_service=ATHLETE_DATA.equipment,
        session_corrections_service=ATHLETE_DATA.session_corrections,
    ),
    profile_tools=CoachProfileToolDependencies(
        profile_service=lambda: ATHLETE_DATA.profile(),
        database_manager=lambda: database_manager(),
        database_lock=DB_LOCK,
    ),
)


COACH_TOOL_DISPATCH = CoachToolDispatchAssembly(
    dependencies=CoachToolDispatchAssembly.Inputs(
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
    )
)


COACH_TOOL_ROUNDS = CoachStructuredToolRoundAssembly(
    dependencies=CoachStructuredToolRoundAssembly.Inputs(
        runtime=StructuredToolRoundRuntime(
            database_manager=lambda: database_manager(),
            database_lock=DB_LOCK,
            profile_mutation_coordinator=PROFILE_MUTATION_COORDINATOR,
            key_value_repository=KEY_VALUE_REPOSITORY,
            root=ROOT,
            logger=LOGGER,
        ),
        contract=StructuredToolRoundContract(
            tool_names=lambda: (tool["name"] for tool in COACH_DIALOGUE_TOOLS),
            read_only_tools=lambda: STRUCTURED_READ_ONLY_TOOLS,
            limits=lambda: CoachStructuredToolRoundLimits(
                max_rounds=structured_tool_round.COACH_TOOL_MAX_ROUNDS,
                background_horizon_days=coach_limits.COACH_BACKGROUND_HORIZON_DAYS,
                default_max_output_tokens=coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
                long_plan_max_output_tokens=coach_limits.COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
            ),
        ),
        services=StructuredToolRoundServices(
            clarification_service=COACH_LOCAL.clarification_service,
            training_patch_service=lambda: (
                COACH_PLANNING_TOOLS.training_patch_service()
            ),
            proposal_creation_service=lambda: COACH_PROPOSALS.creation_service(),
            tool_dispatch_service=lambda: COACH_TOOL_DISPATCH.service(),
            dialogue_action_service=COACH_LOCAL.dialogue_action_service,
            planning_authority_service=SYNC_COMMANDS.authority,
            plan_guard_service=PLAN_GUARD.plan_guard_service,
        ),
        state=StructuredToolRoundState(
            job_store=lambda: COACH_BACKGROUND_JOBS.job_store(),
        ),
        conversation=StructuredToolRoundConversation(
            training_context_service=lambda: COACH_CONTEXT.training_context_service(),
            response_service=lambda: COACH_TURNS.structured_response_service(),
            response_transport=lambda: COACH_CONVERSATION.response_transport(),
        ),
    )
)


COACH_BACKGROUND_JOBS = CoachBackgroundJobsAssembly(
    dependencies=CoachBackgroundJobsAssembly.Inputs(
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
            max_attachment_storage_bytes=lambda: (
                coach_attachments.MAX_ATTACHMENT_STORAGE_BYTES
            ),
        ),
    )
)
APP.coach_background_jobs = COACH_BACKGROUND_JOBS


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
            attachment_context_service=lambda: (
                COACH_CONVERSATION.attachment_context_service()
            ),
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


PUBLIC_STATE: PublicStateAssembly = PublicStateAssembly(
    dependencies=PublicStateAssembly.Inputs(
        core=PublicStateCoreInputs(
            database_manager=lambda: database_manager(),
            database_lock=lambda: DB_LOCK,
            config=lambda: CONFIG,
            settings=lambda: SETTINGS,
            maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
            app_name=APP_NAME,
            app_version=APP_VERSION,
            key_values=lambda: KEY_VALUE_REPOSITORY,
            key_value_service=key_value_service,
            observation_reader=lambda: CANONICAL_READ,
            canonical_serving=lambda: CANONICAL_READ,
            activity_summary_reader=lambda: CANONICAL_READ,
            coverage=lambda: CANONICAL_READ,
        ),
        owners=PublicStateOwnerAssemblies(
            sync_persistence=lambda: SYNC_PERSISTENCE,
            planning_data=lambda: PLANNING_DATA,
            athlete_data=lambda: ATHLETE_DATA,
            external_calendar=lambda: EXTERNAL_CALENDAR,
            provider_sync=lambda: PROVIDER_SYNC,
            garmin=lambda: GARMIN_ASSEMBLY,
            sync_job_queue=lambda: SYNC_JOB_QUEUE,
        ),
        projections=PublicStateProjectionOwners(
            weather=lambda: WEATHER,
            workout_library_sync=lambda: WORKOUT_LIBRARY_SYNC,
            provider_resync=lambda: PROVIDER_RESYNC,
            coach_conversation=lambda: COACH_CONVERSATION,
            calendar_local=lambda: calendar_local,
            planning_season=lambda: planning_season,
            intervals_state=lambda: intervals_state,
            diagnostic_capture=lambda: DIAGNOSTIC_CAPTURE,
        ),
        operations=PublicStateOperationalServices(
            workout_library_sync_running=lambda: workout_library_sync_running,
            daily_planning_context_service=PLANNING_WORKFLOWS.daily_planning_context_service,
            adaptive_preview_followup_service=lambda: AdaptivePreviewFollowupService(
                PLANNING_WORKFLOWS.adaptive_replan_preview_service(), LOGGER
            ),
            adaptive_replan_preview_service=PLANNING_WORKFLOWS.adaptive_replan_preview_service,
            morning_checkin_state_service=COACH_LOCAL.morning_checkin_state_service,
            coach_quick_actions_service=COACH_LOCAL.quick_actions_service,
            provider_state_service=provider_state_service,
        ),
        calendar=PublicStateCalendarSettings(
            local_date=lambda: ATHLETE_CLOCK.now().date(),
            local_now=lambda: ATHLETE_CLOCK.now,
            external_calendar_window_days=lambda: (
                calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS
            ),
            sync_period_defaults=lambda: SYNC_PERIOD_DEFAULTS,
            all_sync_days=lambda: ALL_SYNC_DAYS,
            planned_workout_label=lambda: PLANNED_WORKOUT_LABEL,
        ),
    ),
    provider_credentials=lambda: PROVIDER_CREDENTIAL_SERVICE,
    running_probes={WAHOO_ID: lambda: WAHOO_SYNC.sync_service().running()},
)

CANONICAL_READ = build_canonical_read(
    key_values=KEY_VALUE_REPOSITORY,
    profile=ATHLETE_PROFILE_SERVICE,
)
APP.canonical_read = CANONICAL_READ
METRIC_EXPORT: MetricExportService = build_metric_export_service(
    database_manager,
    lambda: CANONICAL_READ,
    database_lock=DB_LOCK,
    intervals_client=lambda: PROVIDER_TRANSPORT.intervals_client(),
    thresholds=EXPORT_THRESHOLDS,
    today=lambda: ATHLETE_CLOCK.now().date(),
    utc_now=lambda: datetime.now(UTC),
)


def _intervals_export_configured() -> bool:
    return bool(CONFIG.intervals_api_key and CONFIG.intervals_athlete_id)


METRIC_EXPORT_RUNNER = MetricExportRunner(
    lambda: METRIC_EXPORT,
    enabled=_intervals_export_configured,
    maintenance_gate=lambda: runtime_maintenance.MAINTENANCE_GATE,
)
THRESHOLD_WARNINGS = ThresholdStalenessService(
    database_manager,
    lambda: CANONICAL_READ,
    lambda: ATHLETE_CLOCK.now().date(),
    zone_configurations=CanonicalTableReader().zone_configurations,
    preferences=lambda db: preferences_from_profile(
        ATHLETE_DATA.profile().get_from_db(db)
    ),
    sdk_failure=lambda: GARMIN_ASSEMBLY.sync_service().sdk_threshold_failure(),
)


SESSION_FOCUS_BACKFILL = SessionFocusBackfill(
    key_values=KEY_VALUE_REPOSITORY,
    clock=runtime_clock.utc_now,
    future_units=lambda limit: PLANNING_DATA.planned_unit().list(
        limit, future_only=True
    ),
    estimator=PLAN_GUARD.planned_unit_estimator,
    update_unit=lambda *args, **kwargs: PLANNING_DATA.planned_unit().update(
        *args, **kwargs
    ),
    bump_planning_revision=PLANNING_REVISION_SERVICE.bump,
    database_manager=database_manager,
    publish_change=lambda: runtime_events.STATE_EVENT_BUFFER.publish(
        "coach", {"status": "changed"}
    ),
)

PROFILE_WEEKLY_PLAN_REMOVAL = ProfileWeeklyPlanRemoval(
    key_values=KEY_VALUE_REPOSITORY, clock=runtime_clock.utc_now
)

RATING_BACKFILL_REMOVAL = RatingBackfillRemoval(
    key_values=KEY_VALUE_REPOSITORY, clock=runtime_clock.utc_now
)

SESSION_REBUNDLE = SessionRebundle(
    key_values=KEY_VALUE_REPOSITORY,
    clock=runtime_clock.utc_now,
    zone_provider=lambda: ATHLETE_CLOCK.now().tzinfo,
    database_manager=database_manager,
)

CANONICAL_BACKFILL = build_canonical_backfill(
    database=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    zone_provider=lambda: ATHLETE_CLOCK.now().tzinfo,
    maintenance_gate=runtime_maintenance.MAINTENANCE_GATE,
    clock=runtime_clock.utc_now,
    source_preferences=lambda db: preferences_from_profile(
        ATHLETE_DATA.profile().get_from_db(db)
    ),
    # Strength sessions read their session RPE (card M6 v2).
    session_feedback=lambda keys: ATHLETE_DATA.activity_feedback().for_activity_ids(
        keys, sessions_only=True
    ),
    # Session analyses freeze matched planned targets (#1685).
    planned_units=lambda: PLANNING_DATA.planned_unit().list(500),
    # The heart-rate branch's TRIMP constants follow the profile sex (M6 v3).
    athlete_sex=lambda db: ATHLETE_DATA.profile().get_from_db(db).get("sex"),
    # The one-time focus backfill of future units (#1849) runs after all stages.
    extra_followups=(
        PROFILE_WEEKLY_PLAN_REMOVAL,
        RATING_BACKFILL_REMOVAL,
        SESSION_REBUNDLE,
        SESSION_FOCUS_BACKFILL,
    ),
    # Weather during outdoor sessions (#1868); only 2-decimal coordinates leave.
    activity_weather_fetch=lambda *position: (
        activity_weather_provider.ActivityWeatherClient(
            PROVIDER_TRANSPORT.json_http_client().request
        ).fetch(*position)
    ),
    home_location=lambda db: home_coordinates(
        KEY_VALUE_REPOSITORY,
        db,
        ATHLETE_DATA.profile().get_from_db(db).get("weather_location", ""),
    ),
)
APP.canonical_backfill = CANONICAL_BACKFILL

DIAGNOSTICS = build_diagnostics(APP)


PROVIDER_CONNECTION_CHECKS = ProviderConnectionChecks(
    build_connection_probes(
        config=lambda: CONFIG,
        request=lambda *args, **kwargs: PROVIDER_TRANSPORT.json_http_client().request(
            *args, **kwargs
        ),
        default_openai_base_url=DEFAULT_OPENAI_BASE_URL,
        default_anthropic_base_url=DEFAULT_ANTHROPIC_BASE_URL,
        intervals_get=lambda path: PROVIDER_TRANSPORT.intervals_client().get(path),
        wahoo_status=lambda: WAHOO_CONNECTION.service().status(),
        wahoo_user=lambda: WAHOO_SYNC.client().user(),
        garmin_connected=lambda: GARMIN_TOKENS.source() == GARMIN_SOURCE_DB,
        garmin_fingerprint=GARMIN_TOKENS.fingerprint,
        garmin_login=lambda: GARMIN_ASSEMBLY.check_stored_login(),
    ),
    operation=lambda: runtime_maintenance.MAINTENANCE_GATE.operation(),
)
HTTP_API = HttpApiAssembly(
    dependencies=HttpApiAssembly.Inputs(
        core=HttpCoreAndTransport(
            services=HttpCoreServices(
                resources=HttpCoreResources(
                    database_manager=lambda: database_manager(),
                    database_lock=lambda: DB_LOCK,
                    data_dir=lambda: DATA_DIR,
                    readiness_maintenance_gate=lambda: (
                        runtime_maintenance.MAINTENANCE_GATE
                    ),
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
                    proposal_confirmation_service=COACH_PROPOSALS.confirmation_service,
                    proposal_execution_service=COACH_PROPOSALS.execution_service,
                    reset_service=COACH_CONVERSATION.reset_service,
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
                activity_read=ACTIVITY_READS.activity_read,
                equipment=ATHLETE_DATA.equipment,
                activity_routes=lambda: ACTIVITY_ROUTES,
                activity_feedback=ATHLETE_DATA.activity_feedback,
                session_corrections=ATHLETE_DATA.session_corrections,
                zones=ATHLETE_DATA.zones,
                first_threshold=ATHLETE_DATA.first_threshold,
                body_export=lambda profile, revision, deadline: (
                    GARMIN_ASSEMBLY.body_export(ATHLETE_DATA.profile()).export(
                        profile, revision, deadline
                    )
                ),
                clock=ATHLETE_CLOCK,
                local_today=lambda: ATHLETE_CLOCK.now().date(),
                state_event_buffer=runtime_events.STATE_EVENT_BUFFER,
            ),
            diagnostics=HttpDiagnosticsServices(
                recent_logs=DIAGNOSTICS.recent_log_entries_service,
                report=DIAGNOSTICS.report_service,
            ),
            history=HttpHistoryServices(
                undo=HISTORY.undo_service,
            ),
            workout_library=PLANNING_DATA.workout_library,
            planned_unit=PLANNING_DATA.planned_unit,
            training_reports=PERFORMANCE.training_reports,
            wahoo_library_state=WAHOO_SYNC.library_state,
        ),
        domains=HttpDomainRouteServices(
            privacy=HttpPrivacyServices(
                backup=BACKUP.backup_service,
                export=PRIVACY.archive_export_service,
                delete=PRIVACY.delete_service,
                restore=BACKUP.restore_service,
                max_backup_bytes=MAX_BACKUP_BYTES,
            ),
            sync=HttpSyncServices(
                job_queue=SYNC_JOB_QUEUE.service,
                state_repository=sync_state_repository,
                garmin_analysis_refresh=GARMIN_ASSEMBLY.analysis_refresh_service,
                wahoo_sync=WAHOO_SYNC.sync_service,
                full_resync=PROVIDER_RESYNC.full_resync_service,
                provider_configured=lambda provider_id: PROVIDER_CONFIGURED[
                    provider_id
                ](),
                period_defaults=SYNC_PERIOD_DEFAULTS,
                all_sync_days=ALL_SYNC_DAYS,
                uuid_factory=lambda: uuid.uuid4().hex,
            ),
            nutrition=HttpNutritionServices(
                diary=NUTRITION_SERVICES.diary_service,
                meal_library=NUTRITION_SERVICES.meal_library_service,
                intervals_sync=NUTRITION_SERVICES.intervals_sync_service,
                audio_transcription=MODEL_TRANSPORT.audio_transcription_client,
                refresh=GARMIN_ASSEMBLY.nutrition_refresh_service,
            ),
            wahoo=WAHOO_CONNECTION.service,
            metric_export=lambda: METRIC_EXPORT,
            provider_credentials=PROVIDER_CREDENTIAL_SERVICE,
            garmin_login=lambda: GARMIN_LOGIN,
            connection_checks=lambda: PROVIDER_CONNECTION_CHECKS,
        ),
    ),
)


def main() -> None:
    observability.configure_logging(LOGGER, DATA_DIR, LOG_PATH, REDACTOR)
    configuration_error = app_config.security_configuration_error(
        CONFIG, sqlcipher_available=SQLCIPHER_AVAILABLE
    )
    if configuration_error:
        LOGGER.critical(
            "Secure startup refused",
            extra={
                "event": "secure_startup_refused",
                "context": {"reason": configuration_error},
            },
        )
        raise SystemExit(configuration_error)
    storage_warning = app_config.data_dir_env_warning(DATA_DIR)
    if storage_warning:
        LOGGER.warning(
            "APP_PASSWORD stored in the data directory",
            extra={
                "event": "app_password_in_data_dir",
                "context": {"reason": storage_warning},
            },
        )
    proxy_warning = app_config.proxy_list_warning(CONFIG.invalid_trusted_proxies)
    if proxy_warning:
        LOGGER.warning(
            "Invalid trusted proxy entries ignored",
            extra={
                "event": "config_invalid_trusted_proxy",
                "context": {"setting": "TRUSTED_PROXY_IPS", "reason": proxy_warning},
            },
        )
    LOGGER.info(
        f"{APP_NAME} starting",
        extra={
            "event": "server_start",
            "context": {"version": APP_VERSION, "port": CONFIG.port},
        },
    )
    initialise_database()
    remove_orphaned_staging_files(DATA_DIR, LOGGER)
    server = http_server.CoachHTTPServer(
        ("0.0.0.0", CONFIG.port), HTTP_API.request_handler_class()
    )
    server.allow_reuse_address = True
    sync_worker: sync_worker_runtime.SyncJobWorker | None = None
    daily_loop: sync_scheduler_runtime.DailySyncLoop | None = None
    daily_thread: threading.Thread | None = None
    # `docker stop` sends SIGTERM; shut down like Ctrl+C so pending work is written.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    # `docker kill -s USR1` writes every thread's stack (code locations only, no
    # values) to stderr, so a stalled server can be diagnosed before a restart.
    if sys.platform != "win32":
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    try:
        WORKOUT_LIBRARY_SYNC.sync_state_service().reset_interrupted()
        SYNC_JOB_QUEUE.service().resume_interrupted()
        COACH_BACKGROUND_JOBS.job_store().resume_interrupted(
            COACH_BACKGROUND_JOBS.turn_failure_service()
        )
        # The startup writes on this thread come before any worker that can start
        # the canonical backfill (a finished sync job does): a batch holding the
        # writer must not fail startup with DatabaseBusyError (#2287).
        SYNC_SCHEDULERS.startup_scheduler().schedule()
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
        CANONICAL_BACKFILL.worker.start()
        daily_loop = SYNC_SCHEDULERS.daily_loop()
        daily_thread = threading.Thread(target=daily_loop.run, daemon=True)
        daily_thread.start()
        LOGGER.info(
            f"{APP_NAME} listening",
            extra={"event": "server_ready", "context": {"port": CONFIG.port}},
        )
        server.serve_forever()  # NOSONAR - HTTP is intentionally LAN-only behind the documented HTTPS proxy.
    except KeyboardInterrupt:
        pass
    finally:
        if daily_loop is not None:
            daily_loop.stop()
        if sync_worker is not None:
            sync_worker.stop()
        COACH_JOB_WORKER.stop()
        CANONICAL_BACKFILL.worker.stop()
        METRIC_EXPORT_RUNNER.stop()
        server.server_close()
        DIAGNOSTIC_CAPTURE.close()
        if daily_thread is not None:
            daily_thread.join(timeout=5)
        if sync_worker is not None:
            sync_worker.join(timeout=5)
        COACH_JOB_WORKER.join(timeout=5)
        CANONICAL_BACKFILL.worker.join(timeout=5)
        METRIC_EXPORT_RUNNER.join(timeout=5)
        DIAGNOSTIC_CAPTURE.flush()


if __name__ == "__main__":
    main()
