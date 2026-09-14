"""Current SQLCipher schema contract and connection configuration."""

from __future__ import annotations

from typing import Any


CURRENT_DATABASE_SCHEMA: dict[str, set[str]] = {
    "kv": {"key", "value", "updated_at"},
    "messages": {"id", "role", "content", "client_turn_id", "created_at", "attachments"},
    "snapshots": {"id", "payload", "created_at"},
    "workout_library": {"id", "local_id", "external_id", "payload", "sync_dirty", "sync_state", "sync_error", "last_synced_at", "updated_at"},
    "planned_units": {"id", "local_id", "external_id", "payload", "sync_dirty", "sync_state", "sync_error", "sync_conflict", "baseline_hash", "last_synced_at", "plan_id", "revision", "tombstone", "command_id", "created_at", "updated_at"},
    "planning_state": {"id", "revision", "updated_at"},
    "coach_plan_artifacts": {"id", "conversation_id", "client_turn_id", "base_revision", "status", "payload", "created_at", "updated_at"},
    "coach_commands": {"id", "client_turn_id", "conversation_id", "intent", "target_system", "artifact_id", "status", "error_class", "receipt", "created_at", "updated_at"},
    "sync_jobs": {"id", "provider", "type", "status", "payload", "requested_by", "attempts", "progress_total", "progress_completed", "error_class", "available_at", "started_at", "finished_at", "created_at", "updated_at"},
    "sync_job_items": {"id", "job_id", "item_key", "operation", "payload_hash", "remote_id", "status", "attempts", "error_class", "error_detail", "created_at", "updated_at"},
    "provider_sync_cursors": {"provider", "stream", "cursor", "high_water_mark", "updated_at"},
    "competitions": {"id", "name", "event_date", "sport", "priority", "distance", "target", "course_profile", "notes", "category", "start_date_local", "description", "moving_time", "intervals_event_id", "external_id", "sync_dirty", "sync_state", "sync_conflict", "last_synced_at", "created_at", "updated_at"},
    "competition_sync_tombstones": {"id", "intervals_event_id", "external_id", "created_at"},
    "training_plans": {"id", "name", "goal", "start_date", "end_date", "status", "created_at", "updated_at"},
    "athlete_checkins": {"checkin_date", "soreness", "stress", "motivation", "session_rpe", "day_form", "illness", "pain", "available_minutes", "availability_notes", "notes", "created_at", "updated_at"},
    "activity_feedback": {"activity_id", "activity_name", "activity_date", "notes", "created_at", "updated_at"},
    "plan_adjustments": {"id", "payload", "status", "created_at", "applied_at"},
    "coach_action_proposals": {"id", "session_csrf_hash", "action_type", "target_system", "object_ids", "diff", "payload", "payload_hash", "action_token_hash", "status", "expires_at", "created_at", "used_at"},
    "change_history": {"id", "entity_type", "entity_id", "action", "source", "created_at", "before_hash", "after_hash", "diff"},
    "provider_refresh_history": {"id", "provider", "area", "operation_id", "trigger", "started_at", "finished_at", "phase", "status", "error_code", "next_retry_at"},
    "public_event_sources": {"id", "name", "url", "last_sync_at", "last_error", "created_at", "updated_at"},
    "public_event_candidates": {"id", "source_id", "uid", "name", "event_date", "sport", "distance", "location", "url", "description", "imported_competition_id", "created_at", "updated_at"},
    "external_calendar_events": {"id", "uid", "name", "event_date", "start_local", "end_local", "duration_minutes", "all_day", "training_relevant", "no_intensity", "short_only", "updated_at"},
    "sessions": {"token_hash", "csrf_hash", "expires_at", "created_at", "last_seen"},
}

CURRENT_DATABASE_INDEXES = {
    "idx_change_history_created_at", "idx_change_history_entity", "idx_coach_plan_artifacts_conversation",
    "idx_planned_units_date", "idx_planned_units_external_id", "idx_planned_units_local_id",
    "idx_provider_refresh_area", "idx_provider_refresh_created_at", "idx_sync_job_items_status",
    "idx_sync_jobs_status_available", "idx_workout_library_external_id",
}


def configure_cipher(db: Any, password: str) -> None:
    db.execute(f"PRAGMA key='{password.replace(chr(39), chr(39) * 2)}'")
    db.execute("PRAGMA cipher_compatibility = 4")
    db.execute("PRAGMA cipher_memory_security = ON")


def database_table_names(db: Any) -> set[str]:
    return {str(row["name"]) for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not str(row["name"]).startswith("sqlite_")}


def database_index_names(db: Any) -> set[str]:
    return {str(row["name"]) for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            if not str(row["name"]).startswith("sqlite_")}


def database_schema_is_current(db: Any) -> bool:
    if database_table_names(db) != set(CURRENT_DATABASE_SCHEMA) or database_index_names(db) != CURRENT_DATABASE_INDEXES:
        return False
    return all(columns == {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
               for table, columns in CURRENT_DATABASE_SCHEMA.items())
