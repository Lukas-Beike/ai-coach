from __future__ import annotations
from backend.coach.attachments import (
    MAX_ATTACHMENT_STORAGE_BYTES,
    MAX_GEMINI_INLINE_IMAGE_BYTES,
    MAX_REQUEST_BYTES,
)
from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.profile_update import CoachProfileUpdateService
from backend.coach.read_tools import CoachReadToolService
from backend.coach.training_template_tools import TrainingTemplateToolService
from backend.coach import streams as coach_streams

import hashlib
import hmac
import json
import logging
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from contextlib import nullcontext, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import partial, wraps
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

from backend.db import row_factory as database_row_factory
from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import (
    DiagnosticReportDependencies,
    DiagnosticReportService,
)
from backend.errors import (
    COACH_ABORTED_ERROR,
    INTERNAL_SERVER_ERROR,
    INTERVALS_API_KEY_ERROR,
    INVALID_LIBRARY_ID_ERROR,
    NOT_FOUND_ERROR,
    PLANNED_CALENDAR_RECHECK_ERROR,
    AppError,
    ClientDisconnected,
    provider_error,
    public_app_error_status,
)
from backend import config as app_config
from backend import change_history
from backend import observability
from backend.activities.duplicate_service import DuplicateActivityService
from backend.calendar import external as calendar_external
from backend.calendar import local as calendar_local
from backend.calendar import public_events as public_event_calendar
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
    intervals_operation,
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
from backend.db.repositories import ActivityFeedbackRepository, ChatRepository, CheckinRepository, CompetitionRepository, KeyValueRepository, PlanAdjustmentRepository, PlanningStateRepository, ProfileRepository, SnapshotRepository, TrainingPlanRepository
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
from backend.providers.garmin import GarminClientFactory
from backend.providers.garmin_morning import fetch_morning_body_battery
from backend.http_api import server as http_server
from backend.http_api.bootstrap_state import (
    PublicBootstrapDependencies,
    PublicBootstrapService,
)
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
from backend.planning import planned_units as planning_planned_units
from backend.planning import planned_unit_service as planning_planned_unit_service
from backend.planning.replacement_service import StructuredTrainingPlanReplacementService
from backend.planning.revision import PlanningRevisionService
from backend.planning import season as planning_season
from backend.planning.state_service import StructuredTrainingStateService
from backend.planning.training_plan_artifact_service import TrainingPlanArtifactService
from backend.planning import training_plans as planning_training_plans
from backend.planning import workouts as planning_workouts
from backend.http_api.bootstrap_calendar import PublicStateCalendarProjection
from backend.http_api.public_state import PublicStateDependencies, PublicStateService
from backend.sync.jobs import (
    SyncJobStore,
)
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.queue import SyncJobQueueService
from backend.sync.scheduler import (
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
    CoachConversationProvisionService,
    CoachConversationResetService,
    CoachMessageService,
    GeminiConversationHistoryService,
    GeminiConversationResponseService,
    GeminiLocalChatHistoryService,
    GeminiRequestPayloadService,
    GeminiResponseNormalizationService,
)
from backend.coach.proposals import (
    CoachProposalCreationService,
    CoachProposalConfirmationService,
    CoachProposalExecutionService,
    CoachProposalReadService,
    coach_action_hash,
    coach_action_view,
)
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.dialogue import CoachDialogueReadService, INSTRUCTIONS as COACH_DIALOGUE_INSTRUCTIONS, dialogue_tools
from backend.coach.dialogue_action import CoachDialogueActionService
from backend.coach.dialogue_plan_scope import CoachDialoguePlanScopeService
from backend.coach.clarification import CoachClarificationService
from backend.coach.turn_outcome import CoachStructuredOutcomeService
from backend.coach.tool_call_metadata import structured_tool_call_metadata
from backend.coach.training_patch import CoachTrainingPatchService
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.coach.tool_round_journal import CoachStructuredToolRoundJournal
from backend.coach.response_retry import CoachResponseRetryPolicy
from backend.coach.conversation_recovery import CoachConversationRecoveryService
from backend.coach.planning_commands import CoachPlanningCommandService
from backend.coach.job_store import CoachJobStore
from backend.coach.cancellation import CoachCancellationService
from backend.coach.turn_failures import (
    CoachTurnFailureDependencies,
    CoachTurnFailureService,
    coach_error_metadata,
)
from backend.coach.job_submission import CoachJobSubmissionService
from backend.coach.morning import ManualMorningCheckinService, MorningCheckinStateService
from backend.coach.tools import build_tool_contracts
from backend.coach.service import command_receipt
from backend.coach.authorization import (
    coach_execution_scope,
    coach_session_key,
    require_coach_scope,
)
from backend.http_api.responses import (
    header_items as response_header_items,
    json_bytes as response_json_bytes,
    response_headers,
)
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.http_api.library_page import LibraryPageService
from backend.http_api.chat_page import ChatHistoryPageService
from backend.http_api.static_assets import StaticAssetService
from backend.http_api.export_streams import ExportStreamTransport
from backend.http_api.state_events_transport import StateEventTransport
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
TRAINING_PLAN_SCOPE_PREFIX = "training_plan:"
PLANNED_WORKOUT_LABEL = "Geplante Einheit"
AUTO_UPDATE_LABEL = "stündliche automatische Aktualisierung"
APP_NAME = "Intervals Coach"
SELECT_PLANNED_PAYLOAD_SQL = "SELECT payload FROM planned_units WHERE local_id=?"
UPDATE_COMMAND_RECEIPT_SQL = "UPDATE coach_commands SET status='completed', receipt=?, updated_at=? WHERE client_turn_id=?"
SELECT_COMMAND_RECEIPT_SQL = "SELECT receipt FROM coach_commands WHERE client_turn_id=?"
APP_VERSION = "1.11.11"
MAX_BODY_BYTES = 1_000_000
MAX_AUDIO_BODY_BYTES = 8_000_000
MAX_BACKUP_BYTES = 100_000_000
MAX_PRIVACY_EXPORT_BYTES = 100_000_000
MIN_EXPORT_FREE_BYTES = 10_000_000
EXPORT_TIME_LIMIT_SECONDS = 120
STREAM_CHUNK_BYTES = 64 * 1024
MAX_EXTERNAL_RESPONSE_BYTES = 10_000_000
# The Responses API counts both visible output and reasoning tokens against
# max_output_tokens. Keep ordinary replies bounded, but leave enough room for
# an explicitly requested multi-week training plan.
COACH_DEFAULT_MAX_OUTPUT_TOKENS = 6_000
COACH_LONG_PLAN_MAX_OUTPUT_TOKENS = 32_000
COACH_FOLLOWUP_MAX_OUTPUT_TOKENS = 2_500
OPENAI_RESPONSE_TIMEOUT_SECONDS = 180
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_BACKGROUND_POLL_SECONDS = 2
OPENAI_BACKGROUND_MAX_SECONDS = 60 * 60
COACH_BACKGROUND_HORIZON_DAYS = 7
COACH_BACKGROUND_UNIT_LIMIT = 7
COACH_TRAINING_CHANGE_LIMIT = 366
INTERVALS_SYNC_WAIT_SECONDS = 120
DB_LOCK = threading.RLock()
OPENAI_CONVERSATION_LOCK = threading.RLock()
CHAT_QUEUE_LIMIT = 3
CHAT_QUEUE = threading.BoundedSemaphore(CHAT_QUEUE_LIMIT)
CHAT_LOCK_TIMEOUT_SECONDS = 30
COACH_JOB_WORKER_LOCK = threading.Lock()
COACH_JOB_WAKE = threading.Event()
COACH_JOB_STOP = threading.Event()
COACH_JOB_WORKER: threading.Thread | None = None
SYNC_JOB_WORKER: SyncJobWorker | None = None
RATE_LIMITER = RateLimiter()
SYNC_JOB_RE = re.compile(r"^/api/sync/jobs/([0-9a-f-]+)$")


CONFIG = load_config(ROOT, DATA_DIR)


class IntervalsClient:
    def __init__(self, config: Config | None = None, *, request: Callable[..., Any] | None = None):
        self.config = config or CONFIG
        request_fn = request or (lambda *args, **kwargs: provider_http_client().request(*args, **kwargs))
        self._api = IntervalsApiClient(
            api_key=self.config.intervals_api_key,
            request=lambda *args, **kwargs: request_fn(*args, **kwargs),
        )
        self._workout_folder_id: int | None = None

    @property
    def pagination(self) -> dict[str, dict[str, Any]]:
        return {collection: dict(metadata) for collection, metadata in self._api.pagination.items()}

    def get(self, path: str, params: dict[str, Any] | None = None, *, cancel_event: threading.Event | None = None) -> Any:
        if cancel_event is None:
            return self._api.get(path, params)
        return self._api.get(path, params, cancel_event=cancel_event)

    def get_paged_collection(
        self,
        path: str,
        params: dict[str, Any] | None,
        collection: str,
        page_size: int = 500,
        cancel_event: threading.Event | None = None,
    ) -> list[dict[str, Any]]:
        return self._api.get_paged_collection(
            path,
            params,
            collection,
            page_size=page_size,
            cancel_event=cancel_event,
        )

    @intervals_operation
    def post(self, path: str, payload: Any, params: dict[str, Any] | None = None) -> Any:
        return self._api.post(path, payload, params)

    @intervals_operation
    def put(self, path: str, payload: Any, params: dict[str, Any] | None = None) -> Any:
        return self._api.put(path, payload, params)

    @intervals_operation
    def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._api.delete(path, params)

    def get_workout_library(self, *, cancel_event: threading.Event | None = None) -> list[dict[str, Any]]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.get_paged_collection(
            f"/athlete/{athlete}/workouts", {}, "workout_library", cancel_event=cancel_event
        )
        if not isinstance(result, list):
            raise AppError(502, "Intervals.icu hat keine Trainingsbibliothek zurÃ¼ckgegeben.")
        fields = (
            "id", "name", "description", "type", "moving_time", "distance",
            "target", "workout_doc", "icu_training_load", "icu_intensity", "indoor",
            "tags", "folder_id",
        )
        return [planning_context.selected(item, fields) for item in result if isinstance(item, dict)]

    @staticmethod
    def _folder_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            folder_id = int(value)
        except (TypeError, ValueError):
            return None
        return folder_id if folder_id > 0 else None

    def get_or_create_workout_folder(self) -> int:
        """Return the private library folder used for coach-created templates."""
        if self._workout_folder_id is not None:
            return self._workout_folder_id
        athlete = quote(self.config.intervals_athlete_id, safe="")
        folders = self.get(f"/athlete/{athlete}/folders")
        if isinstance(folders, dict):
            folders = folders.get("folders") or folders.get("data") or []
        if not isinstance(folders, list):
            raise AppError(502, "Intervals.icu hat keine gültige Ordnerliste zurückgegeben.")
        matching: list[dict[str, Any]] = []
        pending = [item for item in folders if isinstance(item, dict)]
        while pending:
            folder = pending.pop(0)
            if str(folder.get("name") or "").strip() == APP_NAME:
                matching.append(folder)
            children = folder.get("children")
            if isinstance(children, list):
                pending.extend(item for item in children if isinstance(item, dict))
        for folder in matching:
            folder_id = self._folder_id(folder.get("id"))
            if folder_id is not None:
                self._workout_folder_id = folder_id
                return folder_id
        created = self.post(f"/athlete/{athlete}/folders", {"name": APP_NAME})
        folder_id = self._folder_id(created.get("id") if isinstance(created, dict) else None)
        if folder_id is None:
            raise AppError(502, "Intervals.icu hat keinen gültigen Ordner zurückgegeben.")
        self._workout_folder_id = folder_id
        return folder_id

    def create_library_workouts(self, workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for workout in workouts:
            planning_workouts.validate_workout_description(workout)
        athlete = quote(self.config.intervals_athlete_id, safe="")
        folder_id = self.get_or_create_workout_folder()
        created: list[dict[str, Any]] = []
        for workout in workouts:
            payload = {
                "name": str(workout.get("name") or "Coach-Einheit")[:200],
                "description": str(workout.get("description") or "")[:12000],
                "type": planning_workouts.intervals_workout_sport(workout.get("type") or workout.get("sport")),
                "folder_id": folder_id,
                "target": workout.get("target") or "AUTO",
            }
            result = self.post(f"/athlete/{athlete}/workouts", payload)
            if not isinstance(result, dict):
                raise AppError(502, "Intervals.icu hat keine Trainingsbibliotheks-Einheit zurÃ¼ckgegeben.")
            created.append(result)
        return created

    def update_library_workout(self, workout_id: str, workout: dict[str, Any]) -> dict[str, Any]:
        planning_workouts.validate_workout_description(workout)
        athlete = quote(self.config.intervals_athlete_id, safe="")
        remote_id = quote(str(workout_id), safe="")
        payload = {
            "name": str(workout.get("name") or "Coach-Einheit")[:200],
            "description": str(workout.get("description") or "")[:12000],
            "type": planning_workouts.intervals_workout_sport(workout.get("type") or workout.get("sport")),
            "target": workout.get("target") or "AUTO",
        }
        folder_id = self._folder_id(workout.get("folder_id"))
        # Intervals.icu requires folder_id for workout updates as well as
        # creates. Resolve a missing folder through the private Coach folder.
        payload["folder_id"] = folder_id if folder_id is not None else self.get_or_create_workout_folder()
        result = self.put(f"/athlete/{athlete}/workouts/{remote_id}", payload)
        if not isinstance(result, dict):
            raise AppError(502, "Intervals.icu returned no updated library workout.")
        return result

    def plan_library_workout(self, workout_id: str, workout: dict[str, Any], plan_date: str) -> dict[str, Any]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        payload = planning_workouts.workout_event_payload(
            f"library-{workout_id}-{plan_date}",
            {
                "date": plan_date,
                "sport": workout.get("type") or workout.get("sport") or "Ride",
                "name": workout.get("name") or "Bibliotheks-Einheit",
                "description": workout.get("description") or "",
                "duration_minutes": workout.get("duration_minutes") or max(5, round(float(workout.get("moving_time") or 3600) / 60)),
                "target": workout.get("target") or "AUTO",
            },
            today=local_now().date(),
        )
        result = self.post(f"/athlete/{athlete}/events/bulk", [payload], {"upsert": "true"})
        if not isinstance(result, list) or not result:
            raise AppError(502, "Intervals.icu hat keine geplante Einheit zurÃ¼ckgegeben.")
        planning_workouts.validate_intervals_workout_result(workout, result[0])
        return result[0]

    def fetch_competition_events(self) -> list[dict[str, Any]]:
        """Fetch a broad calendar range for target-event synchronization."""
        athlete = quote(self.config.intervals_athlete_id, safe="")
        today = local_now().date()
        result = self.get_paged_collection(
            f"/athlete/{athlete}/events",
            {
                "oldest": (today - timedelta(days=365)).isoformat(),
                "newest": (today + timedelta(days=730)).isoformat(),
            },
            "competition_events",
        )
        if not isinstance(result, list):
            raise AppError(502, "Intervals.icu hat keine Kalenderevents zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def upsert_competition_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.post(f"/athlete/{athlete}/events/bulk", events, {"upsert": "true"})
        if not isinstance(result, list):
            raise AppError(502, "Intervals.icu hat keine Zielwettkämpfe zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def upsert_calendar_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Upsert explicitly approved non-workout calendar events."""
        if not events:
            return []
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.post(f"/athlete/{athlete}/events/bulk", events, {"upsert": "true"})
        if not isinstance(result, list):
            raise AppError(502, "Intervals.icu hat keine Kalendereinträge zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def bulk_delete_events(self, identifiers: list[dict[str, str]]) -> Any:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        return self.put(f"/athlete/{athlete}/events/bulk-delete", identifiers)

    def delete_event(self, event_id: str) -> Any:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        return self.delete(f"/athlete/{athlete}/events/{quote(event_id, safe='')}")

    def delete_activity(self, activity_id: str) -> Any:
        return self.delete(f"/activity/{quote(activity_id, safe='')}")



LOGGER = logging.getLogger("intervals_coach")
REDACTOR = observability.Redactor(lambda: CONFIG)




def serialise_conversation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not CHAT_QUEUE.acquire(blocking=False):
            raise AppError(429, "Der Coach ist gerade ausgelastet. Bitte später erneut versuchen.", reason="chat_queue_full")
        acquired = OPENAI_CONVERSATION_LOCK.acquire(timeout=CHAT_LOCK_TIMEOUT_SECONDS)
        if not acquired:
            CHAT_QUEUE.release()
            raise AppError(409, "Die vorherige Coach-Anfrage läuft noch. Bitte erneut versuchen.", reason="chat_request_timeout")
        try:
            return function(*args, **kwargs)
        finally:
            OPENAI_CONVERSATION_LOCK.release()
            CHAT_QUEUE.release()
    return wrapped


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
MORNING_RETRY_SECONDS = 15 * 60
MORNING_MAX_ATTEMPTS = 3

LIBRARY_BULK_PREVIEW_TTL_SECONDS = 10 * 60


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
        COACH_TRAINING_CHANGE_LIMIT,
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


def coach_athlete_record_tool_service() -> CoachAthleteRecordToolService:
    """Compose concrete local services for Coach athlete-record mutations."""
    return CoachAthleteRecordToolService(
        checkin_service(), activity_feedback_service(), competition_service()
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
        COACH_TRAINING_CHANGE_LIMIT,
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
            lambda checkin_date: fetch_morning_body_battery(
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
            MorningBatteryRetryPolicy(MORNING_MAX_ATTEMPTS, MORNING_RETRY_SECONDS),
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
        IntervalsClient,
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
        IntervalsClient,
        planned_unit_sync_state_writer(),
        utc_now,
        lambda: local_now().date(),
    )


def planned_calendar_repair_service() -> PlannedCalendarRepairService:
    """Compose the exact-identity planned calendar repair use case."""
    return PlannedCalendarRepairService(
        CONFIG,
        database_manager(),
        IntervalsClient,
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
        IntervalsClient,
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
        CONFIG, IntervalsClient, workout_library_sync_state_service()
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
        COACH_TRAINING_CHANGE_LIMIT,
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
        COACH_TRAINING_CHANGE_LIMIT,
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
        IntervalsClient(),
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


@contextmanager
def database():
    """Use the database manager as the sole nested transaction owner."""
    with database_manager().unit_of_work() as db:
        yield db


def initialise_database() -> None:
    with DB_LOCK, database() as db:
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


def get_kv(key: str, db: sqlite3.Connection | None = None) -> str | None:
    if db is not None:
        return KEY_VALUE_REPOSITORY.get(db, key)
    with DB_LOCK, database() as owned:
        return get_kv(key, owned)


SYNC_PERIOD_DEFAULTS = {"intervals": 90, "garmin": 30}
ALL_SYNC_DAYS = -1
SYNC_CHUNK_DAYS = 90
SYNC_EARLIEST_DATE = date(2000, 1, 1)
# Keep enough calendar history to show whether recently planned workouts were
# completed, while retaining the existing five-week forward planning horizon.
PLANNED_CALENDAR_HISTORY_DAYS = 35
PLANNED_CALENDAR_FUTURE_DAYS = 35
COACH_RECENT_ACTIVITIES_PER_SPORT = 5
COACH_PLANNED_EVENT_LIMIT = 50
COACH_LOCAL_PLANNED_LIMIT = 50
COACH_LIBRARY_LIMIT = 12
COACH_LIBRARY_DESCRIPTION_LIMIT = 1500
COACH_CONTEXT_TOTAL_CHAR_LIMIT = 120_000
COACH_CONTEXT_SECTION_LIMITS = {
    "intervals": 32_000,
    "current_performance": 24_000,
    "garmin": 16_000,
    "local_feedback": 12_000,
    "activity_feedback": 12_000,
    "planning": 16_000,
    "weather": 16_000,
    "daily_planning_context": 24_000,
    "external_calendar": 20_000,
}


def set_kv(key: str, value: str, db: sqlite3.Connection | None = None) -> None:
    if db is not None:
        KEY_VALUE_REPOSITORY.set(db, key, value)
        return
    with DB_LOCK, database() as owned:
        set_kv(key, value, owned)


SETTINGS = SettingsService(lambda: CONFIG, get_kv, set_kv)
DIAGNOSTIC_CAPTURE = observability.DiagnosticCapture(get_kv, set_kv, REDACTOR, utc_now)


def provider_http_client() -> provider_http.JsonHttpClient:
    """Return the observed JSON client bound to the active provider state."""
    global PROVIDER_HTTP_CLIENT
    state = provider_state_service()
    if PROVIDER_HTTP_CLIENT is None or PROVIDER_HTTP_CLIENT.provider_state is not state:
        PROVIDER_HTTP_CLIENT = provider_http.JsonHttpClient(
            APP_VERSION,
            MAX_EXTERNAL_RESPONSE_BYTES,
            LOGGER,
            DIAGNOSTIC_CAPTURE,
            state,
            REDACTOR.redact_text,
            partial(observability.safe_response_headers, redact=REDACTOR.redact_text),
            utc_now,
            sync_observation.operation_context,
            opener=urlopen,
        )
    return PROVIDER_HTTP_CLIENT


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
        max_bytes=MAX_EXTERNAL_RESPONSE_BYTES,
        app_version=APP_VERSION,
        json_media_type=JSON_MEDIA_TYPE,
        provider_state=provider_state_service(),
        logger=LOGGER,
        opener=urlopen,
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
        coach_streams.CHAT_STREAM_REGISTRY, DB_LOCK, OPENAI_CONVERSATION_LOCK,
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
            max_bytes=MAX_EXTERNAL_RESPONSE_BYTES,
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
        opener=urlopen,
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


def coach_job_store() -> CoachJobStore:
    """Compose durable Coach background-job persistence."""
    return CoachJobStore(
        database_manager, DB_LOCK, COACH_JOB_WAKE,
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
        COACH_JOB_WAKE, utc_now, background_horizon_days=COACH_BACKGROUND_HORIZON_DAYS,
        max_attachment_storage_bytes=MAX_ATTACHMENT_STORAGE_BYTES,
        max_gemini_inline_image_bytes=MAX_GEMINI_INLINE_IMAGE_BYTES,
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
        TRAINING_PLAN_SCOPE_PREFIX,
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
        database_manager(), CHAT_REPOSITORY, max_inline_bytes=MAX_GEMINI_INLINE_IMAGE_BYTES
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
        default_max_output_tokens=COACH_DEFAULT_MAX_OUTPUT_TOKENS,
        json_media_type=JSON_MEDIA_TYPE,
    )


CHAT_PAGE_MAX = 100


def library_page_service() -> LibraryPageService:
    """Compose the read-only workout-library page query."""
    return LibraryPageService(database_manager())


def chat_history_page_service() -> ChatHistoryPageService:
    """Compose bounded local chat history and session-bound proposal reads."""
    return ChatHistoryPageService(
        database_manager(),
        KEY_VALUE_REPOSITORY,
        coach_proposal_read_service(),
        DB_LOCK,
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
        IntervalsClient, runtime_maintenance.MAINTENANCE_GATE,
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
        local_planned_limit=COACH_LOCAL_PLANNED_LIMIT,
        library_limit=COACH_LIBRARY_LIMIT,
        library_description_limit=COACH_LIBRARY_DESCRIPTION_LIMIT,
        section_limits=COACH_CONTEXT_SECTION_LIMITS,
        total_char_limit=COACH_CONTEXT_TOTAL_CHAR_LIMIT,
        activity_limit_per_sport=COACH_RECENT_ACTIVITIES_PER_SPORT,
        planned_event_limit=COACH_PLANNED_EVENT_LIMIT,
    )


def coach_request_payload_service() -> CoachRequestPayloadService:
    """Compose the stateless structured Coach request builder."""
    return CoachRequestPayloadService(
        coach_training_context_service(), SETTINGS, COACH_LONG_PLAN_MAX_OUTPUT_TOKENS,
    )


def coach_context_preview_service() -> CoachContextPreviewService:
    """Compose read-only, user-inspectable Coach context preview."""
    return CoachContextPreviewService(
        sync_state_repository(), coach_message_service(), coach_training_context_service(),
        coach_structured_context_service(), workout_library_service(),
        CoachContextPreviewLimits(
            library_limit=COACH_LIBRARY_LIMIT,
            library_description_limit=COACH_LIBRARY_DESCRIPTION_LIMIT,
            section_limits=COACH_CONTEXT_SECTION_LIMITS,
            total_char_limit=COACH_CONTEXT_TOTAL_CHAR_LIMIT,
            local_planned_limit=COACH_LOCAL_PLANNED_LIMIT,
            activity_limit_per_sport=COACH_RECENT_ACTIVITIES_PER_SPORT,
            planned_event_limit=COACH_PLANNED_EVENT_LIMIT,
        ),
        utc_now=lambda: datetime.now(timezone.utc),
    )


def transcribe_audio(audio: bytes, content_type: str) -> dict[str, str]:
    """Transcribe one short voice note; audio is intentionally never persisted."""
    return audio_transcription_client().transcribe(
        audio,
        content_type,
        provider=SETTINGS.selected_ai_provider(),
        model=SETTINGS.selected_model(),
    )


def request_ai_provider(payload: dict[str, Any]) -> str:
    provider = str(payload.get("_ai_provider") or "").casefold()
    return provider if provider in {"openai", "gemini"} else SETTINGS.selected_ai_provider()


def responses_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Call Responses API and retry transient locks on the persistent conversation."""
    if request_ai_provider(payload) == "gemini":
        return gemini_conversation_response_service().request(payload)
    return openai_responses_client().responses(payload)


def responses_background_request(
    payload: dict[str, Any],
    *,
    response_id: str | None = None,
    on_response_id: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Create or resume a bounded OpenAI background response and poll it."""
    if request_ai_provider(payload) == "gemini":
        _raise_chat_cancelled(cancel_event)
        result = gemini_conversation_response_service().request(payload, cancel_event=cancel_event)
        _raise_chat_cancelled(cancel_event)
        return result
    return openai_responses_client().background(
        payload,
        response_id=response_id,
        on_response_id=on_response_id,
        cancel_event=cancel_event,
    )


def _raise_chat_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AppError(499, COACH_ABORTED_ERROR, reason="chat_cancelled")


def responses_stream_request(
    payload: dict[str, Any],
    on_text_delta: Any,
    cancel_event: threading.Event | None = None,
    on_response_id: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if request_ai_provider(payload) == "gemini":
        _raise_chat_cancelled(cancel_event)
        result = gemini_conversation_response_service().stream(payload, on_text_delta, cancel_event)
        _raise_chat_cancelled(cancel_event)
        return result
    return openai_stream_client().stream(
        payload,
        on_text_delta,
        cancel_event=cancel_event,
        on_response_id=on_response_id,
    )


COACH_TOOL_MAX_ROUNDS = 12
COACH_COMMAND_STALE_SECONDS = 15 * 60
COACH_CANONICAL_TOOL_NAMES, COACH_STRUCTURED_TOOLS, STRUCTURED_READ_ONLY_TOOLS, COACH_DIALOGUE_TOOLS = build_tool_contracts(
    default_profile=DEFAULT_PROFILE,
    checkin_text_limits=CHECKIN_TEXT_LIMITS,
    checkin_score_fields=CHECKIN_SCORE_FIELDS,
    training_change_limit=COACH_TRAINING_CHANGE_LIMIT,
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
            TRAINING_PLAN_SCOPE_PREFIX,
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
            TRAINING_PLAN_SCOPE_PREFIX,
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


def _structured_coach_receipt(
    message: str,
    *,
    intent: dict[str, Any],
    conversation_id: str,
    client_turn_id: str,
    session_csrf_hash: str,
    ai_provider: str,
    model: str | None,
) -> dict[str, Any]:
    with DB_LOCK, database() as db:
        existing = db.execute(SELECT_COMMAND_RECEIPT_SQL, (client_turn_id,)).fetchone()
        receipt = command_receipt(existing["receipt"]) if existing else {}
        if existing:
            coach_command_receipt_service().require_owner(receipt, session_csrf_hash)
        else:
            user = CHAT_REPOSITORY.add(db, "user", message, client_turn_id=client_turn_id)
            receipt = {"client_turn_id": client_turn_id, "session_key": coach_session_key(session_csrf_hash),
                       "user_message_id": user["id"], "status": "running", "command_receipts": [],
                       "ai_provider": ai_provider, "model": model}
            db.execute("INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, target_system, status, receipt, created_at, updated_at) VALUES (?, ?, ?, ?, 'none', 'running', ?, ?, ?)",
                       (uuid.uuid4().hex, client_turn_id, conversation_id, json.dumps(intent), json.dumps(receipt), utc_now(), utc_now()))
    return receipt


def _send_structured_coach_response(
    payload: dict[str, Any],
    *,
    resume_id: str,
    checkpoint: Any,
    on_delta: Any,
    on_text_delta: Any,
    cancel_event: threading.Event | None,
    background_owned: bool,
    ai_provider: str,
) -> dict[str, Any]:
    if background_owned and on_text_delta is None:
        return responses_background_request(
            payload,
            response_id=resume_id or None,
            on_response_id=checkpoint,
            cancel_event=cancel_event,
        )
    if on_text_delta is None:
        return responses_request(payload)
    return responses_stream_request(
        payload,
        on_delta,
        cancel_event,
        on_response_id=checkpoint if background_owned and ai_provider == "openai" else None,
    )


def coach_conversation_recovery_service() -> CoachConversationRecoveryService:
    """Compose the durable recovery owner from concrete storage services."""
    return CoachConversationRecoveryService(
        database_manager(), DB_LOCK, KEY_VALUE_REPOSITORY, coach_job_store(), LOGGER,
    )


def _resume_background_coach_response(
    exc: AppError, payload: dict[str, Any], resume_id: str, checkpoint: Callable[[str], None],
    cancel_event: threading.Event | None, *, background_owned: bool, ai_provider: str,
) -> dict[str, Any] | None:
    resumable = (
        background_owned and ai_provider == "openai" and resume_id
        and exc.reason in {"provider_unavailable", "provider_timeout", "invalid_response"}
        and (cancel_event is None or not cancel_event.is_set())
    )
    if not resumable:
        return None
    return responses_background_request(
        payload, response_id=resume_id, on_response_id=checkpoint, cancel_event=cancel_event,
    )


def coach_response_retry_policy() -> CoachResponseRetryPolicy:
    """Compose retry policy with the application logger."""
    return CoachResponseRetryPolicy(LOGGER)


@dataclass(frozen=True)
class _StructuredCoachResponseAttemptContext:
    request_payload: dict[str, Any]
    context: dict[str, Any]
    message: str
    command_receipts: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    client_turn_id: str
    recovery_state: dict[str, bool]


def _structured_coach_response_attempt(
    payload: dict[str, Any],
    *,
    attempt_context: _StructuredCoachResponseAttemptContext,
    ai_provider: str,
    background_owned: bool,
    on_text_delta: Any,
    cancel_event: threading.Event | None,
    state: dict[str, Any],
    attempt: int,
    checkpoint: Any,
    on_delta: Any,
) -> dict[str, Any] | None:
    try:
        return _send_structured_coach_response(
            payload,
            resume_id=state["resume_id"],
            checkpoint=checkpoint,
            on_delta=on_delta,
            on_text_delta=on_text_delta,
            cancel_event=cancel_event,
            background_owned=background_owned,
            ai_provider=ai_provider,
        )
    except AppError as exc:
        resumed = _resume_background_coach_response(
            exc, payload, state["resume_id"], checkpoint, cancel_event,
            background_owned=background_owned, ai_provider=ai_provider,
        )
        if resumed is not None:
            return resumed
        if coach_conversation_recovery_service().recover_if_invalid(
            exc, payload, attempt_context.request_payload, context=attempt_context.context,
            message=attempt_context.message, command_receipts=attempt_context.command_receipts,
            attachments=attempt_context.attachments, client_turn_id=attempt_context.client_turn_id,
            ai_provider=ai_provider, recovery_state=attempt_context.recovery_state,
            request_delta_emitted=state["request_delta_emitted"], attempt=attempt,
        ):
            state["resume_id"] = ""
            return None
        retry_policy = coach_response_retry_policy()
        delay = retry_policy.retry_delay(
            exc, ai_provider=ai_provider, attempt=attempt,
            request_delta_emitted=state["request_delta_emitted"],
        )
        if delay is None:
            raise
        state["resume_id"] = ""
        retry_policy.wait(delay, cancel_event, attempt)
        return None


def _structured_coach_response(
    payload: dict[str, Any],
    *,
    request_payload: dict[str, Any],
    context: dict[str, Any],
    message: str,
    command_receipts: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    client_turn_id: str,
    ai_provider: str,
    background_owned: bool,
    on_text_delta: Any,
    cancel_event: threading.Event | None,
    recovery_state: dict[str, bool],
    resume_id: str = "",
) -> dict[str, Any]:
    state: dict[str, Any] = {"request_delta_emitted": False, "resume_id": resume_id}
    attempt_context = _StructuredCoachResponseAttemptContext(
        request_payload=request_payload,
        context=context,
        message=message,
        command_receipts=command_receipts,
        attachments=attachments,
        client_turn_id=client_turn_id,
        recovery_state=recovery_state,
    )

    def on_delta(delta: str) -> None:
        state["request_delta_emitted"] = True
        if on_text_delta is not None:
            on_text_delta(delta)

    def checkpoint(response_id: str) -> None:
        state["resume_id"] = response_id
        coach_job_store().merge_receipt(client_turn_id, {
            "status": "running",
            "phase": "waiting_openai",
            "openai_response_id": response_id,
            "pending_tool_outputs": [],
            "response_input": payload["input"] if isinstance(payload["input"], list) else None,
            "previous_response_id": payload.get("previous_response_id"),
        })

    for attempt in range(3):
        _raise_chat_cancelled(cancel_event)
        response = _structured_coach_response_attempt(
            payload,
            attempt_context=attempt_context,
            ai_provider=ai_provider,
            background_owned=background_owned,
            on_text_delta=on_text_delta,
            cancel_event=cancel_event,
            state=state,
            attempt=attempt,
            checkpoint=checkpoint,
            on_delta=on_delta,
        )
        if response is not None:
            return response
    raise AppError(502, "Der KI-Dienst konnte die Antwort nicht fertigstellen.", reason="response_failed")


@dataclass
class _StructuredCoachRoundState:
    tools: list[dict[str, Any]]
    command_receipts: list[dict[str, Any]]
    sync_job_ids: list[str]
    context: dict[str, Any]
    allow_mutations: bool
    conversation_id: str
    client_turn_id: str
    session_csrf_hash: str
    cancel_event: threading.Event | None
    ai_provider: str
    request_payload: dict[str, Any]
    model_instructions: str
    message: str
    attachments: list[dict[str, Any]]
    background_owned: bool
    on_text_delta: Any
    recovery_state: dict[str, bool]


def _execute_structured_coach_tool_call(
    item: dict[str, Any], *, state: _StructuredCoachRoundState, question: str, cancelled: bool,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    name = str(item.get("name") or "")
    call_id = str(item.get("call_id") or "")
    action = {"operation": name, "authorization_scope": []}
    effect_key = coach_action_hash({"tool": name, "arguments": item.get("arguments")})
    step_key = name
    repair_key = scope_repair_key = request_binding_key = plan_effect_key = None
    model_instructions = state.model_instructions
    try:
        metadata = structured_tool_call_metadata(item, state.tools, state.command_receipts)
        name, call_id = metadata["name"], metadata["call_id"]
        action = metadata["action"]
        effect_key, step_key = metadata["effect_key"], metadata["step_key"]
        repair_key = metadata["repair_key"]
        scope_repair_key = metadata["scope_repair_key"]
        request_binding_key = metadata["request_binding_key"]
        plan_effect_key = metadata["plan_effect_key"]
        cached = coach_structured_tool_replay_service().lookup(metadata, state.command_receipts)
        if cached:
            result = cached["result"]
        else:
            action = coach_structured_tool_preparation_service().prepare(
                metadata, state.command_receipts, question=question, cancelled=cancelled,
                context=state.context, allow_mutations=state.allow_mutations,
            )
            local_transaction = name not in {"start_provider_refresh", "apply_adaptive_replan"}
            with (DB_LOCK if local_transaction else nullcontext()), (database() if local_transaction else nullcontext()):
                result = coach_structured_tool_execution_service().execute(
                    metadata, action=action, context=state.context, conversation_id=state.conversation_id,
                    client_turn_id=state.client_turn_id, session_csrf_hash=state.session_csrf_hash,
                    sync_job_ids=state.sync_job_ids, cancel_event=state.cancel_event,
                )
                state.command_receipts.append({
                    "call_id": call_id, "tool": name, "effect_key": effect_key, "step_key": step_key,
                    "repair_key": repair_key, "scope_repair_key": scope_repair_key,
                    "request_binding_key": request_binding_key, "plan_effect_key": plan_effect_key,
                    "request": action.get("request"), "result": result,
                })
                coach_job_store().merge_receipt(state.client_turn_id, {"command_receipts": state.command_receipts, "sync_job_ids": state.sync_job_ids})
        if result.get("synchronous_refresh") or (name == "get_sync_job" and result.get("ok")):
            model_instructions = coach_training_context_service().build() + "\n\n" + COACH_DIALOGUE_INSTRUCTIONS
        if action.get("period"):
            scope = coach_execution_scope(action, background_horizon_days=COACH_BACKGROUND_HORIZON_DAYS)
            state.request_payload["max_output_tokens"] = COACH_LONG_PLAN_MAX_OUTPUT_TOKENS if scope["planning"] else COACH_DEFAULT_MAX_OUTPUT_TOKENS
            coach_job_store().merge_receipt(state.client_turn_id, {"plan_scope": scope})
    except (AppError, ValueError, TypeError, KeyError) as exc:
        result = coach_structured_tool_failure_service().project(
            exc, name=name, call_id=call_id, effect_key=effect_key, step_key=step_key,
            repair_key=repair_key, scope_repair_key=scope_repair_key,
            request_binding_key=request_binding_key, plan_effect_key=plan_effect_key,
            action=action, command_receipts=state.command_receipts,
        )
    state.model_instructions = model_instructions
    return name, call_id, result, action


def _structured_coach_followup_response(
    response: dict[str, Any], *, outputs: list[dict[str, Any]], state: _StructuredCoachRoundState,
    question: str, cancelled: bool, rounds: int,
) -> dict[str, Any]:
    followup = {**state.request_payload, "instructions": state.model_instructions, "input": outputs,
                "tool_choice": "none" if question or cancelled or rounds >= COACH_TOOL_MAX_ROUNDS else "auto"}
    if state.ai_provider == "openai" and response.get("id") and not followup.get("conversation"):
        followup["previous_response_id"] = response["id"]
    return _structured_coach_response(
        followup, request_payload=state.request_payload, context=state.context, message=state.message,
        command_receipts=state.command_receipts, attachments=state.attachments, client_turn_id=state.client_turn_id,
        ai_provider=state.ai_provider, background_owned=state.background_owned, on_text_delta=state.on_text_delta,
        cancel_event=state.cancel_event, recovery_state=state.recovery_state,
    )


def _run_structured_coach_tool_rounds(
    response: dict[str, Any], *, rounds: int, question: str, cancelled: bool,
    state: _StructuredCoachRoundState,
) -> tuple[dict[str, Any], int, str, bool, str]:
    journal = coach_structured_tool_round_journal()
    while rounds < COACH_TOOL_MAX_ROUNDS:
        calls = journal.function_calls(response)
        if not calls:
            break
        pending = journal.start_round(state.client_turn_id, calls)
        outputs = []
        for item in calls:
            _raise_chat_cancelled(state.cancel_event)
            name, call_id, result, _ = _execute_structured_coach_tool_call(
                item, state=state, question=question, cancelled=cancelled,
            )
            question, cancelled, pending = journal.record_output(
                client_turn_id=state.client_turn_id, name=name, call_id=call_id,
                result=result, outputs=outputs, pending=pending,
                command_receipts=state.command_receipts,
                question=question, cancelled=cancelled,
            )
        rounds += 1
        journal.finish_round(state.client_turn_id, rounds)
        response = _structured_coach_followup_response(
            response, outputs=outputs, state=state, question=question, cancelled=cancelled, rounds=rounds,
        )
        journal.clear_outputs(state.client_turn_id)
        if question or cancelled:
            break
    return response, rounds, question, cancelled, state.model_instructions


def _structured_coach_turn_request(
    message: str, *, intent: dict[str, Any], conversation_id: str, client_turn_id: str,
    session_csrf_hash: str, background_job: bool, ai_provider: str, model: str | None,
    thinking_level: str | None, on_text_delta: Any, cancel_event: threading.Event | None,
) -> dict[str, Any]:
    receipt = _structured_coach_receipt(
        message, intent=intent, conversation_id=conversation_id, client_turn_id=client_turn_id,
        session_csrf_hash=session_csrf_hash, ai_provider=ai_provider, model=model,
    )
    attachment_context = coach_attachment_context_service()
    attachments, has_prior_openai_attachments = attachment_context.load_for_receipt(receipt)
    retain_openai_attachment_context = ai_provider == "openai" and bool(attachments or has_prior_openai_attachments)
    background_owned = background_job and receipt.get("mode") == "background"
    context = coach_dialogue_read_service().context(client_turn_id)
    attachment_context.add_evidence(context)
    allow_mutations = intent.get("allow_mutations", True)
    command_receipts = list(receipt.get("command_receipts") or [])
    sync_job_ids = list(receipt.get("sync_job_ids") or [])
    tools = COACH_DIALOGUE_TOOLS if allow_mutations else [tool for tool in COACH_DIALOGUE_TOOLS if tool["name"] in STRUCTURED_READ_ONLY_TOOLS]
    model_instructions, request_payload = coach_request_payload_service().build(
        message=message, context=context, command_receipts=command_receipts, tools=tools,
        allow_mutations=allow_mutations, ai_provider=ai_provider, model=model,
        thinking_level=thinking_level, conversation_id=conversation_id, attachments=attachments,
        retain_openai_attachment_context=retain_openai_attachment_context,
        has_prior_openai_attachments=has_prior_openai_attachments,
    )
    recovery_state = {"conversation_recovered": False}
    resume_id = _apply_structured_coach_replay(
        receipt, request_payload, ai_provider=ai_provider, background_owned=background_owned,
    )
    response = _structured_coach_response(
        request_payload, request_payload=request_payload, context=context, message=message,
        command_receipts=command_receipts, attachments=attachments, client_turn_id=client_turn_id,
        ai_provider=ai_provider, background_owned=background_owned, on_text_delta=on_text_delta,
        cancel_event=cancel_event, recovery_state=recovery_state, resume_id=resume_id,
    )
    return {
        "receipt": receipt, "context": context, "command_receipts": command_receipts,
        "sync_job_ids": sync_job_ids, "allow_mutations": allow_mutations, "tools": tools,
        "model_instructions": model_instructions, "request_payload": request_payload,
        "recovery_state": recovery_state, "attachments": attachments,
        "background_owned": background_owned, "response": response,
    }


def _apply_structured_coach_replay(
    receipt: dict[str, Any], request_payload: dict[str, Any], *, ai_provider: str, background_owned: bool,
) -> str:
    resume_id = str(receipt.get("openai_response_id") or "") if background_owned and ai_provider == "openai" else ""
    if resume_id and receipt.get("response_input"):
        request_payload["input"] = receipt["response_input"]
        if receipt.get("previous_response_id") and not request_payload.get("conversation"):
            request_payload["previous_response_id"] = receipt["previous_response_id"]
    if background_owned and receipt.get("pending_tool_outputs"):
        request_payload["input"] = receipt["pending_tool_outputs"]
        if ai_provider == "openai" and resume_id and not request_payload.get("conversation"):
            request_payload["previous_response_id"] = resume_id
        resume_id = ""
    return resume_id


def _structured_coach_final_receipt(
    receipt: dict[str, Any], *, status: str, response: dict[str, Any], client_turn_id: str,
    command_receipts: list[dict[str, Any]], sync_job_ids: list[str], intent: dict[str, Any],
    rounds: int, failures: list[dict[str, Any]], awaiting_clarification: bool,
) -> dict[str, Any]:
    final_receipt = {
        **receipt,
        "status": status,
        "awaiting_clarification": awaiting_clarification,
        "response_status": response.get("status") if response.get("status") in {"completed", "incomplete", "failed", "cancelled"} else None,
        "client_turn_id": client_turn_id, "command_receipts": command_receipts, "sync_job_ids": sync_job_ids,
        "intent": intent, "tool_rounds": rounds, "pending_operations": sorted({entry["tool"] for entry in failures}),
        "proposed_actions": [entry["result"]["proposed_action"] for entry in command_receipts if entry.get("result", {}).get("proposed_action")],
    }
    for key in ("openai_response_id", "pending_tool_outputs", "pending_tool_calls", "response_input", "previous_response_id"):
        final_receipt.pop(key, None)
    return final_receipt


def _persist_structured_coach_final_receipt(
    final_receipt: dict[str, Any], *, client_turn_id: str, command_receipts: list[dict[str, Any]],
    ai_provider: str,
) -> dict[str, Any]:
    with DB_LOCK, database() as db:
        current_command = db.execute(
            "SELECT status, receipt FROM coach_commands WHERE client_turn_id=?", (client_turn_id,),
        ).fetchone()
        if current_command and current_command["status"] == "completed":
            return command_receipt(current_command["receipt"])
        final_receipt["message"] = CHAT_REPOSITORY.add(db, "assistant", final_receipt["text"], client_turn_id=client_turn_id)
        for step in command_receipts:
            if step["tool"] == "preview_adaptive_replan" and step.get("result", {}).get("ok"):
                preview_id = step["result"].get("id")
                preview_row = db.execute("SELECT payload FROM plan_adjustments WHERE id=? AND status='preview'", (preview_id,)).fetchone()
                if preview_row:
                    preview_payload = json.loads(preview_row["payload"])
                    preview_payload["published_message_id"] = final_receipt["message"]["id"]
                    db.execute("UPDATE plan_adjustments SET payload=? WHERE id=?", (json.dumps(preview_payload, ensure_ascii=False), preview_id))
        set_kv("last_coach_ai_provider", ai_provider, db)
        db.execute(UPDATE_COMMAND_RECEIPT_SQL, (json.dumps({key: value for key, value in final_receipt.items() if key != "text"}, ensure_ascii=False), utc_now(), client_turn_id))
    final_receipt.pop("text", None)
    runtime_events.STATE_EVENT_BUFFER.publish("coach", {"message_id": final_receipt["message"]["id"], "role": "assistant", "client_turn_id": client_turn_id})
    return final_receipt


def _chat_with_structured_coach_impl(
    message: str, *, intent: dict[str, Any], conversation_id: str, client_turn_id: str,
    on_text_delta: Any = None, cancel_event: threading.Event | None = None,
    session_csrf_hash: str = "", background_job: bool = False,
    ai_provider: str | None = None, model: str | None = None, thinking_level: str | None = None,
) -> dict[str, Any]:
    ai_provider = ai_provider or SETTINGS.selected_ai_provider()
    state = _structured_coach_turn_request(
        message,
        intent=intent,
        conversation_id=conversation_id,
        client_turn_id=client_turn_id,
        session_csrf_hash=session_csrf_hash,
        background_job=background_job,
        ai_provider=ai_provider,
        model=model,
        thinking_level=thinking_level,
        on_text_delta=on_text_delta,
        cancel_event=cancel_event,
    )
    receipt = state["receipt"]
    context = state["context"]
    command_receipts = state["command_receipts"]
    sync_job_ids = state["sync_job_ids"]
    allow_mutations = state["allow_mutations"]
    tools = state["tools"]
    request_payload = state["request_payload"]
    model_instructions = state["model_instructions"]
    attachments = state["attachments"]
    background_owned = state["background_owned"]
    recovery_state = state["recovery_state"]
    response = state["response"]
    round_state = _StructuredCoachRoundState(
        tools=tools, command_receipts=command_receipts, sync_job_ids=sync_job_ids,
        context=context, allow_mutations=allow_mutations, conversation_id=conversation_id,
        client_turn_id=client_turn_id, session_csrf_hash=session_csrf_hash,
        cancel_event=cancel_event, ai_provider=ai_provider, request_payload=request_payload,
        model_instructions=model_instructions, message=message, attachments=attachments,
        background_owned=background_owned, on_text_delta=on_text_delta, recovery_state=recovery_state,
    )
    response, rounds, question, cancelled, model_instructions = _run_structured_coach_tool_rounds(
        response,
        rounds=int(receipt.get("tool_rounds") or 0),
        question="",
        cancelled=False,
        state=round_state,
    )
    status, text, failures = coach_structured_outcome_service().finalize(
        response,
        command_receipts,
        question=question,
        cancelled=cancelled,
        allow_mutations=allow_mutations,
        context=context,
        message=message,
    )
    final_receipt = _structured_coach_final_receipt(
        receipt,
        status=status,
        response=response,
        client_turn_id=client_turn_id,
        command_receipts=command_receipts,
        sync_job_ids=sync_job_ids,
        intent=intent,
        rounds=rounds,
        failures=failures,
        awaiting_clarification=bool(question),
    )
    final_receipt["text"] = text
    return _persist_structured_coach_final_receipt(
        final_receipt,
        client_turn_id=client_turn_id,
        command_receipts=command_receipts,
        ai_provider=ai_provider,
    )




def _chat_with_structured_coach(*args: Any, **kwargs: Any) -> dict[str, Any]:
    intent = kwargs.get("intent") if isinstance(kwargs.get("intent"), dict) else {}
    client_turn_id = str(kwargs.get("client_turn_id") or "")
    try:
        receipt = _chat_with_structured_coach_impl(*args, **kwargs)
    except Exception as exc:
        if isinstance(exc, AppError) and exc.reason in {"command_scope_denied", "client_turn_in_progress"}:
            raise
        LOGGER.warning("Coach command failed", extra={"event": "coach_command_failed", "context": coach_error_metadata(exc, ROOT)})
        receipt = coach_turn_failure_service().persist(client_turn_id, intent, exc)
        if not receipt:
            raise
    return {key: value for key, value in receipt.items() if key != "session_key"}


def chat_stream_status(session_csrf_hash: str) -> dict[str, Any]:
    """Return the status of the chat operation belonging to this session."""
    attached = coach_streams.CHAT_STREAM_REGISTRY.attached_status(session_csrf_hash)
    if attached:
        return attached
    job = coach_job_submission_service().active(session_csrf_hash)
    if not job:
        return {"status": "idle", "operation_id": None}
    receipt = job["receipt"]
    return {
        "status": "running",
        "operation_id": receipt.get("operation_id"),
        "mode": "background",
        "phase": receipt.get("phase") or job.get("status"),
        "plan_scope": receipt.get("plan_scope") or {},
    }


def _validated_chat_request(message: str, client_turn_id: str, cancel_event: threading.Event | None) -> tuple[str, str]:
    _raise_chat_cancelled(cancel_event)
    message = message.strip()
    if not message:
        raise AppError(400, "Die Nachricht darf nicht leer sein.")
    if len(message) > 12_000:
        raise AppError(400, "Die Nachricht ist zu lang.")
    client_turn_id = str(client_turn_id).strip()
    if not client_turn_id or len(client_turn_id) > 120:
        raise AppError(400, "client_turn_id muss eine begrenzte, nicht leere Kennung sein.", reason="invalid_client_turn")
    return message, client_turn_id


def _recover_stale_chat_command(
    db: Any, existing_command: dict[str, Any], background_owned: bool, client_turn_id: str,
) -> dict[str, Any]:
    if not existing_command or existing_command.get("status") != "running" or background_owned:
        return existing_command
    age = db.execute(
        "SELECT (julianday('now') - julianday(?)) * 86400 AS age", (existing_command.get("updated_at"),)
    ).fetchone()
    if float((age or {}).get("age") or 0) <= COACH_COMMAND_STALE_SECONDS:
        return existing_command
    try:
        recovered = json.loads(existing_command.get("receipt") or "{}")
    except (TypeError, ValueError):
        recovered = {}
    if not isinstance(recovered, dict):
        recovered = {}
    recovered.update({"status": "failed", "error": "Die vorherige Coach-Verarbeitung wurde nach einem Prozessabbruch wieder freigegeben."})
    db.execute(
        "UPDATE coach_commands SET status='completed', receipt=?, updated_at=? WHERE client_turn_id=? AND status='running'",
        (json.dumps(recovered, ensure_ascii=False, separators=(",", ":")), utc_now(), client_turn_id),
    )
    return {"status": "completed", "receipt": json.dumps(recovered)}


def _chat_command_state(
    client_turn_id: str, session_csrf_hash: str, background_job: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
    with DB_LOCK, database() as db:
        existing_command = db.execute(
            "SELECT conversation_id, intent, receipt, status, updated_at FROM coach_commands WHERE client_turn_id=?",
            (client_turn_id,),
        ).fetchone()
        background_receipt = command_receipt((existing_command or {}).get("receipt"))
        if existing_command:
            coach_command_receipt_service().require_owner(background_receipt, session_csrf_hash)
        background_owned = bool(background_job and background_receipt.get("mode") == "background")
        existing_command = _recover_stale_chat_command(db, existing_command, background_owned, client_turn_id)
    return existing_command, background_receipt, background_owned


def _chat_provider_settings(background_receipt: dict[str, Any]) -> tuple[str, str, str]:
    ai_provider = str(background_receipt.get("ai_provider") or SETTINGS.selected_ai_provider()).casefold()
    if ai_provider not in {"openai", "gemini"}:
        ai_provider = SETTINGS.selected_ai_provider()
    model = str(background_receipt.get("model") or SETTINGS.selected_model(ai_provider))
    thinking_level = str(background_receipt.get("thinking_level") or SETTINGS.selected_thinking_level()).casefold()
    if thinking_level not in {"low", "medium", "high"}:
        thinking_level = SETTINGS.selected_thinking_level()
    return ai_provider, model, thinking_level


def _resume_background_chat_command(
    background_owned: bool, conversation_id: str,
    structured_intent: dict[str, Any], client_turn_id: str,
) -> None:
    if not background_owned:
        return
    with DB_LOCK, database() as db:
        db.execute(
            "UPDATE coach_commands SET conversation_id=?, intent=?, status='running', updated_at=? WHERE client_turn_id=?",
            (conversation_id, json.dumps(structured_intent), utc_now(), client_turn_id),
        )


@runtime_maintenance.maintenance_operation
@serialise_conversation
def chat_with_coach(message: str, *, allow_mutations: bool = True, on_text_delta: Any = None, cancel_event: threading.Event | None = None, session_csrf_hash: str = "", client_turn_id: str, background_job: bool = False) -> dict[str, Any]:
    message, client_turn_id = _validated_chat_request(message, client_turn_id, cancel_event)
    existing_command, background_receipt, background_owned = _chat_command_state(
        client_turn_id, session_csrf_hash, background_job,
    )
    if existing_command and existing_command.get("status") == "completed" and existing_command.get("receipt"):
        try:
            return coach_command_receipt_service().read(client_turn_id, session_csrf_hash)
        except (TypeError, ValueError):
            pass
    if existing_command and not background_owned:
        raise AppError(409, "Diese Coach-Nachricht wird bereits verarbeitet.", reason="client_turn_in_progress")
    ai_provider, model, thinking_level = _chat_provider_settings(background_receipt)
    existing_conversation_id = str((existing_command or {}).get("conversation_id") or "")
    conversation_id = existing_conversation_id or coach_conversation_provision_service().ensure(ai_provider)
    structured_intent = {"allow_mutations": allow_mutations}
    _resume_background_chat_command(background_owned, conversation_id, structured_intent, client_turn_id)
    return _chat_with_structured_coach(
        message, intent=structured_intent, conversation_id=conversation_id, client_turn_id=client_turn_id,
        session_csrf_hash=session_csrf_hash, on_text_delta=on_text_delta, cancel_event=cancel_event,
        background_job=background_job, ai_provider=ai_provider, model=model, thinking_level=thinking_level,
    )


def _background_coach_stream_delta(operation_id: str, text: str) -> None:
    coach_streams.CHAT_STREAM_REGISTRY.publish(operation_id, "delta", {"text": text})


def _background_coach_delta_callback(
    operation_id: str, receipt: dict[str, Any], stream_attached: bool,
) -> Any:
    if not stream_attached or receipt.get("openai_response_id"):
        return None
    return lambda text: _background_coach_stream_delta(operation_id, text)


def _background_coach_stream_receipt(operation_id: str, value: dict[str, Any]) -> None:
    coach_streams.CHAT_STREAM_REGISTRY.publish(
        operation_id, "completed", {key: item for key, item in value.items() if key != "session_key"},
    )


def _background_coach_cancel_event(operation_id: str, client_turn_id: str) -> threading.Event:
    cancel_event = coach_streams.CHAT_STREAM_REGISTRY.get_or_create_background_event(operation_id)
    with DB_LOCK, database() as db:
        current = db.execute(SELECT_COMMAND_RECEIPT_SQL, (client_turn_id,)).fetchone()
    if current and command_receipt(current["receipt"]).get("cancel_requested"):
        coach_streams.CHAT_STREAM_REGISTRY.cancel_background_event(operation_id)
    return cancel_event


def _persist_completed_morning_coach_job(client_turn_id: str) -> dict[str, Any] | None:
    with DB_LOCK, database() as db:
        set_kv("morning_checkin_date", local_now().date().isoformat(), db)
        set_kv("morning_checkin_status", "ready", db)
    quick_actions = coach_quick_actions_service().state()
    with DB_LOCK, database() as db:
        row = db.execute(SELECT_COMMAND_RECEIPT_SQL, (client_turn_id,)).fetchone()
        completed_receipt = command_receipt((row or {}).get("receipt"))
        completed_receipt["coach_quick_actions"] = quick_actions
        db.execute(
            "UPDATE coach_commands SET receipt=?, updated_at=? WHERE client_turn_id=? AND status='completed'",
            (json.dumps(completed_receipt, ensure_ascii=False, separators=(",", ":")), utc_now(), client_turn_id),
        )
    return completed_receipt


def _execute_background_coach_job(
    job: dict[str, Any], receipt: dict[str, Any], operation_id: str, client_turn_id: str,
    session_csrf_hash: str, cancel_event: threading.Event, stream_attached: bool,
) -> dict[str, Any]:
    if not session_csrf_hash:
        raise AppError(401, "Die Sitzung des Coach-Auftrags ist abgelaufen.", reason="session_expired")
    message = coach_job_store().message(job)
    worker_phase = {"status": "running"}
    if not receipt.get("openai_response_id"):
        worker_phase["phase"] = "preparing"
    coach_job_store().merge_receipt(client_turn_id, worker_phase)
    if receipt.get("request_kind") == "morning_checkin":
        manual_morning_checkin_service().prepare()
    result = chat_with_coach(
        message,
        on_text_delta=_background_coach_delta_callback(operation_id, receipt, stream_attached),
        cancel_event=cancel_event,
        session_csrf_hash=session_csrf_hash,
        client_turn_id=client_turn_id,
        background_job=True,
    )
    if (
        receipt.get("request_kind") == "morning_checkin"
        and result.get("status") == "completed"
        and result.get("message")
        and not result.get("awaiting_clarification")
    ):
        result = _persist_completed_morning_coach_job(client_turn_id) or result
    return result


def _handle_background_coach_error(
    client_turn_id: str, operation_id: str, exc: AppError,
) -> None:
    if exc.reason in {"chat_queue_full", "chat_request_timeout"}:
        coach_job_store().requeue(client_turn_id, exc.reason)
        LOGGER.warning(
            "Persistent Coach background job requeued after contention",
            extra={"event": "coach_background_job_requeued", "context": {"operation_id": operation_id, "reason": exc.reason}},
        )
        coach_streams.CHAT_STREAM_REGISTRY.publish(operation_id, "background", {
            "status": "queued", "mode": "background", "operation_id": operation_id,
        })
        return
    failed = coach_turn_failure_service().persist(client_turn_id, {}, exc)
    if failed:
        _background_coach_stream_receipt(operation_id, failed)
        return
    coach_streams.CHAT_STREAM_REGISTRY.publish(operation_id, "error", {
        "reason": exc.reason or "request_failed", "message": REDACTOR.redact_text(exc.message)[:1000],
    })


def _handle_background_coach_exception(client_turn_id: str, operation_id: str, exc: Exception) -> None:
    failed = coach_turn_failure_service().persist(client_turn_id, {}, exc)
    if failed:
        _background_coach_stream_receipt(operation_id, failed)
    else:
        coach_streams.CHAT_STREAM_REGISTRY.publish(operation_id, "error", {
            "reason": "internal_error", "message": INTERNAL_SERVER_ERROR,
        })
    LOGGER.exception(
        "Persistent Coach background job failed",
        extra={"event": "coach_background_job_failed", "context": {"operation_id": operation_id, "error_code": sync_observation.operation_error_code(exc)}},
    )


@runtime_maintenance.claimed_maintenance_operation
def _run_background_coach_job(job: dict[str, Any]) -> None:
    receipt = job.get("receipt") if isinstance(job.get("receipt"), dict) else {}
    operation_id = str(receipt.get("operation_id") or "")
    client_turn_id = str(job.get("client_turn_id") or "")
    session_csrf_hash = session_auth_service().restore_coach_session_csrf_hash(
        receipt.get("session_key")
    )
    cancel_event = _background_coach_cancel_event(operation_id, client_turn_id)
    stream_attached = coach_streams.CHAT_STREAM_REGISTRY.events(session_csrf_hash, operation_id) is not None
    try:
        result = _execute_background_coach_job(
            job, receipt, operation_id, client_turn_id, session_csrf_hash, cancel_event, stream_attached,
        )
        _background_coach_stream_receipt(operation_id, result)
    except AppError as exc:
        _handle_background_coach_error(client_turn_id, operation_id, exc)
    except Exception as exc:
        _handle_background_coach_exception(client_turn_id, operation_id, exc)
    finally:
        coach_streams.CHAT_STREAM_REGISTRY.remove_background_event(operation_id)


def _coach_job_worker_loop() -> None:
    while not COACH_JOB_STOP.is_set():
        try:
            with runtime_maintenance.MAINTENANCE_GATE.operation():
                job = coach_job_store().claim()
                if job:
                    _run_background_coach_job(job)
                    continue
        except AppError as exc:
            if exc.reason != "maintenance":
                raise
        COACH_JOB_WAKE.wait(5)
        COACH_JOB_WAKE.clear()


def start_coach_job_worker() -> None:
    """Start the single durable Coach worker after database initialization."""
    global COACH_JOB_WORKER
    with COACH_JOB_WORKER_LOCK:
        if COACH_JOB_WORKER is not None and COACH_JOB_WORKER.is_alive():
            return
        COACH_JOB_STOP.clear()
        COACH_JOB_WORKER = threading.Thread(target=_coach_job_worker_loop, name="coach-job-worker", daemon=True)
        COACH_JOB_WORKER.start()


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
        database=database,
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
        COACH_JOB_WAKE,
        DatabaseRestoreConfig(DATA_DIR, DB_PATH),
        REDACTOR.redact_text,
    )


def readiness_service() -> ReadinessService:
    """Compose the public readiness probe from its concrete dependencies."""
    return ReadinessService(
        database_manager, DB_LOCK, DATA_DIR, runtime_maintenance.MAINTENANCE_GATE
    )


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

    def _handle_public_get(self, path: str) -> bool:
        if path == "/api/health":
            self.send_json(200, {"status": "ok", "maintenance": runtime_maintenance.MAINTENANCE_GATE.state()})
        elif path == "/api/readiness":
            readiness = readiness_service().state()
            self.send_json(200 if readiness["ready"] else 503, readiness)
        elif path == "/api/auth/status":
            session = self.auth_service.authenticated_session(self)
            result = {"authenticated": bool(session), "maintenance": runtime_maintenance.MAINTENANCE_GATE.state()}
            self.send_json(200, result)
        elif path == "/api/bootstrap":
            self.auth_service.require_auth(self)
            self.send_json(200, public_bootstrap_service().read())
        else:
            return False
        return True

    def _handle_sync_get(self, path: str) -> bool:
        if path == "/api/state/events":
            self.auth_service.require_auth(self)
            StateEventTransport(runtime_events.STATE_EVENT_BUFFER).handle(
                self.path,
                send_headers=self.send_sse_headers,
                send_event=self.send_sse_event,
                set_connection_timeout=self.connection.settimeout,
            )
        elif match := SYNC_JOB_RE.match(path):
            self.auth_service.require_auth(self)
            self.send_json(200, sync_job_queue_service().state(match.group(1)))
        elif path == "/api/sync/status":
            self.auth_service.require_auth(self)
            self.send_json(200, sync_public_state_service().state())
        elif path == "/api/activities":
            self.auth_service.require_auth(self)
            query = parse_qs(urlparse(self.path).query)
            self.send_json(200, activity_read_service().page(
                query.get("cursor", [None])[0], query.get("limit", [None])[0],
                query.get("days", [ALL_SYNC_DAYS])[0],
                today=local_now().date(),
            ))
        else:
            return False
        return True

    def _handle_coach_get(self, path: str) -> bool:
        if path == "/api/chat/history":
            session = self.auth_service.require_auth(self)
            query = parse_qs(urlparse(self.path).query)
            self.send_json(200, chat_history_page_service().page(
                query.get("cursor", [None])[0], query.get("limit", [None])[0],
                query.get("q", [None])[0], session_csrf_hash=session["csrf_hash"],
            ))
        elif path == "/api/chat/receipt":
            session = self.auth_service.require_auth(self)
            query = parse_qs(urlparse(self.path).query)
            self.send_json(200, coach_command_receipt_service().read(
                query.get("client_turn_id", [None])[0], session["csrf_hash"],
            ))
        elif path == "/api/chat/status":
            session = self.auth_service.require_auth(self)
            self.send_json(200, chat_stream_status(session["csrf_hash"]))
        else:
            return False
        return True

    def _handle_training_get(self, path: str) -> bool:
        if path == "/api/plan":
            self.auth_service.require_auth(self)
            query = parse_qs(urlparse(self.path).query)
            self.send_json(200, public_plan_state_service().read(
                local_only=query.get("local", ["0"])[0] == "1"
            ))
        elif path == "/api/weather":
            self.auth_service.require_auth(self)
            query = parse_qs(urlparse(self.path).query)
            self.send_json(200, public_weather_state_service().state(local_only=query.get("local", ["0"])[0] == "1"))
        elif path == "/api/library":
            self.auth_service.require_auth(self)
            query = parse_qs(urlparse(self.path).query)
            self.send_json(200, library_page_service().page(query.get("cursor", [None])[0], query.get("limit", [None])[0]))
        elif path == "/api/performance":
            self.auth_service.require_auth(self)
            self.send_json(200, public_performance_state_service().performance_state())
        elif path == "/api/profile":
            self.auth_service.require_auth(self)
            self.send_json(200, {"profile": profile_service().get(), "competitions": competition_service().list(limit=100)})
        elif path == "/api/feedback":
            self.auth_service.require_auth(self)
            self.send_json(200, public_feedback_state_service().feedback_state())
        elif path == "/api/context-preview":
            self.auth_service.require_auth(self)
            self.send_json(200, coach_context_preview_service().preview(SETTINGS.selected_ai_provider()))
        else:
            return False
        return True

    def _handle_diagnostics_get(self, path: str) -> bool:
        if path == "/api/logs":
            self.auth_service.require_auth(self)
            raw_limit = parse_qs(urlparse(self.path).query).get("limit", ["200"])[0]
            try:
                limit = max(1, min(int(raw_limit), 500))
            except ValueError:
                limit = 200
            self.send_json(200, {"entries": recent_log_entries_service().list(limit)})
        elif path == "/api/diagnostics":
            self.auth_service.require_auth(self)
            self.send_json(200, diagnostic_report_service().report())
        elif path == "/api/diagnostics/capture":
            self.auth_service.require_auth(self)
            self.send_json(200, DIAGNOSTIC_CAPTURE.status())
        elif path == "/api/privacy/export":
            self.auth_service.require_auth(self)
            export_stream_transport().stream_privacy_export(self)
        elif path == "/api/privacy/delete/preview":
            self.auth_service.require_auth(self)
            self.send_json(200, privacy_delete_service().preview())
        elif path == "/api/change-history":
            self.auth_service.require_auth(self)
            raw_limit = parse_qs(urlparse(self.path).query).get("limit", ["100"])[0]
            try:
                limit = max(1, min(int(raw_limit), change_history.MAX_ROWS))
            except ValueError:
                limit = 100
            self.send_json(200, {"changes": change_history_service().list(limit)})
        elif path == "/api/privacy/backup":
            self.auth_service.require_auth(self)
            export_stream_transport().stream_database_backup(self)
        else:
            return False
        return True

    def do_GET(self) -> None:
        self.request_id = uuid.uuid4().hex[:12]
        try:
            path = urlparse(self.path).path
            handled = (
                self._handle_public_get(path)
                or self._handle_sync_get(path)
                or self._handle_coach_get(path)
                or self._handle_training_get(path)
                or self._handle_diagnostics_get(path)
            )
            if not handled and path.startswith("/api/"):
                raise AppError(404, NOT_FOUND_ERROR)
            if not handled:
                self.send_static(path)
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
            if path == "/api/login":
                result = self.auth_service.login_user(self, str(self.read_json().get("password") or ""))
                token = result.pop("session_token")
                csrf = result["csrf"]
                self.send_json(200, result, {
                    "Set-Cookie": self.auth_service.session_cookie_headers(token, csrf),
                })
            elif path == "/api/privacy/restore":
                session = self.auth_service.require_auth(self)
                self.auth_service.require_csrf(self, session)
                payload = self.read_body(MAX_BACKUP_BYTES)
                result = database_restore_service().restore(payload)
                self.send_json(200, result, {"Set-Cookie": [
                    self.auth_service.session_cookie_headers(clear=True)[0], self.auth_service.session_cookie_headers(clear=True)[1],
                ]})
            elif path == "/api/logout":
                session = self.auth_service.require_auth(self)
                self.auth_service.require_csrf(self, session)
                with runtime_maintenance.MAINTENANCE_GATE.operation():
                    self.auth_service.logout_user(self)
                self.send_json(200, {"status": "ok"}, {"Set-Cookie": [
                    self.auth_service.session_cookie_headers(clear=True)[0], self.auth_service.session_cookie_headers(clear=True)[1],
                ]})
            else:
                session = self.auth_service.require_auth(self)
                self.auth_service.require_csrf(self, session)
                if path == "/api/chat/cancel":
                    # Cancellation must remain reachable while the streaming
                    # request holds the maintenance gate for its lifetime.
                    payload = self.read_json()
                    self.send_json(200, coach_cancellation_service().cancel(session["csrf_hash"], payload.get("operation_id")))
                else:
                    with runtime_maintenance.MAINTENANCE_GATE.operation():
                        self.handle_authenticated_post(path, session)
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
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive" if persistent else "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.flush()
        except self.client_disconnect_errors as exc:
            self.log_client_disconnect()
            raise ClientDisconnected() from exc

    def send_sse_event(self, event: str, payload: Any, event_id: int | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            prefix = f"id: {event_id}\n" if event_id is not None else ""
            self.wfile.write(f"{prefix}event: {event}\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
        except self.client_disconnect_errors as exc:
            self.log_client_disconnect()
            raise ClientDisconnected() from exc

    def handle_chat_stream(self, session: dict[str, Any]) -> None:  # NOSONAR - SSE lifecycle must remain atomic around durable job ownership
        payload = self.read_json(MAX_REQUEST_BYTES)
        message = str(payload.get("message", ""))
        client_turn_id = str(payload.get("client_turn_id") or "").strip()
        request_kind = payload.get("request_kind")
        if not client_turn_id:
            raise AppError(400, "client_turn_id ist für Coach-Nachrichten erforderlich.", reason="invalid_client_turn")
        operation_id, cancel_event = coach_streams.CHAT_STREAM_REGISTRY.register(session["csrf_hash"])
        client_connected = True

        def send_event(event: str, data: Any) -> None:
            nonlocal client_connected
            if not client_connected:
                return
            try:
                self.send_sse_event(event, data)
            except ClientDisconnected:
                # The browser may be reloaded or moved to another tab while
                # the provider request is still running. The chat operation
                # must finish and persist its answer independently of SSE.
                client_connected = False

        try:
            self.connection.settimeout(OPENAI_RESPONSE_TIMEOUT_SECONDS + 30)
            try:
                self.send_sse_headers(persistent=False)
                send_event("started", {"operation_id": operation_id})
            except ClientDisconnected:
                client_connected = False
            job = coach_job_submission_service().enqueue(
                message, client_turn_id, session["csrf_hash"],
                operation_id=operation_id, cancel_event=cancel_event, request_kind=request_kind, attachments=payload.get("attachments"),
            )
            persisted_operation_id = str(job.get("operation_id") or "")
            if persisted_operation_id and persisted_operation_id != operation_id:
                # A retry after restart may resolve to the original durable
                # operation. The new finite stream cannot own that queue, so
                # return its receipt and let the client resume via polling.
                send_event("background", job)
                return
            events = coach_streams.CHAT_STREAM_REGISTRY.events(session["csrf_hash"], operation_id)
            if events is None:
                send_event("background", job)
            else:
                while True:
                    try:
                        event, data = events.get(timeout=15)
                    except queue.Empty:
                        active = coach_job_submission_service().active(session["csrf_hash"], operation_id)
                        if active:
                            send_event("heartbeat", {"operation_id": operation_id})
                            continue
                        try:
                            send_event("completed", coach_command_receipt_service().read(client_turn_id, session["csrf_hash"]))
                        except AppError as exc:
                            send_event("error", {"reason": exc.reason or "request_failed", "message": REDACTOR.redact_text(exc.message)[:1000]})
                        break
                    send_event(event, data)
                    if event in {"completed", "error", "background"}:
                        break
        except AppError as exc:
            send_event("error", {"reason": exc.reason or "request_failed", "message": REDACTOR.redact_text(exc.message)[:1000]})
        except Exception:
            LOGGER.exception(
                "Unhandled coach stream error",
                extra={"event": "chat_stream_error", "context": {"request_id": self.request_id}},
                exc_info=True,
            )
            send_event("error", {"reason": "internal_error", "message": INTERNAL_SERVER_ERROR})
        finally:
            coach_streams.CHAT_STREAM_REGISTRY.unregister(session["csrf_hash"], operation_id)
            self.close_connection = True

    def _handle_coach_post(self, path: str, session: dict[str, Any]) -> bool:
        if path == "/api/transcribe":
            content_type = self.headers.get("Content-Type", "")
            self.send_json(200, transcribe_audio(self.read_audio_body(), content_type))
        elif path == "/api/planning/commands":
            self.send_json(200, coach_planning_command_service().execute(
                self.read_json(), conversation_id=coach_conversation_provision_service().ensure(), session_csrf_hash=session["csrf_hash"],
            ))
        elif path == "/api/coach/actions/confirm":
            self.send_json(200, coach_proposal_confirmation_service().confirm(
                self.read_json().get("proposal_id"), session["csrf_hash"],
            ))
        elif path == "/api/coach/actions/execute":
            payload = self.read_json()
            self.send_json(200, coach_proposal_execution_service().execute(
                payload.get("action_token"), session["csrf_hash"], payload.get("payload_hash"),
            ))
        elif path == "/api/chat/stream":
            self.handle_chat_stream(session)
        elif path == "/api/chat":
            payload = self.read_json(MAX_REQUEST_BYTES)
            client_turn_id = str(payload.get("client_turn_id") or "").strip()
            if not client_turn_id:
                raise AppError(400, "client_turn_id ist für Coach-Nachrichten erforderlich.", reason="invalid_client_turn")
            self.send_json(202, coach_job_submission_service().enqueue(
                str(payload.get("message", "")), client_turn_id, session["csrf_hash"],
                request_kind=payload.get("request_kind"), attachments=payload.get("attachments"),
            ))
        elif path == "/api/chat/reset":
            self.send_json(200, coach_conversation_reset_service().reset())
        elif path == "/api/feedback":
            self.send_json(200, checkin_service().save(self.read_json()))
        else:
            return False
        return True

    def _handle_sync_post(self, path: str) -> bool:
        if not SyncCommandEndpoint.handles(path):
            return False
        payload = self.read_json() if SyncCommandEndpoint.needs_body(path) else None
        status, result = sync_command_endpoint().execute(path, payload)
        self.send_json(status, result)
        return True

    def _handle_data_post(self, path: str, session: dict[str, Any]) -> bool:
        if path == "/api/change-history/undo/preview":
            preview = history_undo_service().preview(self.read_json().get("change_id"))
            proposal = coach_proposal_creation_service().create(
                preview.pop("proposal"), session["csrf_hash"]
            )
            self.send_json(
                200,
                {**preview, "proposed_action": proposal["proposed_action"]},
            )
        elif path == "/api/diagnostics/capture":
            self.send_json(200, DIAGNOSTIC_CAPTURE.set_enabled(self.read_json().get("enabled")))
        elif path == "/api/privacy/delete":
            payload = self.read_json()
            if payload.get("confirm") != "LOKALE DATEN LÖSCHEN":
                raise AppError(400, "Zum Löschen muss LOKALE DATEN LÖSCHEN bestätigt werden.")
            self.send_json(200, privacy_delete_service().delete())
        elif path == "/api/change-history/undo":
            self.send_json(200, history_undo_service().apply(self.read_json()))
        else:
            return False
        return True

    def handle_authenticated_post(self, path: str, session: dict[str, Any]) -> None:
        handled = (
            self._handle_coach_post(path, session)
            or self._handle_sync_post(path)
            or self._handle_data_post(path, session)
        )
        if not handled:
            raise AppError(404, NOT_FOUND_ERROR)

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
            if path == "/api/settings/model":
                self.send_json(200, SETTINGS.save_model(self.read_json().get("model")))
                return
            if path == "/api/settings/ai-provider":
                self.send_json(200, SETTINGS.save_ai_provider(self.read_json().get("provider")))
                return
            if path == "/api/settings/thinking-level":
                self.send_json(200, SETTINGS.save_thinking_level(self.read_json().get("thinking_level")))
                return
            if path == "/api/settings/calendar-display":
                self.send_json(200, SETTINGS.save_calendar_display_settings(self.read_json()))
                return
            if path == "/api/athlete-context":
                payload = self.read_json()
                self.send_json(200, athlete_context_service().save(payload.get("profile"), payload.get("competitions")))
                return
            if path != "/api/profile":
                raise AppError(404, NOT_FOUND_ERROR)
            self.send_json(200, profile_service().save(self.read_json()))
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
        data = response_json_bytes(payload)
        self.send_response(status)
        for key, value in response_headers("application/json; charset=utf-8", len(data)):
            self.send_header(key, value)
        for key, value in response_header_items(headers):
            self.send_header(key, value)
        self._response_status = status
        self._response_bytes = len(data)
        self._response_started_at = time.perf_counter()
        try:
            self.end_headers()
            self.wfile.write(data)
        except self.client_disconnect_errors as exc:
            self._response_error_type = type(exc).__name__
            self.log_client_disconnect()
        finally:
            for attribute in ("_response_status", "_response_bytes", "_response_started_at", "_response_error_type"):
                self.__dict__.pop(attribute, None)

    def send_file_stream(
        self,
        path: Path,
        content_type: str,
        filename: str,
        *,
        deadline: float | None = None,
        cleanup: bool = False,
    ) -> None:
        try:
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            with path.open("rb") as source:
                while True:
                    if deadline is not None and time.monotonic() > deadline:
                        LOGGER.warning("File stream exceeded time limit", extra={"event": "file_stream_timeout"})
                        break
                    chunk = source.read(STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except self.client_disconnect_errors:
            self.log_client_disconnect()
        except OSError:
            LOGGER.warning("File stream failed", extra={"event": "file_stream_failed"}, exc_info=True)
        finally:
            if cleanup:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning("Temporary export cleanup failed", extra={"event": "export_cleanup_failed"})

    def send_bytes(self, status: int, data: bytes, content_type: str, headers: dict[str, str | list[str]] | None = None) -> None:
        self.send_response(status)
        for key, value in response_headers(content_type, len(data)):
            self.send_header(key, value)
        for key, value in response_header_items(headers):
            self.send_header(key, value)
        try:
            self.end_headers()
            self.wfile.write(data)
        except self.client_disconnect_errors:
            self.log_client_disconnect()

    def send_static(self, path: str) -> None:
        response = self.static_asset_service.render(
            path,
            getattr(self, "path", ""),
            getattr(self, "headers", {}).get("If-None-Match"),
        )
        self.send_response(response.status)
        for name, value in response.headers:
            self.send_header(name, value)
        try:
            self.end_headers()
            if response.body:
                self.wfile.write(response.body)
        except self.client_disconnect_errors:
            self.log_client_disconnect()


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
    sync_job_queue_service().resume_interrupted()
    coach_job_store().resume_interrupted(coach_turn_failure_service())
    server = http_server.CoachHTTPServer(("0.0.0.0", CONFIG.port), request_handler_class())
    server.allow_reuse_address = True
    sync_job_worker().start()
    start_coach_job_worker()
    startup_sync_scheduler().schedule()
    threading.Thread(target=daily_sync_loop_service().run, daemon=True).start()
    LOGGER.info(f"{APP_NAME} listening", extra={"event": "server_ready", "context": {"port": CONFIG.port}})
    try:
        server.serve_forever()  # NOSONAR - HTTP is intentionally LAN-only behind the documented HTTPS proxy.
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
