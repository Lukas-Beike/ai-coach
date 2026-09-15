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
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "server.py"
PLAN_PATH = ROOT / "docs" / "server-monolith-extraction-plan.md"
DOC_PATH = ROOT / "docs" / "server-extraction-inventory.md"
P0_BASE_COMMIT = "362d6caa4c27951af86b82b11b3a43d48dadceee"


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
    pattern = re.compile(r"^\|\s*([0-9][0-9.]*)\s*[–-]\s*([0-9][0-9.]*)\s*\|")
    for line in PLAN_PATH.read_text(encoding="utf-8").splitlines():
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


def _candidate_for_name(name: str, candidates: tuple[str, ...]) -> str:
    """Choose a concrete plan target, or preserve ambiguity explicitly."""

    lowered = name.lower()
    explicit = {
        "publish_state_event": "runtime/events.py",
        "state_events_since": "runtime/events.py",
        "maintenance_operation": "runtime/maintenance.py",
        "claimed_maintenance_operation": "runtime/maintenance.py",
        "MaintenanceGate": "runtime/maintenance.py",
        "ProviderResyncGate": "sync/",
        "provider_operation": "sync/",
        "intervals_operation": "sync/",
        "garmin_operation": "sync/garmin.py",
        "IntervalsClient": "providers/intervals_client.py",
        "serialise_conversation": "coach/conversation.py",
        "utc_now": "runtime/",
        "AppError": "errors.py",
        "public_app_error_status": "errors.py",
        "ClientDisconnected": "errors.py",
        "security_configuration_error": "config.py",
        "database_manager": "db/manager.py",
        "database": "db/manager.py",
        "initialise_database": "db/schema.py",
        "external_call": "providers/http.py",
        "external_result_context": "observability.py",
        "provider_error": "errors.py",
        "CoachHTTPServer": "http_api/",
        "VERSIONED_STATIC_ASSETS": "http_api/",
        "UTC_OFFSET_SUFFIX": "config.py",
        "ISO_MIDNIGHT_SUFFIX": "config.py",
        "JSON_MEDIA_TYPE": "http_api/",
        "OCTET_STREAM_MIME": "http_api/",
        "VO2MAX_UNIT": "performance/",
        "LOCAL_INTERVALS_SCOPE": "coach/authorization.py",
        "WORKDAY_TIME_LABEL": "coach/context.py",
        "APP_NAME": "config.py",
        "UUID_PATTERN": "http_api/",
        "PAYLOAD_HASH_PATTERN": "planning/",
        "DATE_ONLY_PATTERN": "planning/",
        "MAX_BODY_BYTES": "http_api/",
        "MAX_AUDIO_BODY_BYTES": "http_api/",
        "MAX_BACKUP_BYTES": "backup/",
        "MAX_PRIVACY_EXPORT_BYTES": "privacy.py",
        "MIN_EXPORT_FREE_BYTES": "backup/",
        "EXPORT_TIME_LIMIT_SECONDS": "backup/",
        "STREAM_CHUNK_BYTES": "coach/streams.py",
        "MAX_EXTERNAL_CALENDAR_BYTES": "providers/calendar.py",
        "CALENDAR_FETCH_TIMEOUT_SECONDS": "providers/calendar.py",
        "CALENDAR_CONNECTION_TIMEOUT_SECONDS": "providers/calendar.py",
        "MAX_EXTERNAL_RESPONSE_BYTES": "providers/http.py",
        "MESSAGE_ATTACHMENTS_QUERY": "coach/conversation.py",
        "SESSIONS": "http_api/auth.py",
        "RATE_LIMITS": "http_api/auth.py",
        "COMPETITION_EXTERNAL_PREFIX": "planning/competitions.py",
        "CALENDAR_DISPLAY_DEFAULTS": "settings.py",
        "CALENDAR_DISPLAY_MAX_WEEKS": "settings.py",
        "URL_VALUE_RE": "observability.py",
        "DEFAULT_PROFILE": "athlete/",
        "NRW_LATITUDE_BOUNDS": "weather/",
        "NRW_LONGITUDE_BOUNDS": "weather/",
        "MORNING_RETRY_SECONDS": "coach/morning.py",
        "MORNING_MAX_ATTEMPTS": "coach/morning.py",
        "LIBRARY_BULK_MAX_ENTRIES": "planning/",
        "LIBRARY_BULK_PREVIEW_TTL_SECONDS": "coach/proposals.py",
        "LIBRARY_BULK_LOCAL_ACTIONS": "planning/",
        "DEFAULT_TIMEZONE": "config.py",
        "ATHLETE_RECORD_HANDLERS": "athlete/",
        "DB_LOCK": "db/manager.py",
        "DATABASE_MANAGER": "db/manager.py",
        "DATABASE_MANAGER_SIGNATURE": "db/manager.py",
        "SYNC_LOCK": "sync/",
        "WORKOUT_LIBRARY_SYNC_LOCK": "sync/",
        "COMPETITION_SYNC_LOCK": "sync/competitions.py",
        "PERFORMANCE_LOCK": "performance/",
        "OPENAI_CONVERSATION_LOCK": "coach/conversation.py",
        "CHAT_QUEUE": "coach/conversation.py",
        "CHAT_QUEUE_LIMIT": "coach/conversation.py",
        "CHAT_LOCK_TIMEOUT_SECONDS": "coach/conversation.py",
        "DIAGNOSTIC_CAPTURE_LOCK": "observability.py",
        "EXTERNAL_HTTP_STARTED_EVENT": "observability.py",
        "EXTERNAL_HTTP_COMPLETED_EVENT": "observability.py",
        "CHAT_STREAM_LOCK": "coach/streams.py",
        "CHAT_STREAMS": "coach/streams.py",
        "STREAM_CHUNK_BYTES": "coach/streams.py",
        "COACH_JOB_WORKER_LOCK": "coach/jobs.py",
        "COACH_JOB_WAKE": "coach/jobs.py",
        "COACH_JOB_STOP": "coach/jobs.py",
        "COACH_JOB_WORKER": "coach/jobs.py",
        "COACH_JOB_CANCEL_EVENTS": "coach/jobs.py",
        "MORNING_CHECKIN_LOCK": "coach/morning.py",
        "EXTERNAL_CALENDAR_LOCK": "calendar/",
        "SYNC_JOB_WORKER_LOCK": "sync/",
        "SYNC_JOB_WAKE": "sync/",
        "SYNC_JOB_STOP": "sync/",
        "SYNC_JOB_WORKER": "sync/",
        "SESSION_LOCK": "http_api/auth.py",
        "RATE_LIMIT_LOCK": "http_api/auth.py",
        "STATE_EVENT_CONDITION": "runtime/events.py",
        "STATE_EVENTS": "runtime/events.py",
        "STATE_EVENT_NEXT_ID": "runtime/events.py",
        "MAINTENANCE_GATE": "runtime/maintenance.py",
        "_configure_cipher": "db/manager.py",
        "RATE_LIMIT_CLEANUP_INTERVAL_SECONDS": "http_api/auth.py",
        "RATE_LIMIT_CLEANUP_BATCH_SIZE": "http_api/auth.py",
        "RATE_LIMIT_BUCKET_MAX_AGE_SECONDS": "http_api/auth.py",
        "RATE_LIMIT_LAST_CLEANUP_MONOTONIC": "http_api/auth.py",
    }
    if name in explicit:
        return explicit[name]
    if name.startswith(("SESSION_", "RATE_LIMIT_")):
        return "http_api/auth.py"
    if lowered.startswith(("_safe_url", "_unguessable_url", "_safe_calendar_url", "operation_", "observed_")):
        return "observability.py"
    if lowered.startswith(("_weather", "weather_", "fetch_weather", "_fetch_weather", "_record_weather", "_refresh_weather")) or lowered == "weather_state":
        return "weather/"
    if lowered.startswith(("daily_sync", "schedule_daily", "_schedule_daily", "_enqueue_startup", "_scheduler_")):
        return "sync/scheduler.py"
    if lowered.startswith(("_normalized_", "_pending_", "_existing_", "_historical_", "_execute_", "_queue_next_")):
        return "sync/"
    if lowered in {"_record_change", "list_change_history", "get_kv", "set_kv"}:
        return "history/" if "change" in lowered else "settings.py"
    if lowered == "_coach_error_metadata":
        return "observability.py"
    if lowered.startswith(("_cycling_", "parallel_cycling", "intervals_cycling", "is_outdoor", "is_cycling", "_activities_by_", "deduplicate_api", "list_recent_activities")):
        return "activities/"
    if lowered in {"get_activity_details", "duplicate_activity_delete_preview"} or lowered.startswith("_remove_intervals_activity"):
        return "activities/"
    if lowered in {"measurement_age", "bounded_score", "bounded_minutes"} or lowered.startswith(("wellness_", "_atl_", "_wellness_", "actual_atl", "eftp_", "comparison_value", "first_present", "readiness_", "as_number", "sport_setting", "sport_info", "intervals_eftp", "intervals_max_hr", "threshold_pace", "zone2_pace", "height_in_cm")):
        return "performance/"
    if lowered.startswith(("_normalize_fixture_sleep", "_fixture_sleep", "_shift_fixture_sleep", "garmin_")):
        return "sync/garmin.py"
    if lowered in {"add_message", "list_messages"}:
        return "coach/conversation.py"
    if lowered == "_invalidate_weather_cache_if_location_changed":
        return "weather/"
    if lowered in {"timezone_name"}:
        return "config.py"
    if lowered in {"list_public_event_candidates"}:
        return "calendar/"
    if lowered == "_save_athlete_profile":
        return "athlete/"
    if lowered.startswith(("_retry_after", "_provider_error", "_intervals_error", "_safe_interval_error", "_read_http", "_urlopen_", "_http_", "http_json", "_capture_http", "_handle_http", "multipart_form_data", "request_ai_provider", "responses_background_request", "output_text")):
        return "providers/http.py" if any(token in lowered for token in ("http", "urlopen", "multipart", "retry_after")) else "providers/"
    if lowered.startswith(("_adaptive_", "adaptive_", "_illness_", "illness_", "latest_illness", "_upsert_illness", "_fill_illness", "check_adaptive", "apply_adaptive", "_apply_adaptive", "_record_date", "_weekly_compliance", "compact_", "_is_composite_duration")):
        return "planning/"
    if lowered in {"selected", "coach_quick_actions_state"}:
        return "coach/context.py" if lowered != "selected" else "planning/"
    if lowered.startswith(("api_page", "encode_page", "decode_page", "paged_", "state_versions")):
        return "http_api/pagination.py"
    if lowered.startswith(("_canonical_", "_local_calendar", "local_calendar", "_repair_calendar", "_repaircalendar", "repaircalendar", "_require_intervals_calendar", "_intervals_calendar", "_intervals_connection", "intervals_public", "_adopt_remote", "_remote_calendar")):
        return "calendar/"
    if lowered.startswith(("delete_duplicate", "assert_duplicate")):
        return "activities/" if lowered.startswith("delete") else "coach/proposals.py"
    if lowered.startswith(("_structured_training", "_structured_adaptive", "_apply_structured_adaptive", "_validated_training", "_record_created_training", "_record_existing_training", "_validate_training_change", "_prepare_structured_training", "_validate_structured_training", "_collect_structured_training", "_apply_structured_training", "_replacement_", "_create_replacement", "_copy_replacement", "_archive_replacement", "_validate_replacement")):
        return "planning/"
    if lowered.startswith(("_structured_artifact", "_structured_action")):
        return "coach/tool_execution.py"
    if lowered.startswith(("_repair_manifest", "_validate_repair_manifest", "_refresh_repair_manifest", "_structured_bounded")):
        return "coach/proposals.py"
    if lowered.startswith(("_start_structured_provider", "_run_structured_intervals", "_retry_structured_intervals", "_resolve_structured_sync")):
        return "sync/"
    if lowered.startswith(("_record_intervals_sync", "_finish_intervals_sync", "_validate_selected_plan_sync", "_persist_selected_plan_sync")):
        return "sync/"
    if lowered.startswith(("_dialogue_", "_check_dialogue", "_validate_dialogue", "_alternative_planning_steps", "_profile_repair", "_profile_steps", "_apply_training_patch", "_store_training_patch")):
        return "coach/dialogue.py"
    if lowered.startswith(("_planning_command", "_prepare_planning_command", "_execute_planning_command", "execute_planning_command", "_claim_planning_command", "_prepare_commit_planning", "_validate_training_patch")):
        return "coach/tool_execution.py"
    if lowered == "_require_command_owner":
        return "coach/authorization.py"
    if lowered.startswith("_structured_command_failure") or lowered.startswith("_persist_structured_command_failure"):
        return "coach/service.py"
    if lowered in {"metric"} or lowered.startswith(("_provider_usage", "_response_retry")):
        return "providers/"
    if lowered == "_prepare_structured_plan_sync":
        return "sync/"
    if lowered in {"local_now"}:
        return "runtime/"
    if lowered.startswith("public_"):
        return "http_api/"
    if lowered.startswith(("_checkpoint_database", "client_ip", "allow_rate", "cookie_value", "readiness_state")):
        return "http_api/"
    if lowered.startswith("_startup_historical") or lowered == "main":
        return "sync/scheduler.py" if lowered != "main" else "server.py / Composition Root"
    if name.startswith(("ASSET_", "STATIC_")):
        return "http_api/"
    if name.endswith("_SQL") or name in {"DB_PATH", "DATA_DIR"}:
        return "db/"
    if name.endswith("_ERROR") or name.endswith("_ERRORS"):
        return "errors.py"
    if any(token in name for token in ("OPENAI", "GEMINI")):
        return "providers/"
    if "GARMIN" in name:
        return "sync/garmin.py"
    if "WEATHER" in name:
        return "weather/"
    if "SYNC" in name or "RESYNC" in name:
        return "sync/"
    if "COACH" in name or "CHAT" in name:
        return "coach/"
    if "PLAN" in name or "WORKOUT" in name:
        return "planning/"
    if name.startswith(("available_", "selected_", "save_")) and any(
        token in lowered for token in ("ai", "model", "thinking", "calendar")
    ):
        return "settings.py"
    if any(token in lowered for token in ("diagnostic", "redact", "sanitize", "secret", "logging", "log_", "safe_response_headers")):
        return "observability.py"
    if lowered.startswith(("provider_refresh", "sync_job", "_sync", "sync_", "enqueue_", "resume_interrupted", "start_sync", "resolve_sync", "garmin_snapshot")):
        return "sync/"
    if lowered.startswith(("_history", "history_", "undo", "_undo", "list_change", "_change", "_audit", "audit_")):
        return "history/"
    if lowered.startswith(("activity_", "_activity")):
        return "activities/"
    preferences = (
        (("load_local_env", "config"), "config.py"),
        (("setting", "model", "provider", "thinking"), "settings.py"),
        (("log", "redact", "sanitize", "secret", "external_call"), "observability.py"),
        (("maintenance", "event", "generation"), "runtime/"),
        (("db", "sql", "repository", "schema", "database"), "db/"),
        (("history", "undo"), "history/"),
        (("garmin",), "sync/garmin.py"),
        (("activity",), "activities/"),
        (("performance", "recovery", "vo2", "battery", "fitness"), "performance/"),
        (("profile", "checkin", "feedback", "athlete"), "athlete/"),
        (("competition", "race"), "planning/competitions.py"),
        (("ical", "calendar", "byday", "recurrence"), "providers/calendar.py"),
        (("weather",), "weather/"),
        (("workout", "library", "planned", "training_plan", "plan_", "planning"), "planning/"),
        (("openai", "gemini", "transcri", "responses_request", "audio"), "providers/"),
        (("context", "prompt", "coach", "conversation", "chat"), "coach/"),
        (("proposal", "authoriz", "scope", "tool"), "coach/"),
        (("stream",), "coach/streams.py"),
        (("job", "queue", "worker"), "coach/jobs.py"),
        (("morning",), "coach/morning.py"),
        (("backup", "restore", "export"), "backup/"),
        (("privacy", "delete"), "privacy.py"),
        (("http", "request", "response", "handler", "session", "csrf", "auth", "pagination"), "http_api/"),
        (("scheduler", "daily"), "sync/scheduler.py"),
        (("sync", "resync", "refresh", "cursor", "snapshot", "reconcile"), "sync/"),
    )
    for words, preferred in preferences:
        if not any(word in lowered for word in words):
            continue
        exact = next((candidate for candidate in candidates if candidate == preferred), None)
        if exact:
            return exact
        compatible = next(
            (candidate for candidate in candidates if preferred.rstrip("/").split("/")[0] in candidate),
            None,
        )
        if compatible:
            return compatible
    if len(candidates) == 1:
        return candidates[0]
    return "unklar: " + ", ".join(candidates)


def phase_for_target(target: str) -> str:
    lowered = target.lower()
    if target.startswith("unklar"):
        return "P0 (Zuordnung offen)"
    if "config" in lowered or "errors" in lowered or "observability" in lowered or "runtime" in lowered or "settings" in lowered or "db" in lowered:
        return "P1"
    if "providers" in lowered:
        return "P2"
    if any(value in lowered for value in ("activities", "performance", "athlete", "calendar", "weather")):
        return "P3"
    if "planning" in lowered:
        return "P4"
    if "history" in lowered:
        return "P5"
    if "scheduler" in lowered:
        return "P8"
    if "sync" in lowered:
        return "P6"
    if "coach" in lowered:
        if any(value in lowered for value in ("jobs", "streams", "morning")):
            return "P8"
        return "P7"
    if "backup" in lowered or "privacy" in lowered:
        return "P9"
    if "http_api" in lowered:
        return "P10"
    return "P11"


def make_items(tree: ast.Module, ranges: tuple[PlanRange, ...]) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    direct_nodes = {id(node) for node in tree.body}
    seen_global_names: set[str] = set()
    for node in sorted(_module_scope_nodes(tree.body), key=lambda item: (item.lineno, item.col_offset)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Keep the historical import count stable. Control-flow imports
            # still bind a module-global name and are represented once below.
            if id(node) not in direct_nodes:
                for name, imported_module in _import_bindings(node):
                    if name in seen_global_names:
                        continue
                    seen_global_names.add(name)
                    plan_range = range_for(node.lineno, ranges)
                    candidates = plan_range.targets if plan_range else ()
                    target = _candidate_for_name(name, candidates)
                    items.append(
                        InventoryItem(
                            "Globale Bindung", name, node.lineno, getattr(node, "end_lineno", node.lineno),
                            imported_module, target, phase_for_target(target), "offen", node, imported_module,
                        )
                    )
                continue
            for name, imported_module in _import_bindings(node):
                seen_global_names.add(name)
                target = imported_module.split(":", 1)[0]
                if target.startswith("backend"):
                    target = target.replace(".", "/")
                    status = "bereits ausgelagert (Importbindung)"
                else:
                    target = "server.py / Composition Root"
                    status = "bestehende Infrastrukturbindung"
                items.append(
                    InventoryItem(
                        "Importbindung", name, node.lineno, getattr(node, "end_lineno", node.lineno),
                        imported_module, target, "P1" if target.startswith("backend") else "P11", status,
                        node, imported_module,
                    )
                )
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "Klasse" if isinstance(node, ast.ClassDef) else "Funktion"
            plan_range = range_for(node.lineno, ranges)
            candidates = plan_range.targets if plan_range else ()
            target = _candidate_for_name(node.name, candidates)
            items.append(
                InventoryItem(
                    kind, node.name, node.lineno, getattr(node, "end_lineno", node.lineno),
                    "server.py", target, phase_for_target(target), "offen", node,
                )
            )
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target_node in targets:
                for name in _bound_names(target_node):
                    if name in seen_global_names:
                        continue
                    seen_global_names.add(name)
                    plan_range = range_for(node.lineno, ranges)
                    candidates = plan_range.targets if plan_range else ()
                    target = _candidate_for_name(name, candidates)
                    status = "offen"
                    if name in {"ROOT", "PUBLIC_DIR", "APP_VERSION"}:
                        target = "server.py / Composition Root"
                        status = "verbleibt bis P11 (prüfen)"
                    items.append(
                        InventoryItem(
                            "Globale Bindung", name, node.lineno, getattr(node, "end_lineno", node.lineno),
                            "server.py", target, phase_for_target(target), status, node,
                        )
                    )
    return items


def reference_files() -> tuple[Path, ...]:
    result: list[Path] = []
    roots = {
        ROOT / "backend": "backend",
        ROOT / "tests": "tests",
        ROOT / "e2e": "e2e",
        ROOT / "scripts": "scripts",
        ROOT / ".github": "workflows",
    }
    for directory, _ in roots.items():
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or any(part in {"__pycache__", ".git", "data"} for part in path.parts):
                continue
            if path.resolve() == (ROOT / "scripts" / "server_extraction_inventory.py").resolve():
                continue
            if path.name.startswith(".env") or path.suffix.lower() in {".db", ".log"}:
                continue
            result.append(path)
    for path in (ROOT / "Dockerfile", ROOT / "docker-compose.yml"):
        if path.exists():
            result.append(path)
    return tuple(sorted(set(result)))


def _category(path: Path) -> str:
    relative = path.relative_to(ROOT)
    if relative.parts[0] == ".github":
        return "Workflows/CI"
    return relative.parts[0] if relative.parts else "Repository"


def _location(path: Path, line: int) -> str:
    parts = path.relative_to(ROOT).parts
    display = "/".join(parts[2:]) if parts[:2] == (".github", "workflows") else "/".join(parts[1:])
    if not display:
        display = parts[0]
    return f"{_category(path)}/{display}:{line}"


def collect_references(items: list[InventoryItem]) -> tuple[dict[str, list[str]], list[str]]:
    names = {item.name for item in items}
    references: dict[str, list[str]] = defaultdict(list)
    dynamic: list[str] = []
    aliases = {"server"}
    server_alias_pattern = re.compile(r"^\s*import\s+server\s+as\s+(\w+)")
    member_pattern = re.compile(r"\b(server|[A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)\b")
    literal_pattern = re.compile(r"[\"']([A-Za-z_]\w*)[\"']")
    for path in reference_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            alias_match = server_alias_pattern.match(line)
            if alias_match:
                aliases.add(alias_match.group(1))
            if "server" not in line and not any(alias in line for alias in aliases):
                continue
            for receiver, name in member_pattern.findall(line):
                if receiver in aliases and name in names:
                    location = _location(path, number)
                    references[name].append(f"{location} (direkt/dynamisch unklar)")
            if any(token in line for token in ("getattr", "sys.modules", "monkeypatch", "patch.object", "patch(")):
                dynamic.append(f"{_location(path, number)}: {line.strip()}")
                for name in literal_pattern.findall(line):
                    if name in names:
                        location = _location(path, number)
                        references[name].append(f"{location} (Monkeypatch/getattr/sys.modules)")
            if re.search(r"\bfrom\s+server\s+import\b", line):
                for name in re.findall(r"\b[A-Za-z_]\w*\b", line.split("import", 1)[1]):
                    if name in names:
                        references[name].append(f"{_location(path, number)} (Import)")
    return {name: sorted(set(values)) for name, values in references.items()}, sorted(set(dynamic))


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


def dependencies(items: list[InventoryItem], tree: ast.Module) -> dict[str, tuple[set[str], set[str], set[str], set[str]]]:
    definitions = {item.name for item in items if item.kind in {"Funktion", "Klasse"}}
    globals_ = {item.name for item in items}
    result: dict[str, tuple[set[str], set[str], set[str], set[str]]] = {}
    for item in items:
        if item.kind not in {"Funktion", "Klasse"} or item.node is None:
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


def strongly_connected_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(name: str) -> None:
        nonlocal index
        indices[name] = lowlinks[name] = index
        index += 1
        stack.append(name)
        on_stack.add(name)
        for successor in sorted(graph.get(name, ())):
            if successor not in indices:
                visit(successor)
                lowlinks[name] = min(lowlinks[name], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[name] = min(lowlinks[name], indices[successor])
        if lowlinks[name] == indices[name]:
            component: list[str] = []
            while True:
                successor = stack.pop()
                on_stack.remove(successor)
                component.append(successor)
                if successor == name:
                    break
            if len(component) > 1 or name in graph.get(name, set()):
                components.append(tuple(sorted(component)))

    for name in sorted(graph):
        if name not in indices:
            visit(name)
    return sorted(components)


def _format_names(values: set[str] | list[str], limit: int = 12) -> str:
    ordered = sorted(values)
    if not ordered:
        return "–"
    if len(ordered) > limit:
        return ", ".join(f"`{value}`" for value in ordered[:limit]) + f", … (+{len(ordered) - limit})"
    return ", ".join(f"`{value}`" for value in ordered)


def build_document() -> str:
    source = SERVER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVER_PATH))
    ranges = read_plan_ranges()
    items = make_items(tree, ranges)
    references, dynamic = collect_references(items)
    deps = dependencies(items, tree)
    definition_names = {item.name for item in items if item.kind in {"Funktion", "Klasse"}}
    graph = {name: set(deps.get(name, (set(), set(), set(), set()))[0]) & definition_names for name in definition_names}
    cycles = strongly_connected_components(graph)
    counts = Counter((item.kind, item.phase) for item in items)
    target_counts = Counter(item.target for item in items)
    source_lines = len(source.splitlines())
    plan_end = max(item.end for item in ranges)
    outside_plan = [item for item in items if item.line > plan_end]
    source_fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()

    lines = [
        "# Statisches Inventar für die server.py-Auslagerung",
        "",
        "> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.",
        "",
        "## Ausgangsstand",
        "",
        f"- Geprüfter P0-Basiscommit: `{P0_BASE_COMMIT}`",
        f"- Inventarisierter `server.py`-Quelltext (SHA-256): `{source_fingerprint}`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.",
        f"- `server.py`: {source_lines:,} physische Zeilen".replace(",", "."),
        f"- Inventareinträge: {len(items):,}".replace(",", "."),
        f"- Definitionen (Funktionen/Klassen): {len(definition_names):,}".replace(",", "."),
        f"- Globale Bindungen einschließlich Imports: {sum(item.kind == 'Globale Bindung' for item in items):,} Zuweisungen, {sum(item.kind == 'Importbindung' for item in items):,} Imports".replace(",", "."),
        f"- Planbereich: bis Zeile {plan_end:,}; Einträge dahinter: {len(outside_plan):,} (zielbestimmt über Symbol-/Verantwortungsanalyse)".replace(",", "."),
        "- Status dieses Stands: P0/Intervals-Reabsorption integriert; P1 hat noch nicht begonnen. `offen` bedeutet, dass die fachliche Eigentümerschaft noch migriert werden muss.",
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
    for phase_number in range(0, 12):
        phase = f"P{phase_number}" if phase_number else "P0 (Zuordnung offen)"
        definitions = counts[("Funktion", phase)] + counts[("Klasse", phase)]
        bindings = counts[("Globale Bindung", phase)]
        imports = counts[("Importbindung", phase)]
        lines.append(f"| {phase} | {definitions} | {bindings} | {imports} |")
    lines += ["", "## Referenzanalyse außerhalb von server.py", "", "Direkte `server.<name>`-Zugriffe und erkennbare Import-/Patchstellen sind pro Eintrag in der Tabelle vermerkt. Die Ortsangaben decken `backend/`, `tests/`, `e2e/`, `scripts/`, Docker und GitHub-Workflows ab.", ""]
    if dynamic:
        lines += ["### Dynamische Zugriffe und Monkeypatches", "", "Diese Stellen benötigen bei jeder Migration eine manuelle Prüfung des Lookup-Ortes:", ""]
        lines.extend(f"- `{entry}`" for entry in dynamic)
        lines.append("")
    else:
        lines += ["Keine dynamischen Zugriffe, Monkeypatches oder `sys.modules`-Stellen außerhalb von `server.py` gefunden.", ""]
    lines += ["## P1-Aufruf- und Zustandsabhängigkeiten", "", "Die folgende Tabelle ist die statische Grundlage für P1. Reads/Writes sind nur Namen, die im globalen Modulnamespace gebunden werden; lokale Variablen werden soweit AST-statisch erkennbar ausgefiltert. Dynamische Attribute, Closure-Zustand und indirekte Callbacks bleiben unsicher.", "", "| Definition | Zeile | Direkte lokale Aufrufe | Globale Reads | Globale Writes | Imports im Body |", "| --- | ---: | --- | --- | --- | --- |"]
    p1_items = [item for item in items if item.kind in {"Funktion", "Klasse"} and item.line <= 2999]
    for item in p1_items:
        calls, reads, writes, imports = deps.get(item.name, (set(), set(), set(), set()))
        lines.append(f"| `{item.name}` | {item.line} | {_format_names(calls)} | {_format_names(reads)} | {_format_names(writes)} | {_format_names(imports)} |")
    lines += ["", "### Zyklische Gruppen", ""]
    if cycles:
        lines.append(f"Statisch erkannte SCCs im direkten lokalen Aufrufgraphen: {len(cycles)}. Jede Gruppe ist als gemeinsame Umzugseinheit zu prüfen.")
        lines.append("")
        for component in cycles:
            lines.append(f"- {', '.join(f'`{name}`' for name in component)}")
    else:
        lines.append("Keine zyklische Gruppe im direkten lokalen Aufrufgraphen erkannt; dynamische Rückrufe sind damit nicht ausgeschlossen.")
    lines += ["", "## Vollständiges Inventar", "", "`Zielmodul` und `Phase` folgen der Bereichstabelle des vollständigen Plans. Jede Zuordnung ist konkret; eine künftig neu hinzukommende nicht auflösbare Bindung wird als offen markiert und darf nicht stillschweigend erfunden werden. `Status` beschreibt ausschließlich den Stand vor P1.", "", "| Art | Quellname | Ausgangszeile | Zielmodul | Phase | Status | Referenzen außerhalb von server.py |", "| --- | --- | ---: | --- | --- | --- | --- |"]
    for item in items:
        refs = "; ".join(references.get(item.name, [])) or "keine statisch gefunden"
        lines.append(f"| {item.kind} | `{item.name}` | {item.line} | `{item.target}` | {item.phase} | {item.status} | {refs} |")
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
        if not DOC_PATH.exists() or DOC_PATH.read_text(encoding="utf-8") != document:
            print(f"{DOC_PATH} is stale; run python scripts/server_extraction_inventory.py", file=sys.stderr)
            return 1
        return 0
    DOC_PATH.write_text(document, encoding="utf-8")
    print(f"wrote {DOC_PATH} ({len(document.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
