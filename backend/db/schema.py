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
    "nutrition_logs": {"id", "meal_date", "logged_at", "meal_type", "description", "kcal", "carbs_g", "protein_g", "fat_g", "source", "sync_state", "created_at", "updated_at"},
    "nutrition_sync_dates": {"meal_date", "revision", "sync_state", "updated_at"},
    "sessions": {"token_hash", "csrf_hash", "expires_at", "created_at", "last_seen"},
}

CURRENT_DATABASE_INDEXES = {
    "idx_change_history_created_at", "idx_change_history_entity", "idx_coach_plan_artifacts_conversation",
    "idx_nutrition_logs_date",
    "idx_planned_units_date", "idx_planned_units_external_id", "idx_planned_units_local_id",
    "idx_provider_refresh_area", "idx_provider_refresh_created_at", "idx_sync_job_items_status",
    "idx_sync_jobs_status_available", "idx_workout_library_external_id",
}
def initialize_schema(db: Any) -> None:
    """Create the exact current schema on a new database connection."""
    db.executescript(
        """
    PRAGMA journal_mode=WAL;
    CREATE TABLE kv (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE messages (
        attachments TEXT NOT NULL DEFAULT '[]',
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
        content TEXT NOT NULL,
        client_turn_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
     CREATE TABLE workout_library (
         id TEXT PRIMARY KEY,
         local_id TEXT NOT NULL UNIQUE,
         external_id TEXT,
        payload TEXT NOT NULL,
        sync_dirty INTEGER NOT NULL DEFAULT 1,
        sync_state TEXT NOT NULL DEFAULT 'local',
        sync_error TEXT,
        last_synced_at TEXT,
         updated_at TEXT NOT NULL
     );
     CREATE TABLE planned_units (
         id TEXT PRIMARY KEY,
         local_id TEXT NOT NULL UNIQUE,
         external_id TEXT,
         payload TEXT NOT NULL,
         sync_dirty INTEGER NOT NULL DEFAULT 1,
         sync_state TEXT NOT NULL DEFAULT 'local',
         sync_error TEXT,
         sync_conflict TEXT NOT NULL DEFAULT '',
         baseline_hash TEXT,
         last_synced_at TEXT,
         plan_id TEXT,
         revision INTEGER NOT NULL DEFAULT 0,
         tombstone INTEGER NOT NULL DEFAULT 0,
         command_id TEXT,
         created_at TEXT NOT NULL,
         updated_at TEXT NOT NULL
     );
    CREATE TABLE planning_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        revision INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE coach_plan_artifacts (
        id TEXT PRIMARY KEY,
        conversation_id TEXT,
        client_turn_id TEXT,
        base_revision INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft', 'committed', 'superseded')),
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_coach_plan_artifacts_conversation
        ON coach_plan_artifacts(conversation_id, created_at DESC);
    CREATE TABLE coach_commands (
        id TEXT PRIMARY KEY,
        client_turn_id TEXT NOT NULL UNIQUE,
        conversation_id TEXT,
        intent TEXT NOT NULL,
        target_system TEXT NOT NULL,
        artifact_id TEXT,
        status TEXT NOT NULL,
        receipt TEXT,
        error_class TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (artifact_id) REFERENCES coach_plan_artifacts(id)
    );
    CREATE TABLE sync_jobs (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        type TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'partial', 'failed')),
        payload TEXT NOT NULL,
        requested_by TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        progress_total INTEGER NOT NULL DEFAULT 0,
        progress_completed INTEGER NOT NULL DEFAULT 0,
        error_class TEXT,
        available_at TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_sync_jobs_status_available
        ON sync_jobs(status, available_at, created_at);
    CREATE TABLE sync_job_items (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        item_key TEXT NOT NULL,
        operation TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        remote_id TEXT,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        error_class TEXT,
        error_detail TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(job_id, item_key),
        FOREIGN KEY (job_id) REFERENCES sync_jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_sync_job_items_status ON sync_job_items(job_id, status);
    CREATE TABLE provider_sync_cursors (
        provider TEXT NOT NULL,
        stream TEXT NOT NULL,
        cursor TEXT,
        high_water_mark TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, stream)
    );
    CREATE TABLE competitions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        event_date TEXT NOT NULL,
        sport TEXT NOT NULL,
        priority TEXT NOT NULL,
        distance TEXT NOT NULL,
        target TEXT NOT NULL,
        course_profile TEXT NOT NULL,
        notes TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'RACE_B',
        start_date_local TEXT,
        description TEXT NOT NULL DEFAULT '',
        moving_time INTEGER,
        intervals_event_id TEXT,
        external_id TEXT,
        sync_dirty INTEGER NOT NULL DEFAULT 1,
        sync_state TEXT NOT NULL DEFAULT 'local',
        sync_conflict TEXT NOT NULL DEFAULT '',
        last_synced_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE competition_sync_tombstones (
        id TEXT PRIMARY KEY,
        intervals_event_id TEXT,
        external_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE training_plans (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        goal TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE athlete_checkins (
        checkin_date TEXT PRIMARY KEY,
        soreness INTEGER,
        stress INTEGER,
        motivation INTEGER,
        session_rpe INTEGER,
        day_form TEXT NOT NULL DEFAULT '',
        illness TEXT NOT NULL DEFAULT '',
        pain TEXT NOT NULL DEFAULT '',
        available_minutes INTEGER,
        availability_notes TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE activity_feedback (
        activity_id TEXT PRIMARY KEY,
        activity_name TEXT NOT NULL DEFAULT '',
        activity_date TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE plan_adjustments (
        id TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        applied_at TEXT
    );
    CREATE TABLE coach_action_proposals (
        id TEXT PRIMARY KEY,
        session_csrf_hash TEXT NOT NULL,
        action_type TEXT NOT NULL,
        target_system TEXT NOT NULL,
        object_ids TEXT NOT NULL,
        diff TEXT NOT NULL,
        payload TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        action_token_hash TEXT,
        status TEXT NOT NULL,
        expires_at REAL NOT NULL,
        created_at TEXT NOT NULL,
        used_at TEXT
    );
    CREATE TABLE change_history (
        id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        before_hash TEXT NOT NULL,
        after_hash TEXT NOT NULL,
        diff TEXT NOT NULL
    );
    CREATE INDEX idx_change_history_created_at ON change_history(created_at DESC);
    CREATE INDEX idx_change_history_entity ON change_history(entity_type, entity_id, created_at DESC);
    CREATE TABLE provider_refresh_history (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        area TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        trigger TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        phase TEXT NOT NULL,
        status TEXT NOT NULL,
        error_code TEXT,
        next_retry_at TEXT
    );
    CREATE INDEX idx_provider_refresh_created_at ON provider_refresh_history(started_at DESC);
    CREATE INDEX idx_provider_refresh_area ON provider_refresh_history(provider, area, started_at DESC);
    CREATE TABLE public_event_sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        last_sync_at TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE public_event_candidates (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        uid TEXT NOT NULL,
        name TEXT NOT NULL,
        event_date TEXT NOT NULL,
        sport TEXT NOT NULL,
        distance TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        imported_competition_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(source_id, uid),
        FOREIGN KEY(source_id) REFERENCES public_event_sources(id) ON DELETE CASCADE
    );
    CREATE TABLE external_calendar_events (
        id TEXT PRIMARY KEY,
        uid TEXT NOT NULL,
        name TEXT NOT NULL,
        event_date TEXT NOT NULL,
        start_local TEXT NOT NULL,
        end_local TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL,
        all_day INTEGER NOT NULL DEFAULT 0,
        training_relevant INTEGER NOT NULL DEFAULT 1,
        no_intensity INTEGER NOT NULL DEFAULT 0,
        short_only INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(uid, start_local)
    );
    CREATE TABLE nutrition_logs (
        id TEXT PRIMARY KEY,
        meal_date TEXT NOT NULL,
        logged_at TEXT NOT NULL,
        meal_type TEXT NOT NULL CHECK(meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
        description TEXT NOT NULL,
        kcal INTEGER NOT NULL CHECK(kcal >= 0),
        carbs_g REAL,
        protein_g REAL,
        fat_g REAL,
        source TEXT NOT NULL DEFAULT 'manual',
        sync_state TEXT NOT NULL DEFAULT 'local',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_nutrition_logs_date ON nutrition_logs(meal_date, logged_at DESC);
    CREATE TABLE nutrition_sync_dates (
        meal_date TEXT PRIMARY KEY,
        revision INTEGER NOT NULL DEFAULT 1,
        sync_state TEXT NOT NULL DEFAULT 'pending' CHECK(sync_state IN ('pending', 'synced')),
        updated_at TEXT NOT NULL
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        csrf_hash TEXT NOT NULL,
        expires_at REAL NOT NULL,
        created_at TEXT NOT NULL,
        last_seen TEXT NOT NULL
    );
        """
    )
    db.execute("CREATE UNIQUE INDEX idx_workout_library_external_id ON workout_library(external_id) WHERE external_id IS NOT NULL")
    db.execute("CREATE UNIQUE INDEX idx_planned_units_local_id ON planned_units(local_id)")
    db.execute("CREATE INDEX idx_planned_units_external_id ON planned_units(external_id)")
    db.execute("CREATE INDEX idx_planned_units_date ON planned_units(json_extract(payload, '$.date'))")
    


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
