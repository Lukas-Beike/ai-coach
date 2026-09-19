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
COACH_PACKAGE = "coach/"
COACH_CONVERSATION = "coach/conversation.py"
COACH_CONTEXT = "coach/context.py"
COACH_JOBS = "coach/jobs.py"
COACH_MORNING = "coach/morning.py"
COACH_PROPOSALS = "coach/proposals.py"
COACH_STREAMS = "coach/streams.py"
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
SETTINGS_MODULE = "settings.py"
ACTIVITIES_PACKAGE = "activities/"
ATHLETE_PACKAGE = "athlete/"
PERFORMANCE_PACKAGE = "performance/"
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
            "serialise_conversation": COACH_CONVERSATION,
            "utc_now": RUNTIME_PACKAGE,
            "AppError": ERRORS_MODULE,
            "public_app_error_status": ERRORS_MODULE,
            "ClientDisconnected": ERRORS_MODULE,
            "security_configuration_error": CONFIG_MODULE,
            "database_manager": DB_MANAGER,
            "database": DB_MANAGER,
            "initialise_database": "db/bootstrap.py",
            "external_call": PROVIDER_HTTP,
            "external_result_context": OBSERVABILITY_MODULE,
            "provider_error": ERRORS_MODULE,
            "CoachHTTPServer": HTTP_API_PACKAGE,
            "login_user": HTTP_AUTH,
            "logout_user": HTTP_AUTH,
            "bootstrap_provider_states": "http_api/bootstrap.py",
            "VERSIONED_STATIC_ASSETS": HTTP_API_PACKAGE,
            "UTC_OFFSET_SUFFIX": CONFIG_MODULE,
            "ISO_MIDNIGHT_SUFFIX": CONFIG_MODULE,
            "JSON_MEDIA_TYPE": HTTP_API_PACKAGE,
            "OCTET_STREAM_MIME": HTTP_API_PACKAGE,
            "VO2MAX_UNIT": PERFORMANCE_PACKAGE,
            "LOCAL_INTERVALS_SCOPE": "coach/authorization.py",
            "WORKDAY_TIME_LABEL": COACH_CONTEXT,
            "APP_NAME": CONFIG_MODULE,
            "UUID_PATTERN": HTTP_API_PACKAGE,
            "PAYLOAD_HASH_PATTERN": PLANNING_PACKAGE,
            "DATE_ONLY_PATTERN": PLANNING_PACKAGE,
            "MAX_BODY_BYTES": HTTP_API_PACKAGE,
            "MAX_AUDIO_BODY_BYTES": HTTP_API_PACKAGE,
            "MAX_BACKUP_BYTES": BACKUP_PACKAGE,
            "MAX_PRIVACY_EXPORT_BYTES": PRIVACY_MODULE,
            "MIN_EXPORT_FREE_BYTES": BACKUP_PACKAGE,
            "EXPORT_TIME_LIMIT_SECONDS": BACKUP_PACKAGE,
            "STREAM_CHUNK_BYTES": COACH_STREAMS,
            "MAX_EXTERNAL_CALENDAR_BYTES": PROVIDER_CALENDAR,
            "CALENDAR_FETCH_TIMEOUT_SECONDS": PROVIDER_CALENDAR,
            "CALENDAR_CONNECTION_TIMEOUT_SECONDS": PROVIDER_CALENDAR,
            "MAX_EXTERNAL_RESPONSE_BYTES": PROVIDER_HTTP,
            "MESSAGE_ATTACHMENTS_QUERY": COACH_CONVERSATION,
            "SESSIONS": HTTP_AUTH,
            "RATE_LIMITS": HTTP_AUTH,
            "COMPETITION_EXTERNAL_PREFIX": PLANNING_COMPETITIONS,
            "CALENDAR_DISPLAY_DEFAULTS": SETTINGS_MODULE,
            "CALENDAR_DISPLAY_MAX_WEEKS": SETTINGS_MODULE,
            "URL_VALUE_RE": OBSERVABILITY_MODULE,
            "DEFAULT_PROFILE": ATHLETE_PACKAGE,
            "NRW_LATITUDE_BOUNDS": WEATHER_PACKAGE,
            "NRW_LONGITUDE_BOUNDS": WEATHER_PACKAGE,
            "MORNING_RETRY_SECONDS": COACH_MORNING,
            "MORNING_MAX_ATTEMPTS": COACH_MORNING,
            "LIBRARY_BULK_MAX_ENTRIES": PLANNING_PACKAGE,
            "LIBRARY_BULK_PREVIEW_TTL_SECONDS": COACH_PROPOSALS,
            "LIBRARY_BULK_LOCAL_ACTIONS": PLANNING_PACKAGE,
            "DEFAULT_TIMEZONE": CONFIG_MODULE,
            "ATHLETE_RECORD_HANDLERS": ATHLETE_PACKAGE,
            "DB_LOCK": DB_MANAGER,
            "DATABASE_MANAGER": DB_MANAGER,
            "DATABASE_MANAGER_SIGNATURE": DB_MANAGER,
            "SYNC_LOCK": SYNC_PACKAGE,
            "WORKOUT_LIBRARY_SYNC_LOCK": SYNC_PACKAGE,
            "COMPETITION_SYNC_LOCK": "sync/competitions.py",
            "PERFORMANCE_LOCK": PERFORMANCE_PACKAGE,
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
            "EXTERNAL_CALENDAR_LOCK": CALENDAR_PACKAGE,
            "SYNC_JOB_WORKER_LOCK": SYNC_PACKAGE,
            "SYNC_JOB_WAKE": SYNC_PACKAGE,
            "SYNC_JOB_STOP": SYNC_PACKAGE,
            "SYNC_JOB_WORKER": SYNC_PACKAGE,
            "SESSION_LOCK": HTTP_AUTH,
            "RATE_LIMIT_LOCK": HTTP_AUTH,
            "STATE_EVENT_CONDITION": RUNTIME_EVENTS,
            "STATE_EVENTS": RUNTIME_EVENTS,
            "STATE_EVENT_NEXT_ID": RUNTIME_EVENTS,
            "MAINTENANCE_GATE": RUNTIME_MAINTENANCE,
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
            "_require_command_owner": "coach/authorization.py",
            "_prepare_structured_plan_sync": SYNC_PACKAGE,
            "sync_weather": SYNC_PACKAGE,
            "sync_illness_pause_to_intervals": SYNC_PACKAGE,
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
            "_publish_sync_job_result_event": "sync/jobs.py",
            "_update_local_planned_workout_in_db": "planning/calendar.py",
            "readiness_state": PERFORMANCE_PACKAGE,
            "save_snapshot_view": "sync/snapshots.py",
            "set_sync_operation_state": "sync/status.py",
            "coach_context_json_size": COACH_CONTEXT,
            "bounded_coach_context_value": COACH_CONTEXT,
            "bounded_coach_context_sections": COACH_CONTEXT,
            "coach_context_projection_meta": COACH_CONTEXT,
            "coach_intervals_context": COACH_CONTEXT,
            "structured_athlete_context": COACH_CONTEXT,
            "build_training_context": COACH_CONTEXT,
            "context_preview": COACH_CONTEXT,
            "_openai_usage_summary_unlocked": PROVIDERS_PACKAGE,
            "openai_usage_summary": PROVIDERS_PACKAGE,
            "_record_openai_usage_unlocked": PROVIDERS_PACKAGE,
            "record_openai_usage": PROVIDERS_PACKAGE,
            "_validate_openai_response": PROVIDERS_PACKAGE,
            "openai_request": PROVIDERS_PACKAGE,
            "transcribe_audio": PROVIDERS_PACKAGE,
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
            "database_backup_bytes": BACKUP_PACKAGE,
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
            "CSRF_COOKIE": HTTP_AUTH,
            "session_token_hash": HTTP_AUTH,
            "session_timestamp": HTTP_AUTH,
            "cleanup_expired_sessions": HTTP_AUTH,
            "authenticated_session": HTTP_AUTH,
        }
    return explicit.get(name)


_OWNER_PREFIX_RULES = (
    (("public_",), HTTP_API_PACKAGE),
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
    (("_structured_artifact", "_structured_action"), "coach/tool_execution.py"),
    (("_repair_manifest", "_validate_repair_manifest", "_refresh_repair_manifest", "_structured_bounded"), COACH_PROPOSALS),
    (("_start_structured_provider", "_run_structured_intervals", "_retry_structured_intervals", "_resolve_structured_sync", "_record_intervals_sync", "_finish_intervals_sync", "_validate_selected_plan_sync", "_persist_selected_plan_sync"), SYNC_PACKAGE),
    (("_dialogue_", "_check_dialogue", "_validate_dialogue", "_alternative_planning_steps", "_profile_repair", "_profile_steps", "_apply_training_patch", "_store_training_patch"), "coach/dialogue.py"),
    (("_planning_command", "_prepare_planning_command", "_execute_planning_command", "execute_planning_command", "_claim_planning_command", "_prepare_commit_planning", "_validate_training_patch"), "coach/tool_execution.py"),
    (("_structured_command_failure", "_persist_structured_command_failure"), "coach/service.py"),
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
    (("activities", "performance", "athlete", CALENDAR_TOKEN, "weather"), "P3"),
    (("planning",), "P4"),
    (("history",), "P5"),
    (("scheduler", "coach/jobs", "coach/streams", "coach/morning"), "P8"),
    (("sync",), "P6"),
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
