from __future__ import annotations

import faulthandler
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
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
from backend.backup.staging_sweep import remove_orphaned_staging_files
from backend.backup.wiring import build_backup
from backend.canonical.vocabulary import GARMIN_ID, WAHOO_ID
from backend.coach import limits as coach_limits
from backend.coach.conversation_gate import CoachConversationGate
from backend.coach.dialogue import dialogue_tools
from backend.coach.job_worker import COACH_JOB_WORKER
from backend.coach.tool_registry import build_tool_contracts
from backend.coach.tool_wiring import (
    build_coach_command_tools,
    build_coach_planning_tools,
    build_coach_tool_dispatch,
    build_coach_tool_rounds,
)
from backend.coach.turn_wiring import build_coach_background_jobs, build_coach_turns
from backend.coach.wiring import (
    build_coach_context,
    build_coach_conversation,
    build_coach_local,
    build_coach_proposals,
    build_coach_read_tools,
)
from backend.config import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_OPENAI_BASE_URL,
    ConfigHolder,
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
    DatabaseHolder,
    background_writer,
)
from backend.db.repositories import (
    ActivityFeedbackRepository,
    ChatRepository,
    KeyValueRepository,
    PlanAdjustmentRepository,
    PlanningStateRepository,
    TrainingPlanRepository,
)
from backend.db.schema import configure_cipher
from backend.diagnostics.wiring import DiagnosticsServices, build_diagnostics
from backend.history.wiring import build_history
from backend.http_api import server as http_server
from backend.http_api.auth import (
    SessionAuthService,
    get_session_auth_service,
)
from backend.http_api.wiring import (
    PublicStateServices,
    build_http_api,
    build_public_state,
)
from backend.nutrition.wiring import NutritionServices, build_nutrition
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
from backend.performance.wiring import (
    build_activity_reads,
    build_athlete_data,
    build_performance,
)
from backend.planning import library as planning_library
from backend.planning import training_plans as planning_training_plans
from backend.planning.block_review import block_review, last_completed_test
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
    OPENAI_RESPONSE_TIMEOUT_SECONDS,
    ModelTransportServices,
    build_model_transport,
)
from backend.providers.transport_wiring import (
    ProviderTransportServices,
    build_provider_transport,
)
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.runtime import maintenance as runtime_maintenance
from backend.settings import SettingsService
from backend.sync import observation as sync_observation
from backend.sync import scheduler as sync_scheduler_runtime
from backend.sync import worker as sync_worker_runtime
from backend.sync.canonical_read_selector import CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.canonical_wiring import (
    CanonicalBackfillServices,
    build_canonical_backfill,
    build_canonical_read,
)
from backend.sync.daily import DailySyncMarkerService
from backend.sync.execution_wiring import (
    build_sync_job_execution,
    configured_for_job,
    provider_configured_checks,
)
from backend.sync.executor import chained_after_job
from backend.sync.flow_wiring import (
    build_export_thresholds,
    build_external_calendar,
    build_metric_export,
    build_planned_calendar_sync,
    build_planned_unit_sync,
    build_selected_workout_sync,
    build_workout_library_sync,
)
from backend.sync.full_resync import PROVIDER_RESYNC_KEYS
from backend.sync.garmin_login import (
    GarminLoginService,
    GarminSecretRegistry,
    GarminTokenStore,
)
from backend.sync.garmin_service import (
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
from backend.sync.local_load import refresh_after_job
from backend.sync.metric_export import MetricExportService
from backend.sync.metric_export_runner import MetricExportRunner
from backend.sync.profile_weekly_plan_removal import ProfileWeeklyPlanRemoval
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.rating_backfill_removal import RatingBackfillRemoval
from backend.sync.resync_wiring import build_provider_resync
from backend.sync.retry_hold import ProviderRetryHold
from backend.sync.scheduler_wiring import SyncSchedulerServices, build_sync_schedulers
from backend.sync.session_focus_backfill import SessionFocusBackfill
from backend.sync.session_rebundle import SessionRebundle
from backend.sync.state import SyncStateRepository
from backend.sync.wahoo_connection import WahooSecretRegistry
from backend.sync.wahoo_wiring import (
    WahooConnectionServices,
    build_wahoo_connection,
    build_wahoo_sync,
)
from backend.sync.weather import build_weather_sync
from backend.sync.wiring import (
    SyncWindow,
    build_provider_sync,
    build_sync_commands,
    build_sync_job_queue,
    build_sync_persistence,
    build_sync_worker,
    coach_synchronous_refreshes,
)
from backend.weather.activity_weather_store import home_coordinates
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
APP_VERSION = "2.1.11"
MAX_BODY_BYTES = 1_000_000
MAX_AUDIO_BODY_BYTES = 8_000_000
COACH_CONVERSATION_GATE = CoachConversationGate()


ENV_CONFIG = load_config(ROOT, DATA_DIR)
# Runtime configuration: environment values overlaid with stored credentials.
CONFIG_HOLDER = ConfigHolder(ENV_CONFIG)


LOGGER = logging.getLogger("intervals_coach")
GARMIN_SECRET_REGISTRY = GarminSecretRegistry()
WAHOO_SECRET_REGISTRY = WahooSecretRegistry()


def _nutrition_secret_values() -> tuple[str, ...]:
    # Logging starts before NUTRITION_SERVICES exists.
    nutrition = globals().get("NUTRITION_SERVICES")
    return () if nutrition is None else nutrition.secret_values()


# Environment secrets stay redacted while a stored credential overrides them.
REDACTOR = observability.Redactor(
    CONFIG_HOLDER,
    extra_secrets=lambda: (
        *GARMIN_SECRET_REGISTRY.values(),
        *WAHOO_SECRET_REGISTRY.values(),
        *_nutrition_secret_values(),
        *observability.config_secret_values(ENV_CONFIG),
    ),
)


KEY_VALUE_REPOSITORY = KeyValueRepository(runtime_clock.utc_now)
ATHLETE_SESSION_SERVICE = AthleteSessionService()
TRAINING_PLAN_REPOSITORY = TrainingPlanRepository()
PLANNING_STATE_REPOSITORY = PlanningStateRepository()
PLANNING_REVISION_SERVICE = PlanningRevisionService(
    PLANNING_STATE_REPOSITORY, runtime_clock.utc_now
)
PLAN_ADJUSTMENT_REPOSITORY = PlanAdjustmentRepository()
CHAT_REPOSITORY = ChatRepository(runtime_clock.utc_now)
ACTIVITY_FEEDBACK_REPOSITORY = ActivityFeedbackRepository(runtime_clock.utc_now)


GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS = 120


database_manager = DatabaseHolder(
    data_dir=lambda: DATA_DIR,
    database_path=lambda: DB_PATH,
    config=CONFIG_HOLDER,
    sqlcipher_available=lambda: SQLCIPHER_AVAILABLE,
    encrypted_backend=sqlite_backend,
    plain_backend=sqlite3,
    configure=configure_cipher,
    row_factory=database_row_factory,
)


def session_auth_service() -> SessionAuthService:
    """Compose the HTTP session owner from the active persistence and security configuration."""
    return get_session_auth_service(
        database_manager(),
        DB_LOCK,
        CONFIG_HOLDER.value,
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
    # The generation guards against a reused id after the configuration is replaced.
    config_id = (id(CONFIG_HOLDER.value), CONFIG_HOLDER.generation)
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
                CONFIG_HOLDER.value,
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
# Declared ahead of its first lambda reference; assigned after the coach turns.
PUBLIC_STATE: PublicStateServices
# Declared ahead of their first lambda reference; assigned by their builders below.
PROVIDER_TRANSPORT: ProviderTransportServices
WAHOO_CONNECTION: WahooConnectionServices
CANONICAL_BACKFILL: CanonicalBackfillServices
DIAGNOSTICS: DiagnosticsServices
PROVIDER_CREDENTIAL_SERVICE: ProviderCredentialService
ATHLETE_DATA = build_athlete_data(
    database_manager=database_manager,
    key_values=KEY_VALUE_REPOSITORY,
    activity_feedback_repository=ACTIVITY_FEEDBACK_REPOSITORY,
    profile_mutation_coordinator=PROFILE_MUTATION_COORDINATOR,
    utc_now=runtime_clock.utc_now,
    local_date=lambda: ATHLETE_CLOCK.now().date(),
    event_buffer=runtime_events.STATE_EVENT_BUFFER,
    activity_rows=lambda: CANONICAL_READ,
    table_reader=CanonicalTableReader,
    run_lthr=lambda: RUN_LTHR,
    load_inputs_changed=lambda: CANONICAL_BACKFILL.worker.start(),
    thresholds_changed=lambda: METRIC_EXPORT_RUNNER.request(),
    threshold_warnings=lambda: THRESHOLD_WARNINGS.read(),
)
ATHLETE_PROFILE_SERVICE = ATHLETE_DATA.profile_for(
    database_manager_runtime.DATABASE_MANAGER_CACHE
)
# Declared ahead of its first lambda reference; assigned by build_canonical_read below.
CANONICAL_READ: CanonicalReadSelector

# Renames a recognised route of outdoor sessions (#1868); only the label is exposed.
ACTIVITY_ROUTES = ActivityRouteService(database_manager, DB_LOCK, KEY_VALUE_REPOSITORY)

ATHLETE_CLOCK = AthleteLocalClock(ATHLETE_PROFILE_SERVICE)

# The application context the domain builders read (#2069). Owners whose
# builder step has not run yet are set as they are created.
APP = AppContext(
    config=CONFIG_HOLDER,
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
    refresh_config=lambda: PROVIDER_CREDENTIAL_SERVICE.refresh(),
    observed_opener=lambda service: PROVIDER_TRANSPORT.observed_opener(service),
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
ACTIVITY_READS = build_activity_reads(
    APP,
    session_activities=CanonicalTableReader().session_activities,
    refreshable_providers=lambda: configured_for_job(
        PROVIDER_CONFIGURED, "activity_details"
    ),
)
PLAN_GUARD = build_plan_guard(APP)
HISTORY = build_history(APP)


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
    refresh_credentials=lambda: PROVIDER_CREDENTIAL_SERVICE.refresh(),
    cancel_garmin_login=lambda: GARMIN_LOGIN.cancel(),
    disconnect_wahoo=lambda: WAHOO_CONNECTION.service().disconnect(),
    cancel_coach_turns=lambda: (
        APP.coach_conversation.reset_service().cancel_running_turns()
    ),
    log_files=lambda: DIAGNOSTICS.recent_log_entries_service(),
)
BACKUP = build_backup(APP)


def initialise_database() -> None:
    with DB_LOCK, database_manager().unit_of_work() as db:
        initialize_application_database(
            db,
            key_values=KEY_VALUE_REPOSITORY,
            now=runtime_clock.utc_now(),
            current_time=datetime.now(UTC),
            default_profile_json=json.dumps(DEFAULT_PROFILE),
            provider_resync_keys=PROVIDER_RESYNC_KEYS.values(),
            retention_days=int(getattr(CONFIG_HOLDER.value, "data_retention_days", -1)),
        )
    PROVIDER_CREDENTIAL_SERVICE.refresh()


def key_value_service() -> KeyValueService:
    return KeyValueService(database_manager, KEY_VALUE_REPOSITORY, DB_LOCK)


SYNC_PERIOD_DEFAULTS = DEFAULT_PROVIDER_REGISTRY.sync_period_defaults()
ALL_SYNC_DAYS = -1
SYNC_CHUNK_DAYS = 90
SYNC_EARLIEST_DATE = CONFIG_HOLDER.value.sync_history_earliest_date
PLANNED_CALENDAR_FUTURE_DAYS = 35
SYNC_WINDOW = SyncWindow(
    SYNC_PERIOD_DEFAULTS, ALL_SYNC_DAYS, SYNC_CHUNK_DAYS, SYNC_EARLIEST_DATE
)
SETTINGS = SettingsService(
    CONFIG_HOLDER,
    lambda key: key_value_service().get(key),
    lambda key, value: key_value_service().set(key, value),
    claude_models=lambda: MODEL_TRANSPORT.claude_models().status(),
)


PROVIDER_CREDENTIAL_SERVICE = ProviderCredentialService(
    env_config=ENV_CONFIG,
    database_manager=database_manager,
    database_lock=lambda: DB_LOCK,
    key_values=KEY_VALUE_REPOSITORY,
    apply_config=CONFIG_HOLDER.apply,
    garmin_connection=lambda: GARMIN_LOGIN.status(),
    current_config=CONFIG_HOLDER,
)


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
APP.sync_persistence = SYNC_PERSISTENCE


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
    tokenstore_path=lambda: CONFIG_HOLDER.value.garmin_tokenstore,
    registry=GARMIN_SECRET_REGISTRY,
    env_credentials=lambda: bool(
        CONFIG_HOLDER.value.garmin_email and CONFIG_HOLDER.value.garmin_password
    ),
)
GARMIN_LOGIN: GarminLoginService = GarminLoginService(
    config=CONFIG_HOLDER,
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
        METRIC_EXPORT.sync_automatic()
        if CONFIG_HOLDER.value.intervals_export_configured
        else None
    ),
    tokens=GARMIN_TOKENS,
    run_zones=lambda: RUN_LTHR.zones_resolver(),
)
APP.garmin = GARMIN_ASSEMBLY


SYNC_JOB_QUEUE = build_sync_job_queue(
    APP, all_sync_days=ALL_SYNC_DAYS, daily_sync_markers=sync_daily_markers
)
APP.sync_job_queue = SYNC_JOB_QUEUE

EXTERNAL_CALENDAR = build_external_calendar(APP)
APP.external_calendar = EXTERNAL_CALENDAR


PROVIDER_TRANSPORT = build_provider_transport(
    app_version=APP_VERSION,
    logger=LOGGER,
    diagnostic_capture=DIAGNOSTIC_CAPTURE,
    redact_text=REDACTOR.redact_text,
    provider_state=provider_state_service,
    operation_context=sync_observation.operation_context,
    current_config=CONFIG_HOLDER,
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


# The thresholds every outbound export sends (Intervals.icu metrics, Wahoo plan
# headers): local zones, then Garmin, then Wahoo, current on the athlete's today.
EXPORT_THRESHOLDS = build_export_thresholds(APP)
WAHOO_SYNC = build_wahoo_sync(
    APP,
    connection=WAHOO_CONNECTION.service,
    daily_markers=sync_daily_markers,
    resync_gate=WAHOO_RESYNC_GATE,
    export_thresholds=EXPORT_THRESHOLDS,
    history_earliest_date=SYNC_EARLIEST_DATE,
    fit_opener=lambda: PROVIDER_TRANSPORT.observed_opener(WAHOO_ID, include_path=False),
)
APP.wahoo = WAHOO_SYNC
APP.settings = SETTINGS
NUTRITION_SERVICES: NutritionServices = build_nutrition(APP)
APP.nutrition = NUTRITION_SERVICES
MODEL_TRANSPORT: ModelTransportServices = build_model_transport(
    config=CONFIG_HOLDER,
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
COACH_CONVERSATION = build_coach_conversation(
    APP, chat_repository=CHAT_REPOSITORY, conversation_lock=COACH_CONVERSATION_GATE.lock
)
APP.coach_conversation = COACH_CONVERSATION
COACH_LOCAL = build_coach_local(APP)
APP.coach_local = COACH_LOCAL
PLANNED_UNIT_SYNC = build_planned_unit_sync(APP)
PLANNED_CALENDAR_SYNC = build_planned_calendar_sync(
    APP,
    state_writer=PLANNED_UNIT_SYNC.state_writer,
    future_days=PLANNED_CALENDAR_FUTURE_DAYS,
)
WORKOUT_LIBRARY_SYNC = build_workout_library_sync(APP)
APP.workout_library_sync = WORKOUT_LIBRARY_SYNC
SELECTED_WORKOUT_SYNC = build_selected_workout_sync(
    APP, planned_calendar=PLANNED_CALENDAR_SYNC, resync_gate=INTERVALS_RESYNC_GATE
)
WEATHER: WeatherServices = build_weather(APP)
APP.weather = WEATHER
WEATHER_SYNC = build_weather_sync(APP, WEATHER)

COACH_CONTEXT = build_coach_context(
    APP, threshold_warnings=lambda: THRESHOLD_WARNINGS.read(), plan_guard=PLAN_GUARD
)
APP.coach_context = COACH_CONTEXT
COACH_READ_TOOLS = build_coach_read_tools(
    APP,
    activity_read=ACTIVITY_READS.activity_read,
    history=HISTORY,
    plan_guard=PLAN_GUARD,
)
APP.coach_read_tools = COACH_READ_TOOLS
COACH_PROPOSALS = build_coach_proposals(APP, history=HISTORY)
APP.coach_proposals = COACH_PROPOSALS

# Derived passes (local load, canonical backfill, Wahoo metric export) after any
# provider read: a queued job, a Coach request that waits and a full resync.
DERIVED_PASS_HOOK = chained_after_job(
    refresh_after_job(lambda: CANONICAL_BACKFILL.worker.start()),
    lambda job: METRIC_EXPORT_RUNNER.after_job(job),
)

PROVIDER_RESYNC = build_provider_resync(
    APP,
    garmin_resync_gate=GARMIN_RESYNC_GATE,
    wahoo_resync_gate=WAHOO_RESYNC_GATE,
    all_sync_days=ALL_SYNC_DAYS,
    after_resync=DERIVED_PASS_HOOK,
)

PROVIDER_CONFIGURED: dict[str, Callable[[], bool]] = provider_configured_checks(APP)

SYNC_JOB_EXECUTION = build_sync_job_execution(
    APP,
    window=SYNC_WINDOW,
    selected_workout_sync_service=SELECTED_WORKOUT_SYNC.service,
    competition_sync_service=PROVIDER_RESYNC.competition_sync_service,
    weather_sync_service=WEATHER_SYNC,
    intervals_resync_gate=INTERVALS_RESYNC_GATE,
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

SYNC_SCHEDULERS: SyncSchedulerServices = build_sync_schedulers(
    APP,
    window=SYNC_WINDOW,
    weather_sync=WEATHER_SYNC,
    garmin_resync_gate=GARMIN_RESYNC_GATE,
    wahoo_resync_gate=WAHOO_RESYNC_GATE,
    retry_held=PROVIDER_RETRY_HOLD.held,
)

SYNC_COMMANDS = build_sync_commands(
    APP,
    intervals_client=lambda: APP.provider_transport.intervals_client(),
    synchronous_refreshes=lambda: coach_synchronous_refreshes(APP, SYNC_WINDOW),
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


COACH_PLANNING_TOOLS = build_coach_planning_tools(
    APP, plan_guard=PLAN_GUARD, sync_commands=SYNC_COMMANDS
)
APP.coach_planning_tools = COACH_PLANNING_TOOLS
COACH_COMMAND_TOOLS = build_coach_command_tools(APP, sync_commands=SYNC_COMMANDS)
APP.coach_command_tools = COACH_COMMAND_TOOLS
COACH_TOOL_DISPATCH = build_coach_tool_dispatch(APP, history=HISTORY)
APP.coach_tool_dispatch = COACH_TOOL_DISPATCH
COACH_TOOL_ROUNDS = build_coach_tool_rounds(
    APP,
    root=ROOT,
    read_only_tools=STRUCTURED_READ_ONLY_TOOLS,
    plan_guard=PLAN_GUARD,
    sync_commands=SYNC_COMMANDS,
)
APP.coach_tool_rounds = COACH_TOOL_ROUNDS
COACH_BACKGROUND_JOBS = build_coach_background_jobs(
    APP,
    chat_repository=CHAT_REPOSITORY,
    root=ROOT,
    read_only_tools=STRUCTURED_READ_ONLY_TOOLS,
    session_auth_service=session_auth_service,
)
APP.coach_background_jobs = COACH_BACKGROUND_JOBS
COACH_TURNS = build_coach_turns(
    APP,
    chat_repository=CHAT_REPOSITORY,
    conversation_gate=COACH_CONVERSATION_GATE,
    root=ROOT,
    read_only_tools=STRUCTURED_READ_ONLY_TOOLS,
)
APP.coach_turns = COACH_TURNS


PUBLIC_STATE = build_public_state(
    APP,
    key_value_service=key_value_service,
    provider_credentials=lambda: PROVIDER_CREDENTIAL_SERVICE,
    provider_resync=lambda: PROVIDER_RESYNC,
    running_probes={WAHOO_ID: lambda: WAHOO_SYNC.sync_service().running()},
    sync_period_defaults=lambda: SYNC_PERIOD_DEFAULTS,
    all_sync_days=ALL_SYNC_DAYS,
    external_calendar_window_days=lambda: (
        calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS
    ),
)

CANONICAL_READ = build_canonical_read(
    key_values=KEY_VALUE_REPOSITORY,
    profile=ATHLETE_PROFILE_SERVICE,
)
APP.canonical_read = CANONICAL_READ
METRIC_EXPORT: MetricExportService = build_metric_export(
    APP, thresholds=EXPORT_THRESHOLDS
)


METRIC_EXPORT_RUNNER = MetricExportRunner(
    lambda: METRIC_EXPORT,
    enabled=lambda: CONFIG_HOLDER.value.intervals_export_configured,
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
        config=CONFIG_HOLDER,
        request=lambda *args, **kwargs: PROVIDER_TRANSPORT.json_http_client().request(
            *args, **kwargs
        ),
        default_openai_base_url=DEFAULT_OPENAI_BASE_URL,
        default_anthropic_base_url=DEFAULT_ANTHROPIC_BASE_URL,
        intervals_get=lambda path: APP.provider_transport.intervals_client().get(path),
        wahoo_status=lambda: WAHOO_CONNECTION.service().status(),
        wahoo_user=lambda: WAHOO_SYNC.client().user(),
        garmin_connected=lambda: GARMIN_TOKENS.source() == GARMIN_SOURCE_DB,
        garmin_fingerprint=GARMIN_TOKENS.fingerprint,
        garmin_login=lambda: GARMIN_ASSEMBLY.check_stored_login(),
    ),
    operation=lambda: runtime_maintenance.MAINTENANCE_GATE.operation(),
)
# The owners the HTTP routes read from the context.
APP.public_state = PUBLIC_STATE
APP.activity_reads = ACTIVITY_READS
APP.activity_routes = ACTIVITY_ROUTES
APP.history = HISTORY
APP.backup = BACKUP
APP.privacy = PRIVACY
APP.diagnostics = DIAGNOSTICS
APP.provider_resync = PROVIDER_RESYNC
APP.provider_credential_service = PROVIDER_CREDENTIAL_SERVICE
APP.provider_connection_checks = PROVIDER_CONNECTION_CHECKS
APP.wahoo_connection = WAHOO_CONNECTION
APP.metric_export = METRIC_EXPORT
APP.garmin_login = GARMIN_LOGIN
HTTP_API = build_http_api(
    APP,
    session_auth_service=session_auth_service,
    audio=audio_provider,
    max_body_bytes=MAX_BODY_BYTES,
    max_audio_body_bytes=MAX_AUDIO_BODY_BYTES,
    public_dir=PUBLIC_DIR,
    chat_page_max=CHAT_PAGE_MAX,
    response_timeout_seconds=OPENAI_RESPONSE_TIMEOUT_SECONDS,
    sync_period_defaults=SYNC_PERIOD_DEFAULTS,
    all_sync_days=ALL_SYNC_DAYS,
    provider_configured=PROVIDER_CONFIGURED,
)


def main() -> None:
    observability.configure_logging(LOGGER, DATA_DIR, LOG_PATH, REDACTOR)
    configuration_error = app_config.security_configuration_error(
        CONFIG_HOLDER.value, sqlcipher_available=SQLCIPHER_AVAILABLE
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
    proxy_warning = app_config.proxy_list_warning(
        CONFIG_HOLDER.value.invalid_trusted_proxies
    )
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
            "context": {"version": APP_VERSION, "port": CONFIG_HOLDER.value.port},
        },
    )
    initialise_database()
    remove_orphaned_staging_files(DATA_DIR, LOGGER)
    server = http_server.CoachHTTPServer(
        ("0.0.0.0", CONFIG_HOLDER.value.port), HTTP_API.request_handler_class()
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
        sync_worker = SYNC_WORKERS.create()
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
            extra={
                "event": "server_ready",
                "context": {"port": CONFIG_HOLDER.value.port},
            },
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
