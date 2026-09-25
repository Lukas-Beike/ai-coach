"""Generate the static server.py extraction inventory.

The generator deliberately uses only the Python standard library.  It parses
source text and never imports ``server`` or opens runtime application data.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_MODULE = "server.py"
SERVER_PATH = ROOT / SERVER_MODULE
PLAN_PATH = ROOT / "docs" / "server-monolith-extraction-plan.md"
DOC_PATH = ROOT / "docs" / "server-extraction-inventory.md"
P0_BASE_COMMIT = "362d6caa4c27951af86b82b11b3a43d48dadceee"
COMPOSITION_ROOT = "server.py / Composition Root"
RUNTIME_PACKAGE = "runtime/"
RUNTIME_EVENTS = "runtime/events.py"
RUNTIME_MAINTENANCE = "runtime/maintenance.py"
SYNC_PACKAGE = "sync/"
SYNC_GARMIN = "sync/garmin.py"
SYNC_RECONCILE = "sync/reconcile.py"
SYNC_SCHEDULER = "sync/scheduler.py"
SYNC_SNAPSHOTS = "sync/snapshots.py"
COACH_PACKAGE = "coach/"
COACH_LIMITS = "coach/limits.py"
COACH_CONVERSATION = "coach/conversation.py"
COACH_CONTEXT = "coach/context.py"
COACH_JOBS = "coach/jobs.py"
COACH_MORNING = "coach/morning.py"
COACH_PROPOSALS = "coach/proposals.py"
COACH_AUTHORIZATION = "coach/authorization.py"
COACH_TOOL_EXECUTION = "coach/tool_execution.py"
COACH_SERVICE = "coach/service.py"
COACH_STREAMS = "coach/streams.py"
SYNC_COMPETITIONS = "sync/competitions.py"
SYNC_PERFORMANCE = "sync/performance.py"
SYNC_ADAPTIVE = "sync/adaptive.py"
SYNC_LIBRARY = "sync/library.py"
SYNC_PLANNED_UNITS = "sync/planned_units.py"
HTTP_API_PACKAGE = "http_api/"
HTTP_AUTH = "http_api/auth.py"
CONFIG_MODULE = "config.py"
ERRORS_MODULE = "errors.py"
OBSERVABILITY_MODULE = "observability.py"
DB_MANAGER = "db/manager.py"
DB_PACKAGE = "db/"
PROVIDERS_PACKAGE = "providers/"
PROVIDER_HTTP = "providers/http.py"
PROVIDER_CALENDAR = "providers/calendar.py"
PROVIDER_OPENAI = "providers/openai.py"
SETTINGS_MODULE = "settings.py"
ACTIVITIES_PACKAGE = "activities/"
ATHLETE_PACKAGE = "athlete/"
PERFORMANCE_PACKAGE = "performance/"
PERFORMANCE_MORNING_BATTERY = "performance/morning_battery_service.py"
PERFORMANCE_ACTIVITY_VALIDATION = "performance/activity_validation.py"
WEATHER_PACKAGE = "weather/"
HISTORY_PACKAGE = "history/"
PLANNING_PACKAGE = "planning/"
PLANNING_COMPETITIONS = "planning/competitions.py"
BACKUP_PACKAGE = "backup/"
CALENDAR_PACKAGE = "calendar/"
PRIVACY_MODULE = "privacy.py"
DIAGNOSTICS_REPORT = "diagnostics/report.py"
SYNC_REFRESH = "sync/refresh.py"
KIND_FUNCTION = "Funktion"
KIND_CLASS = "Klasse"
KIND_GLOBAL = "Globale Bindung"
KIND_IMPORT = "Importbindung"
GITHUB_DIR = ".github"
BACKEND_DIR = "backend"
SCRIPTS_DIR = "scripts"
ENCODING_UTF8 = "utf-8"
END_LINE_ATTRIBUTE = "end_lineno"
CALENDAR_TOKEN = "calendar"
STATUS_OPEN = "offen"


@dataclass(frozen=True)
class PlanRange:
    start: int
    end: int
    responsibilities: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class InventoryItem:
    kind: str
    name: str
    line: int
    end_line: int
    source: str
    target: str
    phase: str
    status: str
    node: ast.AST | None = None
    imported_module: str = ""


def _number(value: str) -> int:
    return int(value.replace(".", ""))


def read_plan_ranges() -> tuple[PlanRange, ...]:
    ranges: list[PlanRange] = []
    pattern = re.compile(r"^\|\s*(\d[\d.]*)\s*[-–]\s*(\d[\d.]*)\s*\|")
    for line in PLAN_PATH.read_text(encoding=ENCODING_UTF8).splitlines():
        match = pattern.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        targets = tuple(re.findall(r"`([^`]+)`", cells[2]))
        ranges.append(
            PlanRange(
                _number(match.group(1)),
                _number(match.group(2)),
                cells[1],
                targets,
            )
        )
    if not ranges:
        raise RuntimeError("No source ranges found in the extraction plan")
    return tuple(ranges)


def range_for(line: int, ranges: tuple[PlanRange, ...]) -> PlanRange | None:
    return next((item for item in ranges if item.start <= line <= item.end), None)


def _bound_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_bound_names(element))
        return names
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return []


def _import_bindings(node: ast.Import | ast.ImportFrom) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            result.append((alias.asname or alias.name.split(".")[0], alias.name))
    else:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            if alias.name == "*":
                continue
            result.append((alias.asname or alias.name, f"{module}:{alias.name}"))
    return result


def _module_scope_nodes(statements: list[ast.stmt]) -> list[ast.stmt]:
    """Flatten module-level control flow without entering local scopes."""

    result: list[ast.stmt] = []
    for node in statements:
        result.append(node)
        branches: list[list[ast.stmt]] = []
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            branches.extend([node.body, node.orelse])
        elif isinstance(node, ast.Try):
            branches.extend([node.body, node.orelse, node.finalbody])
            branches.extend(handler.body for handler in node.handlers)
        elif isinstance(node, ast.Match):
            branches.extend(case.body for case in node.cases)
        for branch in branches:
            result.extend(_module_scope_nodes(branch))
    return result


def _explicit_owner(name: str) -> str | None:
    explicit = {
            "publish_state_event": RUNTIME_EVENTS,
            "state_events_since": RUNTIME_EVENTS,
            "maintenance_operation": RUNTIME_MAINTENANCE,
            "claimed_maintenance_operation": RUNTIME_MAINTENANCE,
            "MaintenanceGate": RUNTIME_MAINTENANCE,
            "ProviderResyncGate": SYNC_PACKAGE,
            "provider_operation": SYNC_PACKAGE,
            "intervals_operation": SYNC_PACKAGE,
            "garmin_operation": SYNC_GARMIN,
            "IntervalsClient": "providers/intervals_client.py",
            "TranscribePostRoutes": HTTP_API_PACKAGE,
            "serialise_conversation": COACH_CONVERSATION,
            "_gemini_request_history": COACH_CONVERSATION,
            "_gemini_request_payload": COACH_CONVERSATION,
            "_gemini_last_user_text": COACH_CONVERSATION,
            "_gemini_call_names": COACH_CONVERSATION,
            "utc_now": RUNTIME_PACKAGE,
            "ATHLETE_CLOCK": "backend/athlete/clock.py",
            "ATHLETE_PROFILE_SERVICE": COMPOSITION_ROOT,
            "AppError": ERRORS_MODULE,
            "public_app_error_status": ERRORS_MODULE,
            "ClientDisconnected": ERRORS_MODULE,
            "security_configuration_error": CONFIG_MODULE,
            "database_manager": DB_MANAGER,
            "SESSION_AUTH_SERVICE_CACHE": HTTP_AUTH,
            "SessionAuthServiceCache": HTTP_AUTH,
            "RATE_LIMITER": HTTP_AUTH,
            "PROVIDER_STATE_SERVICE_CACHE": "providers/state.py",
            "ProviderStateServiceCache": "providers/state.py",
            "PROVIDER_REFRESH_TRACKER_CACHE": SYNC_REFRESH,
            "ProviderRefreshTrackerCache": SYNC_REFRESH,
            "key_value_service": COMPOSITION_ROOT,
            "initialise_database": "db/bootstrap.py",
            "checkin_service": COMPOSITION_ROOT,
            "profile_service": COMPOSITION_ROOT,
            "external_calendar_reader": COMPOSITION_ROOT,
            "calendar_conflict_service": COMPOSITION_ROOT,
            "duplicate_activity_service": COMPOSITION_ROOT,
            "activity_feedback_service": COMPOSITION_ROOT,
            "activity_read_service": COMPOSITION_ROOT,
            "weather_service": COMPOSITION_ROOT,
            "morning_body_battery_service": COMPOSITION_ROOT,
            "structured_training_state_service": COMPOSITION_ROOT,
            "structured_training_change_validator": COMPOSITION_ROOT,
            "structured_training_change_service": COMPOSITION_ROOT,
            "structured_training_plan_replacement_service": COMPOSITION_ROOT,
            "adaptive_replan_apply_service": COMPOSITION_ROOT,
            "adaptive_replan_preview_service": COMPOSITION_ROOT,
            "daily_planning_context_service": COMPOSITION_ROOT,
            "local_plan_creation_service": COMPOSITION_ROOT,
            "training_plan_artifact_service": COMPOSITION_ROOT,
            "planned_unit_service": COMPOSITION_ROOT,
            "workout_library_service": COMPOSITION_ROOT,
            "workout_library_plan_service": COMPOSITION_ROOT,
            "athlete_context_service": COMPOSITION_ROOT,
            "gemini_json_client": COMPOSITION_ROOT,
            "audio_transcription_client": COMPOSITION_ROOT,
            "gemini_stream_client": COMPOSITION_ROOT,
            "openai_responses_client": COMPOSITION_ROOT,
            "openai_stream_client": COMPOSITION_ROOT,
            "external_call": PROVIDER_HTTP,
            "gemini_raw_request": PROVIDERS_PACKAGE,
            "_gemini_responses_result": PROVIDERS_PACKAGE,
            "gemini_responses_request": PROVIDERS_PACKAGE,
            "gemini_stream_request": PROVIDERS_PACKAGE,
            "responses_stream_request": PROVIDERS_PACKAGE,
            "ensure_conversation": COACH_CONVERSATION,
            "_delete_reset_coach_conversation": COACH_CONVERSATION,
            "_cancel_reset_coach_commands": COACH_CONVERSATION,
            "_reset_local_coach_chat_state": COACH_CONVERSATION,
            "_request_coach_operation_cancellation": COACH_JOBS,
            "_clear_coach_conversation_state": COACH_CONVERSATION,
            "reset_coach_chat": COACH_CONVERSATION,
            "_coach_action_hash": COACH_PROPOSALS,
            "_coach_action_view": COACH_PROPOSALS,
            "validated_coach_action_preview_input": COACH_PROPOSALS,
            "create_coach_action_preview": COACH_PROPOSALS,
            "confirm_coach_action_preview": COACH_PROPOSALS,
            "execute_coach_action": COACH_PROPOSALS,
            "external_result_context": OBSERVABILITY_MODULE,
            "provider_error": ERRORS_MODULE,
            "CoachHTTPServer": HTTP_API_PACKAGE,
            "ATHLETE_GET_ROUTES": HTTP_API_PACKAGE,
            "SYNC_GET_ROUTES": HTTP_API_PACKAGE,
            "DIAGNOSTICS_GET_ROUTES": HTTP_API_PACKAGE,
            "HISTORY_GET_ROUTES": HTTP_API_PACKAGE,
            "PRIVACY_GET_ROUTES": HTTP_API_PACKAGE,
            "STATE_EVENTS_GET_ROUTES": HTTP_API_PACKAGE,
            "SETTINGS_PUT_ROUTES": HTTP_API_PACKAGE,
            "ATHLETE_PUT_ROUTES": HTTP_API_PACKAGE,
            "HISTORY_UNDO_POST_ROUTES": HTTP_API_PACKAGE,
            "DIAGNOSTICS_CAPTURE_POST_ROUTES": HTTP_API_PACKAGE,
            "PRIVACY_DELETE_POST_ROUTES": HTTP_API_PACKAGE,
            "COACH_ACTIONS_POST_ROUTES": HTTP_API_PACKAGE,
            "CHAT_POST_ROUTES": HTTP_API_PACKAGE,
            "CHAT_STREAM_TRANSPORT": HTTP_API_PACKAGE,
            "TRANSCRIBE_POST_ROUTES": HTTP_API_PACKAGE,
            "PlanningCommandsPostRoutes": HTTP_API_PACKAGE,
            "FeedbackPostRoutes": HTTP_API_PACKAGE,
            "ChatCancelPostRoutes": HTTP_API_PACKAGE,
            "PrivacyRestorePostRoutes": HTTP_API_PACKAGE,
            "AuthPostRoutes": HTTP_API_PACKAGE,
            "PLANNING_COMMANDS_POST_ROUTES": HTTP_API_PACKAGE,
            "FEEDBACK_POST_ROUTES": HTTP_API_PACKAGE,
            "CHAT_CANCEL_POST_ROUTES": HTTP_API_PACKAGE,
            "PRIVACY_RESTORE_POST_ROUTES": HTTP_API_PACKAGE,
            "AUTH_POST_ROUTES": HTTP_API_PACKAGE,
            "NUTRITION_GET_ROUTES": HTTP_API_PACKAGE,
            "NUTRITION_POST_ROUTES": HTTP_API_PACKAGE,
            "NUTRITION_PUT_ROUTES": HTTP_API_PACKAGE,
            "HTTP_ROUTE_DISPATCHER": HTTP_API_PACKAGE,
            "HttpRouteDispatcher": HTTP_API_PACKAGE,
            "HTTP_POST_DISPATCHER": HTTP_API_PACKAGE,
            "AUTHENTICATED_POST_ROUTES": HTTP_API_PACKAGE,
            "HTTP_RESPONSE_TRANSPORT": HTTP_API_PACKAGE,
            "nutrition_service": "nutrition/service.py",
            "login_user": HTTP_AUTH,
            "logout_user": HTTP_AUTH,
            "bootstrap_provider_states": "http_api/bootstrap.py",
            "VERSIONED_STATIC_ASSETS": HTTP_API_PACKAGE,
            "UTC_OFFSET_SUFFIX": CONFIG_MODULE,
            "ISO_MIDNIGHT_SUFFIX": CONFIG_MODULE,
            "JSON_MEDIA_TYPE": HTTP_API_PACKAGE,
            "OCTET_STREAM_MIME": HTTP_API_PACKAGE,
            "VO2MAX_UNIT": PERFORMANCE_PACKAGE,
            "LOCAL_INTERVALS_SCOPE": COACH_AUTHORIZATION,
            "WORKDAY_TIME_LABEL": COACH_CONTEXT,
            "APP_NAME": CONFIG_MODULE,
            "UUID_PATTERN": HTTP_API_PACKAGE,
            "PAYLOAD_HASH_PATTERN": PLANNING_PACKAGE,
            "DATE_ONLY_PATTERN": SYNC_PACKAGE,
            "MAX_BODY_BYTES": HTTP_API_PACKAGE,
            "MAX_AUDIO_BODY_BYTES": HTTP_API_PACKAGE,
            "MAX_BACKUP_BYTES": BACKUP_PACKAGE,
            "MAX_PRIVACY_EXPORT_BYTES": PRIVACY_MODULE,
            "MIN_EXPORT_FREE_BYTES": BACKUP_PACKAGE,
            "EXPORT_TIME_LIMIT_SECONDS": BACKUP_PACKAGE,
            "STREAM_CHUNK_BYTES": "http_api/response_transport.py",
            "MAX_EXTERNAL_CALENDAR_BYTES": PROVIDER_CALENDAR,
            "CALENDAR_FETCH_TIMEOUT_SECONDS": PROVIDER_CALENDAR,
            "CALENDAR_CONNECTION_TIMEOUT_SECONDS": PROVIDER_CALENDAR,
            "MAX_EXTERNAL_RESPONSE_BYTES": PROVIDER_HTTP,
            "MESSAGE_ATTACHMENTS_QUERY": COACH_CONVERSATION,
            "SESSIONS": HTTP_AUTH,
            "RATE_LIMITS": HTTP_AUTH,
            "COMPETITION_EXTERNAL_PREFIX": PLANNING_COMPETITIONS,
            "COMPETITION_TEXT_LIMITS": PLANNING_COMPETITIONS,
            "competition_start": PLANNING_COMPETITIONS,
            "competition_moving_time": PLANNING_COMPETITIONS,
            "competition_distance": PLANNING_COMPETITIONS,
            "competition_target": PLANNING_COMPETITIONS,
            "competition_category_and_priority": PLANNING_COMPETITIONS,
            "competition_normalized_id": PLANNING_COMPETITIONS,
            "competition_normalized_text_fields": PLANNING_COMPETITIONS,
            "first_present": PLANNING_PACKAGE,
            "as_number": PLANNING_PACKAGE,
            "CALENDAR_DISPLAY_DEFAULTS": SETTINGS_MODULE,
            "CALENDAR_DISPLAY_MAX_WEEKS": SETTINGS_MODULE,
            "URL_VALUE_RE": OBSERVABILITY_MODULE,
            "DEFAULT_PROFILE": ATHLETE_PACKAGE,
            "NRW_LATITUDE_BOUNDS": WEATHER_PACKAGE,
            "NRW_LONGITUDE_BOUNDS": WEATHER_PACKAGE,
            "MORNING_RETRY_SECONDS": PERFORMANCE_MORNING_BATTERY,
            "MORNING_MAX_ATTEMPTS": PERFORMANCE_MORNING_BATTERY,
            "morning_checkin_date": COACH_MORNING,
            "morning_checkin_state": COACH_MORNING,
            "MORNING_CHECKIN_PROMPT": COACH_MORNING,
            "_start_morning_checkin": COACH_MORNING,
            "_morning_checkin_attempt": COACH_MORNING,
            "_complete_morning_checkin": COACH_MORNING,
            "run_morning_checkin": COACH_MORNING,
            "_reserve_morning_checkin": COACH_MORNING,
            "_run_scheduled_morning_checkin": COACH_MORNING,
            "_start_scheduled_morning_checkin": COACH_MORNING,
            "schedule_morning_checkin": COACH_MORNING,
            "_morning_checkin_garmin_ready": COACH_MORNING,
            "_wait_for_morning_intervals_sync": COACH_MORNING,
            "LIBRARY_BULK_MAX_ENTRIES": PLANNING_PACKAGE,
            "COACH_DEFAULT_MAX_OUTPUT_TOKENS": COACH_LIMITS,
            "COACH_LONG_PLAN_MAX_OUTPUT_TOKENS": COACH_LIMITS,
            "COACH_BACKGROUND_HORIZON_DAYS": COACH_LIMITS,
            "COACH_TRAINING_CHANGE_LIMIT": COACH_LIMITS,
            "DEFAULT_TIMEZONE": CONFIG_MODULE,
            "ATHLETE_RECORD_HANDLERS": COACH_TOOL_EXECUTION,
            "DB_LOCK": DB_MANAGER,
            "DATABASE_MANAGER_CACHE": DB_MANAGER,
            "TRAINING_PLAN_REPOSITORY": COMPOSITION_ROOT,
            "PLANNING_STATE_REPOSITORY": COMPOSITION_ROOT,
            "PLANNING_REVISION_SERVICE": COMPOSITION_ROOT,
            "PLAN_ADJUSTMENT_REPOSITORY": COMPOSITION_ROOT,
            "SYNC_LOCK": SYNC_PACKAGE,
            "WORKOUT_LIBRARY_SYNC_LOCK": SYNC_PACKAGE,
            "COMPETITION_SYNC_LOCK": SYNC_COMPETITIONS,
            "PERFORMANCE_LOCK": SYNC_PERFORMANCE,
            "OPENAI_CONVERSATION_LOCK": COACH_CONVERSATION,
            "CHAT_QUEUE": COACH_CONVERSATION,
            "CHAT_QUEUE_LIMIT": COACH_CONVERSATION,
            "CHAT_LOCK_TIMEOUT_SECONDS": COACH_CONVERSATION,
            "DIAGNOSTIC_CAPTURE_LOCK": OBSERVABILITY_MODULE,
            "EXTERNAL_HTTP_STARTED_EVENT": OBSERVABILITY_MODULE,
            "EXTERNAL_HTTP_COMPLETED_EVENT": OBSERVABILITY_MODULE,
            "CHAT_STREAM_LOCK": COACH_STREAMS,
            "CHAT_STREAMS": COACH_STREAMS,
            "COACH_JOB_WORKER_LOCK": COACH_JOBS,
            "COACH_JOB_WAKE": COACH_JOBS,
            "COACH_JOB_STOP": COACH_JOBS,
            "COACH_JOB_WORKER": COACH_JOBS,
            "COACH_JOB_CANCEL_EVENTS": COACH_JOBS,
            "MORNING_CHECKIN_LOCK": COACH_MORNING,
            "EXTERNAL_CALENDAR_LOCK": SYNC_RECONCILE,
            "SYNC_JOB_WORKER_LOCK": SYNC_PACKAGE,
            "SYNC_JOB_WAKE": SYNC_PACKAGE,
            "SYNC_JOB_STOP": SYNC_PACKAGE,
            "SYNC_JOB_WORKER": COMPOSITION_ROOT,
            "SESSION_LOCK": HTTP_AUTH,
            "RATE_LIMIT_LOCK": HTTP_AUTH,
            "STATE_EVENT_CONDITION": RUNTIME_EVENTS,
            "STATE_EVENTS": RUNTIME_EVENTS,
            "STATE_EVENT_NEXT_ID": RUNTIME_EVENTS,
            "MAINTENANCE_GATE": RUNTIME_MAINTENANCE,
            "ACTIVITY_FEEDBACK_REPOSITORY": COMPOSITION_ROOT,
            "WEATHER_SERVICE": COMPOSITION_ROOT,
            "MORNING_BODY_BATTERY_SERVICE": COMPOSITION_ROOT,
            "WEATHER_ADAPTIVE_MAX_MINUTES": "planning/adaptive.py",
            "_configure_cipher": DB_MANAGER,
            "RATE_LIMIT_CLEANUP_INTERVAL_SECONDS": HTTP_AUTH,
            "RATE_LIMIT_CLEANUP_BATCH_SIZE": HTTP_AUTH,
            "RATE_LIMIT_BUCKET_MAX_AGE_SECONDS": HTTP_AUTH,
            "RATE_LIMIT_LAST_CLEANUP_MONOTONIC": HTTP_AUTH,
            "DATA_DIR": "db/",
            "timezone_name": CONFIG_MODULE,
            "list_public_event_candidates": CALENDAR_PACKAGE,
            "_save_athlete_profile": ATHLETE_PACKAGE,
            "metric": PROVIDERS_PACKAGE,
            "local_now": RUNTIME_PACKAGE,
            "_require_command_owner": COACH_AUTHORIZATION,
            "_prepare_structured_plan_sync": COACH_TOOL_EXECUTION,
            "sync_weather": SYNC_PACKAGE,
            "_overlay_weather_values": WEATHER_PACKAGE,
            "_merge_weather_forecasts": WEATHER_PACKAGE,
            "sync_illness_pause_to_intervals": SYNC_PACKAGE,
            "check_adaptive_replan": SYNC_ADAPTIVE,
            "_adaptive_replan_result": SYNC_ADAPTIVE,
            "apply_adaptive_replan": SYNC_ADAPTIVE,
            "activity_page_key": ACTIVITIES_PACKAGE,
            "sync_intervals": SYNC_PACKAGE,
            "_safe_diagnostic_context": OBSERVABILITY_MODULE,
            "_safe_diagnostic_error": OBSERVABILITY_MODULE,
            "_coach_error_metadata": OBSERVABILITY_MODULE,
            "openai_error_diagnostic_details": OBSERVABILITY_MODULE,
            "safe_openai_log_reason": OBSERVABILITY_MODULE,
            "_log_openai_stream_failure": OBSERVABILITY_MODULE,
            "SETTINGS_SECRET_KEYS": OBSERVABILITY_MODULE,
            "coach_diagnostic_history": DIAGNOSTICS_REPORT,
            "coach_diagnostic_history_service": COMPOSITION_ROOT,
            "_safe_response_headers": OBSERVABILITY_MODULE,
            "set_diagnostic_capture": OBSERVABILITY_MODULE,
            "capture_diagnostic_event": OBSERVABILITY_MODULE,
            "measurement_age": PERFORMANCE_PACKAGE,
            "add_message": COACH_CONVERSATION,
            "list_messages": COACH_CONVERSATION,
            "bounded_score": PERFORMANCE_PACKAGE,
            "bounded_minutes": PERFORMANCE_PACKAGE,
            "EXTERNAL_CALENDAR_WINDOW_DAYS": PROVIDER_CALENDAR,
            "ICAL_MAX_RECURRENCE_COUNT": PROVIDER_CALENDAR,
            "ICAL_MAX_RECURRENCE_PERIODS": PROVIDER_CALENDAR,
            "intervals_activity_device_source": ACTIVITIES_PACKAGE,
            "_latest_activity_id": ACTIVITIES_PACKAGE,
            "_paired_activity_match": ACTIVITIES_PACKAGE,
            "_unpaired_activity_match": ACTIVITIES_PACKAGE,
            "mark_daily_sync": "sync/daily.py",
            "_add_weather_context": COACH_CONTEXT,
            "_latest_ride_activity": PERFORMANCE_ACTIVITY_VALIDATION,
            "latest_activity_for_validation": PERFORMANCE_ACTIVITY_VALIDATION,
            "bounded_activity_metric": PERFORMANCE_ACTIVITY_VALIDATION,
            "cycling_activity_validation_details": PERFORMANCE_ACTIVITY_VALIDATION,
            "recent_log_entries": DIAGNOSTICS_REPORT,
            "diagnostic_report": DIAGNOSTICS_REPORT,
            "_diagnostic_frame": DIAGNOSTICS_REPORT,
            "_diagnostic_error_metadata": DIAGNOSTICS_REPORT,
            "_diagnostic_command_steps": DIAGNOSTICS_REPORT,
            "_diagnostic_history_entry": DIAGNOSTICS_REPORT,
            "_provider_refresh_cleanup": SYNC_REFRESH,
            "_provider_refresh_start": SYNC_REFRESH,
            "_provider_refresh_finish": SYNC_REFRESH,
            "_provider_refresh_error_code": SYNC_REFRESH,
            "_current_provider_freshness": "sync/freshness.py",
            "_performance_refresh_failed": SYNC_PERFORMANCE,
            "_performance_refresh_poll_state": SYNC_PERFORMANCE,
            "_publish_sync_job_result_event": "sync/jobs.py",
            "_update_local_planned_workout_in_db": "planning/calendar.py",
            "change_history_service": COMPOSITION_ROOT,
            "history_undo_service": COMPOSITION_ROOT,
            "competition_service": COMPOSITION_ROOT,
            "training_plan_service": COMPOSITION_ROOT,
            "list_competitions": PLANNING_COMPETITIONS,
            "coach_competition_payload": PLANNING_COMPETITIONS,
            "_normalise_coach_competition_id": PLANNING_COMPETITIONS,
            "_merge_coach_competition_update": PLANNING_COMPETITIONS,
            "_delete_competition_tombstones": SYNC_COMPETITIONS,
            "_competition_remote_events": SYNC_COMPETITIONS,
            "_competition_sync_records": SYNC_COMPETITIONS,
            "_competition_sync_remote_indexes": SYNC_COMPETITIONS,
            "_competition_sync_remote_match": SYNC_COMPETITIONS,
            "_record_competition_sync_conflict": SYNC_COMPETITIONS,
            "_remote_missing_competition_conflict": SYNC_COMPETITIONS,
            "_reconcile_dirty_competition": SYNC_COMPETITIONS,
            "_reconcile_synced_competition": SYNC_COMPETITIONS,
            "_remote_competition_local_id": SYNC_COMPETITIONS,
            "_suppressed_competition_identifiers": SYNC_COMPETITIONS,
            "_import_remote_competitions": SYNC_COMPETITIONS,
            "_preserved_dirty_library_workout": SYNC_LIBRARY,
            "_preserve_remote_library_metadata": SYNC_LIBRARY,
            "_persist_remote_library_workout_entry": SYNC_LIBRARY,
            "_mark_missing_remote_library_workouts": SYNC_LIBRARY,
            "upsert_workout_library": SYNC_LIBRARY,
            "LIBRARY_PAGE_MAX": "http_api/pagination.py",
            "update_planned_unit_sync_state": SYNC_PLANNED_UNITS,
            "_planned_unit_sync_guard": SYNC_PLANNED_UNITS,
            "_workout_library_sync_rows": SYNC_LIBRARY,
            "_workout_library_sync_category": SYNC_LIBRARY,
            "_workout_library_sync_entry": SYNC_LIBRARY,
            "_workout_library_sync_snapshot": SYNC_LIBRARY,
            "refresh_workout_library": SYNC_LIBRARY,
            "plan_library_workout_remote": SYNC_LIBRARY,
            "update_workout_library_sync_state": SYNC_LIBRARY,
            "workout_library_sync_summary": SYNC_LIBRARY,
            "_load_local_library_workout_for_sync": SYNC_LIBRARY,
            "_upsert_remote_library_workout": SYNC_LIBRARY,
            "_store_library_workout_remote_identity": SYNC_LIBRARY,
            "_finish_library_workout_sync": SYNC_LIBRARY,
            "_selected_library_sync_row": SYNC_LIBRARY,
            "_library_sync_error": SYNC_LIBRARY,
            "_verify_selected_library_repair": SYNC_LIBRARY,
            "_update_remote_planned_conflict": SYNC_PLANNED_UNITS,
            "_update_remote_planned_clean": SYNC_PLANNED_UNITS,
            "_upsert_remote_planned_event": SYNC_PLANNED_UNITS,
            "_mark_missing_remote_planned_units": SYNC_PLANNED_UNITS,
            "upsert_remote_planned_units": SYNC_PLANNED_UNITS,
            "_seed_intervals_workout_library": SYNC_LIBRARY,
            "_enqueue_coach_plan_push": SYNC_PLANNED_UNITS,
            "_local_calendar_library_entries": "planning/context.py",
            "_RepairCalendarBatch": SYNC_RECONCILE,
            "_RepairCalendarContext": SYNC_RECONCILE,
            "_repair_calendar_context": SYNC_RECONCILE,
            "_repair_calendar_recheck": SYNC_RECONCILE,
            "_repair_calendar_event_is_invalid": SYNC_RECONCILE,
            "_repair_calendar_event_is_ambiguous": SYNC_RECONCILE,
            "_repair_calendar_related_event": SYNC_RECONCILE,
            "_repair_calendar_related_events": SYNC_RECONCILE,
            "_repair_calendar_check_remote_identity": SYNC_RECONCILE,
            "_repair_calendar_upsert": SYNC_RECONCILE,
            "_repair_calendar_delete_duplicates": SYNC_RECONCILE,
            "_repair_calendar_completion": SYNC_RECONCILE,
            "_require_intervals_calendar_access": SYNC_RECONCILE,
            "_adopt_remote_deletion": SYNC_RECONCILE,
            "_adopt_remote_planned_unit": SYNC_RECONCILE,
            "_remote_calendar_window": SYNC_RECONCILE,
            "readiness_state": "runtime/readiness.py",
            "refresh_current_performance": SYNC_PERFORMANCE,
            "_performance_snapshot_inputs": PERFORMANCE_PACKAGE,
            "_first_performance_source": PERFORMANCE_PACKAGE,
            "_performance_body_metrics": PERFORMANCE_PACKAGE,
            "_preferred_performance_metric": PERFORMANCE_PACKAGE,
            "_performance_threshold_metrics": PERFORMANCE_PACKAGE,
            "_performance_vo2_and_prediction_metrics": PERFORMANCE_PACKAGE,
            "api_performance_metrics": PERFORMANCE_PACKAGE,
            "latest_snapshot": SYNC_SNAPSHOTS,
            "save_snapshot": SYNC_SNAPSHOTS,
            "merge_performance_snapshot": SYNC_SNAPSHOTS,
            "save_snapshot_view": SYNC_SNAPSHOTS,
            "_store_intervals_snapshot": SYNC_SNAPSHOTS,
            "set_sync_operation_state": "sync/status.py",
            "provider_resync_state": SYNC_PACKAGE,
            "_validate_full_provider_resync": SYNC_PACKAGE,
            "_full_provider_resync_details": SYNC_PACKAGE,
            "_run_full_provider_resync": SYNC_PACKAGE,
            "_start_full_provider_resync": SYNC_PACKAGE,
            "_complete_full_provider_resync": SYNC_PACKAGE,
            "_record_full_provider_resync_failure": SYNC_PACKAGE,
            "_finish_full_provider_resync": SYNC_PACKAGE,
            "full_provider_resync": SYNC_PACKAGE,
            "_completed_intervals_sync_result": SYNC_PACKAGE,
            "_wait_for_existing_intervals_sync": SYNC_PACKAGE,
            "coach_context_json_size": COACH_CONTEXT,
            "bounded_coach_context_value": COACH_CONTEXT,
            "bounded_coach_context_sections": COACH_CONTEXT,
            "coach_context_projection_meta": COACH_CONTEXT,
            "coach_intervals_context": COACH_CONTEXT,
            "structured_athlete_context": COACH_CONTEXT,
            "build_training_context": COACH_CONTEXT,
            "context_preview": COACH_CONTEXT,
            "_coach_session_key": COACH_AUTHORIZATION,
            "coach_session_key": COACH_AUTHORIZATION,
            "_restore_coach_session_csrf_hash": COACH_JOBS,
            "_coach_command_receipt": COACH_SERVICE,
            "_merge_coach_command_receipt": COACH_SERVICE,
            "_chat_provider_settings": COACH_SERVICE,
            "_resume_background_chat_command": COACH_SERVICE,
            "chat_with_coach": COACH_SERVICE,
            "_active_background_coach_job": COACH_JOBS,
            "_background_coach_request": COACH_JOBS,
            "_background_coach_provider_settings": COACH_JOBS,
            "_persist_background_coach_job": COACH_JOBS,
            "register_chat_stream": COACH_STREAMS,
            "publish_chat_stream_event": COACH_STREAMS,
            "chat_stream_events": COACH_STREAMS,
            "_close_chat_provider_response": COACH_STREAMS,
            "_cancel_attached_chat_stream": COACH_STREAMS,
            "_cancel_background_chat_job": COACH_JOBS,
            "_claim_background_coach_job": COACH_JOBS,
            "_requeue_background_coach_job": COACH_JOBS,
            "_background_coach_message": COACH_JOBS,
            "_background_coach_stream_delta": COACH_JOBS,
            "_background_coach_delta_callback": COACH_JOBS,
            "_background_coach_stream_receipt": COACH_JOBS,
            "_background_coach_cancel_event": COACH_JOBS,
            "_persist_completed_morning_coach_job": COACH_JOBS,
            "_handle_background_coach_error": COACH_JOBS,
            "_handle_background_coach_exception": COACH_JOBS,
            "_run_background_coach_job": COACH_JOBS,
            "_coach_job_worker_loop": COACH_JOBS,
            "start_coach_job_worker": COACH_JOBS,
            "cancel_chat_stream": COACH_STREAMS,
            "unregister_chat_stream": COACH_STREAMS,
            "STRUCTURED_READ_ONLY_TOOLS": COACH_AUTHORIZATION,
            "coach_execution_scope": COACH_AUTHORIZATION,
            "_coach_scope_values": COACH_AUTHORIZATION,
            "_require_coach_scope": COACH_AUTHORIZATION,
            "_stage_coach_artifact": "coach/artifacts.py",
            "_sync_structured_training_plan": COACH_TOOL_EXECUTION,
            "_structured_coach_read_result": COACH_TOOL_EXECUTION,
            "_queue_structured_performance_refresh": COACH_TOOL_EXECUTION,
            "TRAINING_PLAN_SCOPE_PREFIX": COACH_AUTHORIZATION,
            "PLANNED_WORKOUT_LABEL": COACH_CONTEXT,
            "compact_coach_activity": COACH_CONTEXT,
            "compact_coach_planned_event": COACH_CONTEXT,
            "compact_coach_local_planned_workout": COACH_CONTEXT,
            "compact_coach_local_planned_workouts": COACH_CONTEXT,
            "future_coach_planned_workouts": COACH_CONTEXT,
            "_compact_coach_library_item": COACH_CONTEXT,
            "_balanced_coach_library_items": COACH_CONTEXT,
            "coach_workout_library": COACH_CONTEXT,
            "_replace_structured_coach_training_plan": COACH_TOOL_EXECUTION,
            "_validate_structured_training_change_scopes": COACH_TOOL_EXECUTION,
            "_apply_structured_adaptive_replan": COACH_TOOL_EXECUTION,
            "_append_planning_command_scope": COACH_TOOL_EXECUTION,
            "ILLNESS_CALENDAR_CATEGORY": SYNC_ADAPTIVE,
            "ILLNESS_EVENT_EXTERNAL_PREFIX": SYNC_ADAPTIVE,
            "PLANNED_CALENDAR_HISTORY_DAYS": SYNC_PLANNED_UNITS,
            "PLANNED_CALENDAR_FUTURE_DAYS": SYNC_PLANNED_UNITS,
            "_openai_usage_summary_unlocked": PROVIDERS_PACKAGE,
            "openai_usage_summary": PROVIDERS_PACKAGE,
            "_record_openai_usage_unlocked": PROVIDERS_PACKAGE,
            "record_openai_usage": PROVIDERS_PACKAGE,
            "_validate_openai_response": PROVIDERS_PACKAGE,
            "openai_request": PROVIDER_OPENAI,
            "responses_request": PROVIDER_OPENAI,
            "retrieve_openai_response": PROVIDER_OPENAI,
            "cancel_openai_response": PROVIDER_OPENAI,
            "_raise_chat_cancelled": PROVIDER_OPENAI,
            "_capture_openai_stream_failure": PROVIDER_OPENAI,
            "_handle_openai_stream_app_error": PROVIDER_OPENAI,
            "_handle_openai_stream_disconnect": PROVIDER_OPENAI,
            "_handle_openai_stream_http_error": PROVIDER_OPENAI,
            "_handle_openai_stream_timeout": PROVIDER_OPENAI,
            "_handle_openai_stream_network_error": PROVIDER_OPENAI,
            "openai_stream_request": PROVIDER_OPENAI,
            "gemini_usage_summary": PROVIDERS_PACKAGE,
            "_record_gemini_status": PROVIDERS_PACKAGE,
            "_record_gemini_usage": PROVIDERS_PACKAGE,
            "_gemini_content_has_function_response": COACH_CONVERSATION,
            "_gemini_history_exchange_boundary": COACH_CONVERSATION,
            "_trim_gemini_history": COACH_CONVERSATION,
            "_gemini_history_parts_without_raw_media": COACH_CONVERSATION,
            "_gemini_inline_media_from_history": COACH_CONVERSATION,
            "_gemini_history": COACH_CONVERSATION,
            "_save_gemini_history": COACH_CONVERSATION,
            "repair_incomplete_gemini_tool_history": COACH_CONVERSATION,
            "_gemini_selected_raw_attachments": COACH_CONVERSATION,
            "_gemini_history_parts": COACH_CONVERSATION,
            "_gemini_local_chat_history": COACH_CONVERSATION,
            "_validate_structured_plan_limits": PLANNING_PACKAGE,
            "_derived_structured_training_plan": PLANNING_PACKAGE,
            "_resolve_structured_training_plan_reference": PLANNING_PACKAGE,
            "_derive_structured_training_plan": PLANNING_PACKAGE,
            "_planning_change_dependencies": PLANNING_PACKAGE,
            "_prepare_structured_plan_replacement": PLANNING_PACKAGE,
            "_archive_superseded_training_plans": PLANNING_PACKAGE,
            "_replace_structured_training_plan": PLANNING_PACKAGE,
            "_stage_structured_training_plan": PLANNING_PACKAGE,
            "_commit_structured_training_plan": PLANNING_PACKAGE,
            "_persist_committed_training_plan": PLANNING_PACKAGE,
            "_validate_committed_training_plan": PLANNING_PACKAGE,
            "_local_planning_authoritative_rows": SYNC_RECONCILE,
            "_mark_local_planning_row_authoritative": SYNC_RECONCILE,
            "_mark_local_planning_authoritative": SYNC_RECONCILE,
            "_mark_local_competitions_authoritative": SYNC_RECONCILE,
            "privacy_export": PRIVACY_MODULE,
            "PRIVACY_EXPORT_FORMAT_VERSION": PRIVACY_MODULE,
            "PRIVACY_EXPORT_JSONL_FILES": PRIVACY_MODULE,
            "_export_payload": BACKUP_PACKAGE,
            "_export_jsonl_rows": BACKUP_PACKAGE,
            "_export_workout_library": BACKUP_PACKAGE,
            "_export_planned_units": BACKUP_PACKAGE,
            "_export_application_state": BACKUP_PACKAGE,
            "_privacy_export_file": PRIVACY_MODULE,
            "stream_privacy_export": COACH_CONTEXT,
            "database_backup_bytes": BACKUP_PACKAGE,
            "stream_database_backup": BACKUP_PACKAGE,
            "restore_database_backup": BACKUP_PACKAGE,
            "_temporary_restore_database": BACKUP_PACKAGE,
            "_validate_restore_connection": BACKUP_PACKAGE,
            "_validate_restore_database": BACKUP_PACKAGE,
            "_replace_database_with_restore": BACKUP_PACKAGE,
            "_resume_after_database_restore": BACKUP_PACKAGE,
            "_restore_database_backup": BACKUP_PACKAGE,
            "_privacy_delete_counts": PRIVACY_MODULE,
            "privacy_delete_preview": PRIVACY_MODULE,
            "require_auth": HTTP_API_PACKAGE,
            "require_csrf": HTTP_API_PACKAGE,
            "session_cookie_headers": HTTP_API_PACKAGE,
            "RequestHandler": HTTP_API_PACKAGE,
            "delete_local_data": PRIVACY_MODULE,
            "delete_remote_conversation": COACH_CONTEXT,
            "PRIVACY_DELETE_SCOPE": COACH_CONTEXT,
            "PRIVACY_REMOTE_SCOPE": COACH_CONTEXT,
            "CSRF_COOKIE": HTTP_AUTH,
            "session_token_hash": HTTP_AUTH,
            "session_timestamp": HTTP_AUTH,
            "cleanup_expired_sessions": HTTP_AUTH,
            "authenticated_session": HTTP_AUTH,
            "coach_dialogue_context": COACH_SERVICE,
            "_apply_dialogue_operation_scope": COACH_SERVICE,
            "_save_coach_question": COACH_SERVICE,
            "_matching_coach_steps_repaired": COACH_SERVICE,
            "_coach_steps_repaired": COACH_SERVICE,
            "_unresolved_coach_steps": COACH_SERVICE,
            "_coach_repair_key": COACH_SERVICE,
            "_append_template_command_scope": COACH_SERVICE,
            "_add_structured_coach_attachment_evidence": COACH_SERVICE,
            "coach_attachment_context_service": COMPOSITION_ROOT,
            "manual_morning_checkin_service": COMPOSITION_ROOT,
            "morning_checkin_state_service": COMPOSITION_ROOT,
            "_send_structured_coach_response": COACH_SERVICE,
            "_recover_structured_coach_conversation": COACH_SERVICE,
            "_resume_background_coach_response": COACH_SERVICE,
            "_recover_invalid_structured_conversation": COACH_SERVICE,
            "_wait_for_coach_response_retry": COACH_SERVICE,
            "_StructuredCoachResponseAttemptContext": COACH_SERVICE,
            "_mark_resolved_coach_receipts": COACH_SERVICE,
            "_coach_effects": COACH_SERVICE,
            "_persist_structured_coach_pending_request": COACH_SERVICE,
            "_structured_tool_call_metadata": COACH_TOOL_EXECUTION,
            "_cached_structured_tool_call": COACH_TOOL_EXECUTION,
            "_prepare_structured_tool_execution": COACH_TOOL_EXECUTION,
            "_structured_tool_call_failure": COACH_TOOL_EXECUTION,
            "_StructuredCoachRoundState": COACH_TOOL_EXECUTION,
            "_record_structured_coach_tool_output": COACH_TOOL_EXECUTION,
            "_run_structured_coach_tool_rounds": COACH_TOOL_EXECUTION,
            "_persist_structured_coach_final_receipt": COACH_SERVICE,
            "_chat_with_structured_coach_impl": COACH_SERVICE,
            "current_coach_proposals": COACH_PROPOSALS,
            "prune_expired_coach_proposals": COACH_PROPOSALS,
            "coach_command_receipt": COACH_SERVICE,
            "_chat_with_structured_coach": COACH_SERVICE,
            "coach_dialogue_artifact_refs": "coach/context.py",
            "chat_stream_status": "coach/streams.py",
            "_validated_chat_request": COACH_SERVICE,
            "_recover_stale_chat_command": COACH_SERVICE,
            "_chat_command_state": COACH_SERVICE,
            # These functions instantiate concrete backend owners. They are
            # intentionally retained in the final composition root and must
            # not inflate the still-open domain phase counts.
            "provider_refresh_tracker": COMPOSITION_ROOT,
            "intervals_client": COMPOSITION_ROOT,
            "sync_operation_observer": COMPOSITION_ROOT,
            "sync_job_store": COMPOSITION_ROOT,
            "sync_job_queue_service": COMPOSITION_ROOT,
            "planning_authority_service": COMPOSITION_ROOT,
            "illness_pause_sync_service": COMPOSITION_ROOT,
            "adaptive_preview_followup_service": COMPOSITION_ROOT,
            "provider_refresh_command_service": COMPOSITION_ROOT,
            "sync_conflict_command_service": COMPOSITION_ROOT,
            "plan_push_command_service": COMPOSITION_ROOT,
            "structured_plan_sync_service": COMPOSITION_ROOT,
            "plan_repair_manifest_service": COMPOSITION_ROOT,
            "coach_quick_actions_service": COMPOSITION_ROOT,
            "gemini_conversation_history_service": COMPOSITION_ROOT,
            "coach_message_service": COMPOSITION_ROOT,
            "coach_conversation_history_service": COMPOSITION_ROOT,
            "coach_job_store": COMPOSITION_ROOT,
            "gemini_local_chat_history_service": COMPOSITION_ROOT,
            "gemini_request_payload_service": COMPOSITION_ROOT,
            "gemini_response_normalization_service": COMPOSITION_ROOT,
            "gemini_conversation_response_service": COMPOSITION_ROOT,
            "coach_conversation_provision_service": COMPOSITION_ROOT,
            "library_page_service": COMPOSITION_ROOT,
            "chat_history_page_service": COMPOSITION_ROOT,
            "readiness_service": COMPOSITION_ROOT,
            "session_auth_service": COMPOSITION_ROOT,
            "public_performance_state_service": COMPOSITION_ROOT,
            "public_feedback_state_service": COMPOSITION_ROOT,
            "public_state_service": COMPOSITION_ROOT,
            "public_plan_state_service": COMPOSITION_ROOT,
            "public_bootstrap_service": COMPOSITION_ROOT,
            "public_weather_state_service": COMPOSITION_ROOT,
            "daily_sync_scheduler": COMPOSITION_ROOT,
            "daily_sync_loop_service": COMPOSITION_ROOT,
            "startup_sync_scheduler": COMPOSITION_ROOT,
            "coach_activity_read_tool_service": COMPOSITION_ROOT,
            "coach_read_tool_service": COMPOSITION_ROOT,
            "coach_tool_dispatch_service": COMPOSITION_ROOT,
            "coach_athlete_record_tool_service": COMPOSITION_ROOT,
            "coach_library_plan_tool_service": COMPOSITION_ROOT,
            "coach_profile_update_service": COMPOSITION_ROOT,
            "coach_adaptive_apply_service": COMPOSITION_ROOT,
            "coach_conversation_reset_service": COMPOSITION_ROOT,
            "coach_turn_failure_service": COMPOSITION_ROOT,
            "coach_job_submission_service": COMPOSITION_ROOT,
            "coach_cancellation_service": COMPOSITION_ROOT,
            "coach_clarification_service": COMPOSITION_ROOT,
            "coach_training_patch_service": COMPOSITION_ROOT,
            "coach_planning_command_service": COMPOSITION_ROOT,
            "coach_structured_tool_replay_service": COMPOSITION_ROOT,
            "coach_structured_outcome_service": COMPOSITION_ROOT,
            "coach_structured_tool_preparation_service": COMPOSITION_ROOT,
            "coach_structured_tool_execution_service": COMPOSITION_ROOT,
            "coach_structured_tool_failure_service": COMPOSITION_ROOT,
            "coach_structured_tool_round_journal": COMPOSITION_ROOT,
            "coach_response_retry_policy": COMPOSITION_ROOT,
            "coach_conversation_recovery_service": COMPOSITION_ROOT,
            "COACH_CONVERSATION_GATE": COMPOSITION_ROOT,
            "coach_final_receipt_service": COMPOSITION_ROOT,
            "coach_turn_opening_service": COMPOSITION_ROOT,
            "coach_response_transport": COMPOSITION_ROOT,
            "coach_structured_response_service": COMPOSITION_ROOT,
            "coach_structured_tool_round_service": COMPOSITION_ROOT,
            "coach_structured_turn_service": COMPOSITION_ROOT,
            "coach_chat_turn_service": COMPOSITION_ROOT,
            "morning_coach_job_completion_service": COMPOSITION_ROOT,
            "coach_background_job_runner": COMPOSITION_ROOT,
            "coach_command_receipt_service": COMPOSITION_ROOT,
            "coach_request_payload_service": COMPOSITION_ROOT,
            "recent_log_entries_service": COMPOSITION_ROOT,
            "diagnostic_report_service": COMPOSITION_ROOT,
            "privacy_data_export_service": COMPOSITION_ROOT,
            "privacy_archive_export_service": COMPOSITION_ROOT,
            "privacy_delete_service": COMPOSITION_ROOT,
            "database_backup_service": COMPOSITION_ROOT,
            "database_restore_validation_service": COMPOSITION_ROOT,
            "database_restore_service": COMPOSITION_ROOT,
            "export_stream_transport": COMPOSITION_ROOT,
            "request_handler_class": COMPOSITION_ROOT,
            "RATE_LIMITER": COMPOSITION_ROOT,
            "SESSION_AUTH_SERVICE": COMPOSITION_ROOT,
            "SESSION_AUTH_SIGNATURE": COMPOSITION_ROOT,
            "coach_proposal_read_service": COMPOSITION_ROOT,
            "coach_proposal_creation_service": COMPOSITION_ROOT,
            "coach_proposal_execution_service": COMPOSITION_ROOT,
            "coach_proposal_confirmation_service": COMPOSITION_ROOT,
            "coach_structured_context_service": COMPOSITION_ROOT,
            "coach_training_context_service": COMPOSITION_ROOT,
            "coach_context_preview_service": COMPOSITION_ROOT,
            "sync_public_state_service": COMPOSITION_ROOT,
            "state_version_service": COMPOSITION_ROOT,
            "garmin_projection_service": COMPOSITION_ROOT,
            "sync_state_repository": COMPOSITION_ROOT,
            "performance_refresh_service": COMPOSITION_ROOT,
            "intervals_snapshot_reader": COMPOSITION_ROOT,
            "performance_refresh_followup_service": COMPOSITION_ROOT,
            "sync_job_outcome_service": COMPOSITION_ROOT,
            "intervals_snapshot_service": COMPOSITION_ROOT,
            "intervals_sync_service": COMPOSITION_ROOT,
            "garmin_fixture_loader": COMPOSITION_ROOT,
            "garmin_client_factory": COMPOSITION_ROOT,
            "garmin_payload_service": COMPOSITION_ROOT,
            "garmin_sync_state_service": COMPOSITION_ROOT,
            "garmin_remote_reader": COMPOSITION_ROOT,
            "garmin_sync_service": COMPOSITION_ROOT,
            "external_calendar_sync_service": COMPOSITION_ROOT,
            "competition_sync_reconciler": COMPOSITION_ROOT,
            "competition_sync_service": COMPOSITION_ROOT,
            "planned_unit_sync_state_writer": COMPOSITION_ROOT,
            "planned_calendar_sync_service": COMPOSITION_ROOT,
            "planned_calendar_repair_service": COMPOSITION_ROOT,
            "remote_planned_unit_reconciler": COMPOSITION_ROOT,
            "workout_library_sync_state_service": COMPOSITION_ROOT,
            "workout_library_remote_reconciler": COMPOSITION_ROOT,
            "workout_library_refresh_service": COMPOSITION_ROOT,
            "workout_library_sync_service": COMPOSITION_ROOT,
            "selected_workout_sync_service": COMPOSITION_ROOT,
            "sync_job_executor": COMPOSITION_ROOT,
            "sync_job_worker": COMPOSITION_ROOT,
            "SYNC_JOB_RE": HTTP_API_PACKAGE,
            "SYNC_JOB_RESOLVE_RE": HTTP_API_PACKAGE,
            "DAILY_AUTO_UPDATE_LABEL": SYNC_SCHEDULER,
            "AUTO_UPDATE_LABEL": SYNC_SCHEDULER,
            "_execute_coach_action": COACH_TOOL_EXECUTION,
            "_existing_background_coach_job_response": COACH_JOBS,
            "enqueue_background_coach_job": COACH_JOBS,
            "_execute_claimed_planning_command": COACH_TOOL_EXECUTION,
            "_execute_structured_coach_tool": COACH_TOOL_EXECUTION,
            "_execute_structured_coach_tool_call": COACH_TOOL_EXECUTION,
            "resume_interrupted_coach_jobs": COACH_JOBS,
            "_execute_background_coach_job": COACH_JOBS,
            "enqueue_startup_sync_jobs": SYNC_SCHEDULER,
        }
    return explicit.get(name)


_OWNER_PREFIX_RULES = (
    (("public_",), HTTP_API_PACKAGE),
    (("_morning_body_battery", "_persist_morning_body_battery"), PERFORMANCE_PACKAGE),
    (("_garmin_sleep_recovery",), SYNC_PACKAGE),
    (("_intervals_sleep_recovery", "_performance_", "current_performance_context"), PERFORMANCE_PACKAGE),
    (("_structured_coach_", "_structured_authorized_operations", "_authorized_coach_athlete", "_apply_structured_coach", "_coach_dialogue_"), COACH_CONTEXT),
    (("_diagnostic", "diagnostic_", "_log_http_request_started"), OBSERVABILITY_MODULE),
    (("_audit_", "audit_", "_history", "history_", "_undo", "undo", "list_change", "_change"), HISTORY_PACKAGE),
    (("_safe_url", "_unguessable_url", "_safe_calendar_url", "operation_", "observed_"), OBSERVABILITY_MODULE),
    (("_weather", "weather_", "fetch_weather", "_fetch_weather", "_record_weather", "_refresh_weather", "_invalidate_weather_cache"), WEATHER_PACKAGE),
    (("daily_sync", "schedule_daily", "_schedule_daily", "_enqueue_startup", "_scheduler_"), SYNC_SCHEDULER),
    (("_normalized_", "_pending_", "_existing_", "_historical_", "_execute_", "_queue_next_"), SYNC_PACKAGE),
    (("_cycling_", "parallel_cycling", "intervals_cycling", "is_outdoor", "is_cycling", "_activities_by_", "deduplicate_api", "list_recent_activities"), ACTIVITIES_PACKAGE),
    (("get_activity_details", "duplicate_activity_delete_preview", "_remove_intervals_activity"), ACTIVITIES_PACKAGE),
    (("wellness_", "_atl_", "_wellness_", "actual_atl", "eftp_", "comparison_value", "first_present", "readiness_", "as_number", "sport_setting", "sport_info", "intervals_eftp", "intervals_max_hr", "threshold_pace", "zone2_pace", "height_in_cm"), PERFORMANCE_PACKAGE),
    (("_normalize_fixture_sleep", "_fixture_sleep", "_shift_fixture_sleep", "garmin_"), SYNC_GARMIN),
    (("_retry_after", "_read_http", "_urlopen_", "_http_", "http_json", "_capture_http", "_handle_http", "multipart_form_data"), PROVIDER_HTTP),
    (("_provider_error", "_intervals_error", "_safe_interval_error", "request_ai_provider", "responses_background_request", "output_text"), PROVIDERS_PACKAGE),
    (("_adaptive_", "adaptive_", "_illness_", "illness_", "latest_illness", "_upsert_illness", "_fill_illness", "check_adaptive", "apply_adaptive", "_apply_adaptive", "_record_date", "_weekly_compliance", "compact_", "_is_composite_duration"), PLANNING_PACKAGE),
    (("api_page", "encode_page", "decode_page", "paged_", "state_versions"), "http_api/pagination.py"),
    (("_canonical_", "_local_calendar", "local_calendar", "_repair_calendar", "_repaircalendar", "repaircalendar", "_require_intervals_calendar", "_intervals_calendar", "_intervals_connection", "intervals_public", "_adopt_remote", "_remote_calendar"), CALENDAR_PACKAGE),
    (("delete_duplicate", "assert_duplicate"), COACH_PROPOSALS),
    (("_structured_training", "_structured_adaptive", "_apply_structured_adaptive", "_validated_training", "_record_created_training", "_record_existing_training", "_validate_training_change", "_prepare_structured_training", "_validate_structured_training", "_collect_structured_training", "_apply_structured_training", "_replacement_", "_create_replacement", "_copy_replacement", "_archive_replacement", "_validate_replacement"), PLANNING_PACKAGE),
    (("_structured_artifact", "_structured_action"), COACH_TOOL_EXECUTION),
    (("_repair_manifest", "_validate_repair_manifest", "_refresh_repair_manifest", "_structured_bounded"), COACH_PROPOSALS),
    (("_start_structured_provider", "_run_structured_intervals", "_retry_structured_intervals", "_resolve_structured_sync", "_record_intervals_sync", "_finish_intervals_sync", "_validate_selected_plan_sync", "_persist_selected_plan_sync"), SYNC_PACKAGE),
    (("_dialogue_", "_check_dialogue", "_validate_dialogue", "_alternative_planning_steps", "_profile_repair", "_profile_steps", "_apply_training_patch", "_store_training_patch"), "coach/dialogue.py"),
    (("_planning_command", "_prepare_planning_command", "_execute_planning_command", "execute_planning_command", "_claim_planning_command", "_prepare_commit_planning", "_validate_training_patch"), COACH_TOOL_EXECUTION),
    (("_structured_command_failure", "_persist_structured_command_failure"), COACH_SERVICE),
    (("_provider_usage", "_response_retry"), PROVIDERS_PACKAGE),
    (("provider_refresh", "sync_job", "_sync", "sync_", "enqueue_", "resume_interrupted", "start_sync", "resolve_sync", "garmin_snapshot"), SYNC_PACKAGE),
    (("activity_", "_activity"), ACTIVITIES_PACKAGE),
    (("_checkpoint_database", "client_ip", "allow_rate", "cookie_value", "readiness_state"), HTTP_API_PACKAGE),
    (("_startup_historical",), SYNC_SCHEDULER),
)

_NAME_PREFIX_RULES = (
    (("ASSET_", "STATIC_"), HTTP_API_PACKAGE),
    (("SESSION_", "RATE_LIMIT_"), HTTP_AUTH),
)
_NAME_CONTAINS_RULES = (
    (("OPENAI", "GEMINI"), PROVIDERS_PACKAGE),
    (("GARMIN",), SYNC_GARMIN),
    (("WEATHER",), WEATHER_PACKAGE),
    (("SYNC", "RESYNC"), SYNC_PACKAGE),
    (("COACH", "CHAT"), COACH_PACKAGE),
    (("PLAN", "WORKOUT"), PLANNING_PACKAGE),
)

_PREFERENCE_RULES = (
    (("load_local_env", "config"), CONFIG_MODULE),
    (("setting", "model", "provider", "thinking"), SETTINGS_MODULE),
    (("log", "redact", "sanitize", "secret", "external_call"), OBSERVABILITY_MODULE),
    (("maintenance", "event", "generation"), RUNTIME_PACKAGE),
    (("db", "sql", "repository", "schema", "database"), DB_PACKAGE),
    (("history", "undo"), HISTORY_PACKAGE),
    (("garmin",), SYNC_GARMIN),
    (("activity",), ACTIVITIES_PACKAGE),
    (("performance", "recovery", "vo2", "battery", "fitness"), PERFORMANCE_PACKAGE),
    (("profile", "checkin", "feedback", "athlete"), ATHLETE_PACKAGE),
    (("competition", "race"), PLANNING_COMPETITIONS),
    (("ical", CALENDAR_TOKEN, "byday", "recurrence"), PROVIDER_CALENDAR),
    (("weather",), WEATHER_PACKAGE),
    (("workout", "library", "planned", "training_plan", "plan_", "planning"), PLANNING_PACKAGE),
    (("openai", "gemini", "transcri", "responses_request", "audio"), PROVIDERS_PACKAGE),
    (("context", "prompt", "coach", "conversation", "chat"), COACH_PACKAGE),
    (("proposal", "authoriz", "scope", "tool"), COACH_PACKAGE),
    (("stream",), COACH_STREAMS),
    (("job", "queue", "worker"), COACH_JOBS),
    (("morning",), COACH_MORNING),
    (("backup", "restore", "export"), BACKUP_PACKAGE),
    (("privacy", "delete"), PRIVACY_MODULE),
    (("http", "request", "response", "handler", "session", "csrf", "auth", "pagination"), HTTP_API_PACKAGE),
    (("scheduler", "daily"), SYNC_SCHEDULER),
    (("sync", "resync", "refresh", "cursor", "snapshot", "reconcile"), SYNC_PACKAGE),
)

def _owner_from_exact_names(name: str, lowered: str) -> str | None:
    if name.startswith(("SESSION_", "RATE_LIMIT_")):
        return HTTP_AUTH
    if lowered in {"_record_change", "list_change_history"}:
        return HISTORY_PACKAGE
    if lowered in {"get_kv", "set_kv"}:
        return SETTINGS_MODULE
    if lowered in {"selected", "coach_quick_actions_state"}:
        return PLANNING_PACKAGE if lowered == "selected" else COACH_CONTEXT
    if lowered in {"delete_duplicate_activity", "duplicate_activity_delete_preview"}:
        return ACTIVITIES_PACKAGE
    if lowered.startswith("_retry_after"):
        return PROVIDER_HTTP
    if lowered == "main":
        return COMPOSITION_ROOT
    return None


def _owner_from_prefixes(lowered: str) -> str | None:
    for prefixes, target in _OWNER_PREFIX_RULES:
        if lowered.startswith(prefixes):
            if prefixes == ("delete_duplicate", "assert_duplicate"):
                return ACTIVITIES_PACKAGE if lowered.startswith("delete") else COACH_PROPOSALS
            return target
    return None


def _owner_from_uppercase(name: str) -> str | None:
    if name.endswith(("_SQL", "_ERROR", "_ERRORS")):
        return DB_PACKAGE if name.endswith("_SQL") else ERRORS_MODULE
    for prefixes, target in _NAME_PREFIX_RULES:
        if name.startswith(prefixes):
            return target
    for fragments, target in _NAME_CONTAINS_RULES:
        if any(fragment in name for fragment in fragments):
            return target
    return None


def _owner_from_candidates(lowered: str, candidates: tuple[str, ...]) -> str | None:
    for words, preferred in _PREFERENCE_RULES:
        if not any(word in lowered for word in words):
            continue
        exact = next((candidate for candidate in candidates if candidate == preferred), None)
        if exact:
            return exact
        compatible = next((candidate for candidate in candidates if preferred.rstrip("/").split("/")[0] in candidate), None)
        if compatible:
            return compatible
    return candidates[0] if len(candidates) == 1 else None


def _candidate_for_name(name: str, candidates: tuple[str, ...]) -> str:
    lowered = name.lower()
    resolvers = (
        _explicit_owner,
        lambda value: _owner_from_exact_names(value, lowered),
        lambda value: _owner_from_prefixes(lowered),
        _owner_from_uppercase,
    )
    for resolver in resolvers:
        target = resolver(name)
        if target:
            return target
    target = _owner_from_candidates(lowered, candidates)
    return target or "unklar: " + ", ".join(candidates)


_PHASE_RULES = (
    (("config", "errors", "observability", "runtime", "settings", "db"), "P1"),
    (("providers",), "P2"),
    (("scheduler", "coach/jobs", "coach/streams", "coach/morning"), "P8"),
    (("sync",), "P6"),
    (("planning",), "P4"),
    (("activities", "performance", "athlete", CALENDAR_TOKEN, "weather"), "P3"),
    (("history",), "P5"),
    (("coach",), "P7"),
    (("backup", "privacy", "diagnostics"), "P9"),
    (("http_api",), "P10"),
)


def phase_for_target(target: str) -> str:
    if target.startswith("unklar"):
        return "P0 (Zuordnung offen)"
    lowered = target.lower()
    for fragments, phase in _PHASE_RULES:
        if any(fragment in lowered for fragment in fragments):
            return phase
    return "P11"


def _node_end(node: ast.AST) -> int:
    return getattr(node, END_LINE_ATTRIBUTE, node.lineno)


def _candidates_for_line(line: int, ranges: tuple[PlanRange, ...]) -> tuple[str, ...]:
    plan_range = range_for(line, ranges)
    return plan_range.targets if plan_range else ()


def _import_item(
    node: ast.Import | ast.ImportFrom,
    name: str,
    imported_module: str,
    candidates: tuple[str, ...],
    nested: bool,
) -> InventoryItem:
    if nested:
        target = _candidate_for_name(name, candidates)
        return InventoryItem(
            KIND_GLOBAL, name, node.lineno, _node_end(node), imported_module, target,
            phase_for_target(target), STATUS_OPEN, node, imported_module,
        )
    target = imported_module.split(":", 1)[0]
    if target.startswith(BACKEND_DIR):
        target = target.replace(".", "/")
        status = "bereits ausgelagert (Importbindung)"
    else:
        target = COMPOSITION_ROOT
        status = "bestehende Infrastrukturbindung"
    phase = "P1" if target.startswith(BACKEND_DIR) else "P11"
    return InventoryItem(
        KIND_IMPORT, name, node.lineno, _node_end(node), imported_module, target,
        phase, status, node, imported_module,
    )


def _import_items(
    node: ast.Import | ast.ImportFrom,
    candidates: tuple[str, ...],
    nested: bool,
    seen: set[str],
) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    for name, imported_module in _import_bindings(node):
        if nested and name in seen:
            continue
        seen.add(name)
        items.append(_import_item(node, name, imported_module, candidates, nested))
    return items


def _definition_item(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    candidates: tuple[str, ...],
) -> InventoryItem:
    kind = KIND_CLASS if isinstance(node, ast.ClassDef) else KIND_FUNCTION
    target = _candidate_for_name(node.name, candidates)
    return InventoryItem(
        kind, node.name, node.lineno, _node_end(node), SERVER_MODULE, target,
        phase_for_target(target), STATUS_OPEN, node,
    )


def _assignment_items(
    node: ast.Assign | ast.AnnAssign | ast.AugAssign,
    candidates: tuple[str, ...],
    seen: set[str],
) -> list[InventoryItem]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    items: list[InventoryItem] = []
    for target_node in targets:
        for name in _bound_names(target_node):
            if name in seen:
                continue
            seen.add(name)
            target = _candidate_for_name(name, candidates)
            status = STATUS_OPEN
            if name in {"ROOT", "PUBLIC_DIR", "APP_VERSION"}:
                target = COMPOSITION_ROOT
                status = "verbleibt bis P11 (prüfen)"
            items.append(
                InventoryItem(
                    KIND_GLOBAL, name, node.lineno, _node_end(node), SERVER_MODULE, target,
                    phase_for_target(target), status, node,
                )
            )
    return items


def make_items(tree: ast.Module, ranges: tuple[PlanRange, ...]) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    direct_nodes = {id(node) for node in tree.body}
    seen_global_names: set[str] = set()
    nodes = sorted(_module_scope_nodes(tree.body), key=lambda item: (item.lineno, item.col_offset))
    for node in nodes:
        candidates = _candidates_for_line(node.lineno, ranges)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            items.extend(_import_items(node, candidates, id(node) not in direct_nodes, seen_global_names))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            items.append(_definition_item(node, candidates))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            items.extend(_assignment_items(node, candidates, seen_global_names))
    return items


def _reference_roots() -> tuple[Path, ...]:
    return tuple(ROOT / directory for directory in (BACKEND_DIR, "tests", "e2e", SCRIPTS_DIR, GITHUB_DIR))


def _is_reference_file(path: Path) -> bool:
    excluded_parts = {"__pycache__", ".git", "data"}
    if not path.is_file() or any(part in excluded_parts for part in path.parts):
        return False
    if path.resolve() == (ROOT / SCRIPTS_DIR / "server_extraction_inventory.py").resolve():
        return False
    return not path.name.startswith(".env") and path.suffix.lower() not in {".db", ".log"}


def _files_under_root(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [path for path in directory.rglob("*") if _is_reference_file(path)]


def reference_files() -> tuple[Path, ...]:
    result = [path for root in _reference_roots() for path in _files_under_root(root)]
    result.extend(path for path in (ROOT / "Dockerfile", ROOT / "docker-compose.yml") if path.exists())
    return tuple(sorted(set(result)))


def _category(path: Path) -> str:
    relative = path.relative_to(ROOT)
    if relative.parts[0] == GITHUB_DIR:
        return "Workflows/CI"
    return relative.parts[0] if relative.parts else "Repository"


def _location(path: Path, line: int) -> str:
    parts = path.relative_to(ROOT).parts
    display = "/".join(parts[2:]) if parts[:2] == (GITHUB_DIR, "workflows") else "/".join(parts[1:])
    if not display:
        display = parts[0]
    return f"{_category(path)}/{display}:{line}"


SERVER_ALIAS_PATTERN = re.compile(r"^\s*import\s+server\s+as\s+(\w+)")
MEMBER_PATTERN = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)\b")
LITERAL_PATTERN = re.compile(r"[\"']([A-Za-z_]\w*)[\"']")
IMPORT_PATTERN = re.compile(r"\bfrom\s+server\s+import\b")
IMPORT_NAME_PATTERN = re.compile(r"\b[A-Za-z_]\w*\b")
DYNAMIC_TOKENS = ("getattr", "sys.modules", "monkeypatch", "patch.object", "patch(")


def _line_mentions_alias(line: str, aliases: set[str]) -> bool:
    return "server" in line or any(alias in line for alias in aliases)


def _member_references(line: str, path: Path, number: int, names: set[str], aliases: set[str]) -> list[tuple[str, str]]:
    location = _location(path, number)
    return [
        (name, f"{location} (direkt/dynamisch unklar)")
        for receiver, name in MEMBER_PATTERN.findall(line)
        if receiver in aliases and name in names
    ]


def _dynamic_references(line: str, path: Path, number: int, names: set[str]) -> tuple[str | None, list[tuple[str, str]]]:
    if not any(token in line for token in DYNAMIC_TOKENS):
        return None, []
    location = _location(path, number)
    dynamic = f"{location}: {line.strip()}"
    references = [
        (name, f"{location} (Monkeypatch/getattr/sys.modules)")
        for name in LITERAL_PATTERN.findall(line)
        if name in names
    ]
    return dynamic, references


def _import_references(line: str, path: Path, number: int, names: set[str]) -> list[tuple[str, str]]:
    if not IMPORT_PATTERN.search(line):
        return []
    location = _location(path, number)
    imported = line.split("import", 1)[1]
    return [(name, f"{location} (Import)") for name in IMPORT_NAME_PATTERN.findall(imported) if name in names]


def _scan_reference_file(path: Path, names: set[str], aliases: set[str]) -> tuple[list[tuple[str, str]], list[str]]:
    try:
        lines = path.read_text(encoding=ENCODING_UTF8, errors="replace").splitlines()
    except OSError:
        return [], []
    references: list[tuple[str, str]] = []
    dynamic: list[str] = []
    for number, line in enumerate(lines, 1):
        alias_match = SERVER_ALIAS_PATTERN.match(line)
        if alias_match:
            aliases.add(alias_match.group(1))
        if not _line_mentions_alias(line, aliases):
            continue
        references.extend(_member_references(line, path, number, names, aliases))
        dynamic_entry, dynamic_references = _dynamic_references(line, path, number, names)
        if dynamic_entry:
            dynamic.append(dynamic_entry)
            references.extend(dynamic_references)
        references.extend(_import_references(line, path, number, names))
    return references, dynamic


def collect_references(items: list[InventoryItem]) -> tuple[dict[str, list[str]], list[str]]:
    names = {item.name for item in items}
    aliases = {"server"}
    collected: list[tuple[str, str]] = []
    dynamic: list[str] = []
    for path in reference_files():
        references, dynamic_entries = _scan_reference_file(path, names, aliases)
        collected.extend(references)
        dynamic.extend(dynamic_entries)
    grouped: dict[str, list[str]] = defaultdict(list)
    for name, location in collected:
        grouped[name].append(location)
    return {name: sorted(set(values)) for name, values in grouped.items()}, sorted(set(dynamic))


class DependencyVisitor(ast.NodeVisitor):
    def __init__(self, global_names: set[str], definition_names: set[str]) -> None:
        self.global_names = global_names
        self.definition_names = definition_names
        self.reads: set[str] = set()
        self.writes: set[str] = set()
        self.calls: set[str] = set()
        self.imports: set[str] = set()
        self.local_names: set[str] = set()
        self.explicit_globals: set[str] = set()

    def visit_Global(self, node: ast.Global) -> None:
        self.explicit_globals.update(node.names)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in self.global_names:
            return
        if isinstance(node.ctx, ast.Load):
            self.reads.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.writes.add(node.id)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in self.definition_names:
            self.calls.add(node.func.id)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.add("." * node.level + (node.module or ""))


def dependencies(items: list[InventoryItem]) -> dict[str, tuple[set[str], set[str], set[str], set[str]]]:
    definitions = {item.name for item in items if item.kind in {KIND_FUNCTION, KIND_CLASS}}
    globals_ = {item.name for item in items}
    result: dict[str, tuple[set[str], set[str], set[str], set[str]]] = {}
    for item in items:
        if item.kind not in {KIND_FUNCTION, KIND_CLASS} or item.node is None:
            continue
        visitor = DependencyVisitor(globals_, definitions)
        visitor.visit(item.node)
        local_names: set[str] = set()
        if isinstance(item.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_names.update(arg.arg for arg in item.node.args.posonlyargs)
            local_names.update(arg.arg for arg in item.node.args.args + item.node.args.kwonlyargs)
            if item.node.args.vararg:
                local_names.add(item.node.args.vararg.arg)
            if item.node.args.kwarg:
                local_names.add(item.node.args.kwarg.arg)
        reads = {name for name in visitor.reads if name not in local_names or name in visitor.explicit_globals}
        writes = {name for name in visitor.writes if name not in local_names or name in visitor.explicit_globals}
        result[item.name] = (visitor.calls, reads, writes, visitor.imports)
    return result


@dataclass
class _SccState:
    next_index: int = 0
    indices: dict[str, int] = field(default_factory=dict)
    lowlinks: dict[str, int] = field(default_factory=dict)
    stack: list[str] = field(default_factory=list)
    on_stack: set[str] = field(default_factory=set)
    components: list[tuple[str, ...]] = field(default_factory=list)


def _pop_component(name: str, graph: dict[str, set[str]], state: _SccState) -> None:
    component: list[str] = []
    while True:
        successor = state.stack.pop()
        state.on_stack.remove(successor)
        component.append(successor)
        if successor == name:
            break
    if len(component) > 1 or name in graph.get(name, set()):
        state.components.append(tuple(sorted(component)))


def _visit_scc(name: str, graph: dict[str, set[str]], state: _SccState) -> None:
    state.indices[name] = state.lowlinks[name] = state.next_index
    state.next_index += 1
    state.stack.append(name)
    state.on_stack.add(name)
    for successor in sorted(graph.get(name, ())):
        if successor not in state.indices:
            _visit_scc(successor, graph, state)
            state.lowlinks[name] = min(state.lowlinks[name], state.lowlinks[successor])
        elif successor in state.on_stack:
            state.lowlinks[name] = min(state.lowlinks[name], state.indices[successor])
    if state.lowlinks[name] == state.indices[name]:
        _pop_component(name, graph, state)


def strongly_connected_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    state = _SccState()
    for name in sorted(graph):
        if name not in state.indices:
            _visit_scc(name, graph, state)
    return sorted(state.components)


def _format_names(values: set[str] | list[str], limit: int = 12) -> str:
    ordered = sorted(values)
    if not ordered:
        return "–"
    if len(ordered) > limit:
        return ", ".join(f"`{value}`" for value in ordered[:limit]) + f", … (+{len(ordered) - limit})"
    return ", ".join(f"`{value}`" for value in ordered)


def _phase_distribution_lines(counts: Counter[tuple[str, str]]) -> list[str]:
    lines: list[str] = []
    for phase_number in range(12):
        phase = f"P{phase_number}" if phase_number else "P0 (Zuordnung offen)"
        definitions = counts[(KIND_FUNCTION, phase)] + counts[(KIND_CLASS, phase)]
        lines.append(
            f"| {phase} | {definitions} | {counts[(KIND_GLOBAL, phase)]} | "
            f"{counts[(KIND_IMPORT, phase)]} |"
        )
    return lines


def _reference_analysis_lines(dynamic: list[str]) -> list[str]:
    if not dynamic:
        return [
            (
                "Keine dynamischen Zugriffe, Monkeypatches oder `sys.modules`-Stellen "
                "außerhalb von `server.py` gefunden."
            ),
            "",
        ]
    return [
        "### Dynamische Zugriffe und Monkeypatches",
        "",
        "Diese Stellen benötigen bei jeder Migration eine manuelle Prüfung des Lookup-Ortes:",
        "",
        *(f"- `{entry}`" for entry in dynamic),
        "",
    ]


def _p1_dependency_lines(
    items: list[InventoryItem],
    deps: dict[str, tuple[set[str], set[str], set[str], set[str]]],
) -> list[str]:
    lines: list[str] = []
    for item in items:
        if item.kind not in {KIND_FUNCTION, KIND_CLASS} or item.line > 2999:
            continue
        calls, reads, writes, imports = deps.get(item.name, (set(), set(), set(), set()))
        lines.append(
            f"| `{item.name}` | {item.line} | {_format_names(calls)} | "
            f"{_format_names(reads)} | {_format_names(writes)} | {_format_names(imports)} |"
        )
    return lines


def _cycle_lines(cycles: list[tuple[str, ...]]) -> list[str]:
    if not cycles:
        return [
            (
                "Keine zyklische Gruppe im direkten lokalen Aufrufgraphen erkannt; "
                "dynamische Rückrufe sind damit nicht ausgeschlossen."
            )
        ]
    return [
        (
            f"Statisch erkannte SCCs im direkten lokalen Aufrufgraphen: {len(cycles)}. "
            "Jede Gruppe ist als gemeinsame Umzugseinheit zu prüfen."
        ),
        "",
        *(f"- {', '.join(f'`{name}`' for name in component)}" for component in cycles),
    ]


def _inventory_table_lines(
    items: list[InventoryItem], references: dict[str, list[str]]
) -> list[str]:
    lines: list[str] = []
    for item in items:
        refs = "; ".join(references.get(item.name, [])) or "keine statisch gefunden"
        lines.append(
            f"| {item.kind} | `{item.name}` | {item.line} | `{item.target}` | "
            f"{item.phase} | {item.status} | {refs} |"
        )
    return lines


def build_document() -> str:
    source = SERVER_PATH.read_text(encoding=ENCODING_UTF8)
    tree = ast.parse(source, filename=str(SERVER_PATH))
    ranges = read_plan_ranges()
    items = make_items(tree, ranges)
    references, dynamic = collect_references(items)
    deps = dependencies(items)
    definition_names = {item.name for item in items if item.kind in {KIND_FUNCTION, KIND_CLASS}}
    graph = {name: set(deps.get(name, (set(), set(), set(), set()))[0]) & definition_names for name in definition_names}
    cycles = strongly_connected_components(graph)
    counts = Counter((item.kind, item.phase) for item in items)
    target_counts = Counter(item.target for item in items)
    source_lines = len(source.splitlines())
    plan_end = max(item.end for item in ranges)
    outside_plan = [item for item in items if item.line > plan_end]
    source_fingerprint = hashlib.sha256(source.encode(ENCODING_UTF8)).hexdigest()

    lines = [
        "# Statisches Inventar für die server.py-Auslagerung",
        "",
        "> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.",
        "",
        "## Ausgangsstand",
        "",
        f"- Geprüfter P0-Basiscommit: `{P0_BASE_COMMIT}`",
        f"- Inventarisierter `server.py`-Quelltext (SHA-256): `{source_fingerprint}`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.",
        f"- `{SERVER_MODULE}`: {source_lines:,} physische Zeilen".replace(",", "."),
        f"- Inventareinträge: {len(items):,}".replace(",", "."),
        f"- Definitionen (Funktionen/Klassen): {len(definition_names):,}".replace(",", "."),
        f"- Globale Bindungen einschließlich Imports: {sum(item.kind == KIND_GLOBAL for item in items):,} Zuweisungen, {sum(item.kind == KIND_IMPORT for item in items):,} Imports".replace(",", "."),
        f"- Planbereich: bis Zeile {plan_end:,}; Einträge dahinter: {len(outside_plan):,} (zielbestimmt über Symbol-/Verantwortungsanalyse)".replace(",", "."),
        "- Status dieses Stands: P0 ist integriert; bereits ausgelagerte Namen erscheinen als Importbindungen. `offen` bedeutet, dass die fachliche Eigentümerschaft noch migriert werden muss.",
        "",
        "## Reproduzierbare Prüfungen",
        "",
        "```text",
        "python scripts/server_extraction_inventory.py",
        "python scripts/server_extraction_inventory.py --check",
        "python -m py_compile scripts/server_extraction_inventory.py",
        "git diff --check",
        "python -m unittest discover -s tests -v",
        "```",
        "Baseline am unveränderten Ausgangs-HEAD `362d6ca` (separater isolierter Worktree): `python -m unittest discover -s tests -v` — 779 Tests, 12 übersprungen, OK; `python -m compileall -q server.py backend` — PASS; `git diff --check` — PASS.",
        "Infrastruktur-Baseline: `docker build -t ai-coach:server-extraction-baseline .` konnte wegen nicht erreichbarer Docker-API (`npipe`, Docker-Desktop-Daemon unavailable) nicht starten; deshalb wurde E2E nicht gegen einen isolierten Server ausgeführt. Das ist ein externer Infrastruktur-Befund, kein Codefehler.",
        "Der Generator führt selbst keine Tests und keine Laufzeitinitialisierung aus. Synthetische/temporäre Testdaten und gemockte Provider sind verbindlich.",
        "",
        "## Verteilung",
        "",
        "| Phase | Funktionen/Klassen | Globale Bindungen | Importbindungen |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines.extend(_phase_distribution_lines(counts))
    lines += ["", "## Referenzanalyse außerhalb von server.py", "", "Direkte `server.<name>`-Zugriffe und erkennbare Import-/Patchstellen sind pro Eintrag in der Tabelle vermerkt. Die Ortsangaben decken `backend/`, `tests/`, `e2e/`, `scripts/`, Docker und GitHub-Workflows ab.", ""]
    lines.extend(_reference_analysis_lines(dynamic))
    lines += ["## P1-Aufruf- und Zustandsabhängigkeiten", "", "Die folgende Tabelle ist die statische Grundlage für P1. Reads/Writes sind nur Namen, die im globalen Modulnamespace gebunden werden; lokale Variablen werden soweit AST-statisch erkennbar ausgefiltert. Dynamische Attribute, Closure-Zustand und indirekte Callbacks bleiben unsicher.", "", "| Definition | Zeile | Direkte lokale Aufrufe | Globale Reads | Globale Writes | Imports im Body |", "| --- | ---: | --- | --- | --- | --- |"]
    lines.extend(_p1_dependency_lines(items, deps))
    lines += ["", "### Zyklische Gruppen", ""]
    lines.extend(_cycle_lines(cycles))
    lines += ["", "## Vollständiges Inventar", "", "`Zielmodul` und `Phase` folgen der Bereichstabelle des vollständigen Plans. Jede Zuordnung ist konkret; eine künftig neu hinzukommende nicht auflösbare Bindung wird als offen markiert und darf nicht stillschweigend erfunden werden. `Status` beschreibt den jeweils inventarisierten Stand.", "", "| Art | Quellname | Ausgangszeile | Zielmodul | Phase | Status | Referenzen außerhalb von server.py |", "| --- | --- | ---: | --- | --- | --- | --- |"]
    lines.extend(_inventory_table_lines(items, references))
    lines += ["", "## Zielverteilung", "", "| Zielmodul | Einträge |", "| --- | ---: |"]
    lines.extend(f"| `{target}` | {count} |" for target, count in sorted(target_counts.items()))
    lines += ["", "## Grenzen und offene Unsicherheiten", "", "- AST-Aufrufauflösung erfasst nur direkte lokale Aufrufe; `getattr`, `globals()`, `sys.modules`, dekoratorbasierte Registrierung und Callback-Injektion benötigen eine manuelle Nachprüfung.", "- Ein Name kann in mehreren Kategorien mit derselben Schreibweise vorkommen; Referenzzählungen sind deshalb namensbasiert und zeigen Ortsangaben, nicht vermeintliche Laufzeitidentität.", "- Die Tabelle enthält bewusst auch Importbindungen, damit Rückimporte, spätere Re-Exports und der endgültige Composition-Root-Inhalt überprüfbar bleiben.", "- Offene Zielzuordnungen müssen vor dem jeweiligen Umzug fachlich entschieden werden; sie gelten nicht als erledigt.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the generated document differs")
    args = parser.parse_args(argv)
    document = build_document()
    if args.check:
        if not DOC_PATH.exists() or DOC_PATH.read_text(encoding=ENCODING_UTF8) != document:
            print(f"{DOC_PATH} is stale; run python scripts/server_extraction_inventory.py", file=sys.stderr)
            return 1
        return 0
    DOC_PATH.write_text(document, encoding=ENCODING_UTF8)
    print(f"wrote {DOC_PATH} ({len(document.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
