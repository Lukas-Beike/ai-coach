"""Current SQLCipher schema contract and connection configuration."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from enum import StrEnum
from functools import lru_cache
from typing import Any

from backend.canonical.vocabulary import (
    ZONE_DETAIL_KINDS,
    ActivityDetailKind,
    ActivityDetailOrigin,
    ActivityLinkKind,
    ActivityRecordState,
    ActivitySessionState,
    ProjectionState,
    ProviderRecordState,
)

CURRENT_DATABASE_SCHEMA: dict[str, set[str]] = {
    "kv": {"key", "value", "updated_at"},
    "messages": {
        "id",
        "role",
        "content",
        "client_turn_id",
        "created_at",
        "attachments",
    },
    "snapshots": {"id", "payload", "created_at", "synced_at", "recent_activity_count"},
    "workout_library": {
        "id",
        "local_id",
        "external_id",
        "payload",
        "sync_dirty",
        "sync_state",
        "sync_error",
        "last_synced_at",
        "updated_at",
    },
    "planned_units": {
        "id",
        "local_id",
        "external_id",
        "payload",
        "sync_dirty",
        "sync_state",
        "sync_error",
        "sync_conflict",
        "baseline_hash",
        "last_synced_at",
        "plan_id",
        "revision",
        "tombstone",
        "command_id",
        "created_at",
        "updated_at",
    },
    "planning_state": {"id", "revision", "updated_at"},
    "coach_plan_artifacts": {
        "id",
        "conversation_id",
        "client_turn_id",
        "base_revision",
        "status",
        "payload",
        "created_at",
        "updated_at",
    },
    "coach_commands": {
        "id",
        "client_turn_id",
        "conversation_id",
        "intent",
        "target_system",
        "artifact_id",
        "status",
        "error_class",
        "receipt",
        "created_at",
        "updated_at",
    },
    "sync_jobs": {
        "id",
        "provider",
        "type",
        "status",
        "payload",
        "requested_by",
        "attempts",
        "progress_total",
        "progress_completed",
        "error_class",
        "available_at",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    },
    "sync_job_items": {
        "id",
        "job_id",
        "item_key",
        "operation",
        "payload_hash",
        "remote_id",
        "status",
        "attempts",
        "error_class",
        "error_detail",
        "created_at",
        "updated_at",
    },
    "provider_sync_cursors": {
        "provider",
        "stream",
        "cursor",
        "high_water_mark",
        "updated_at",
    },
    "competitions": {
        "id",
        "name",
        "event_date",
        "sport",
        "environment",
        "sport_detail",
        "priority",
        "distance",
        "target",
        "course_profile",
        "notes",
        "category",
        "start_date_local",
        "description",
        "moving_time",
        "intervals_event_id",
        "external_id",
        "sync_dirty",
        "sync_state",
        "sync_conflict",
        "last_synced_at",
        "created_at",
        "updated_at",
    },
    "competition_sync_tombstones": {
        "id",
        "intervals_event_id",
        "external_id",
        "created_at",
        "provider",
    },
    "remote_links": {
        "entity_kind",
        "local_id",
        "provider",
        "remote_id",
        "remote_external_id",
        "baseline_hash",
        "sync_state",
        "last_synced_at",
    },
    "training_plans": {
        "id",
        "name",
        "goal",
        "start_date",
        "end_date",
        "status",
        "created_at",
        "updated_at",
    },
    "athlete_checkins": {
        "checkin_date",
        "soreness",
        "stress",
        "motivation",
        "session_rpe",
        "day_form",
        "illness",
        "pain",
        "available_minutes",
        "availability_notes",
        "notes",
        "created_at",
        "updated_at",
    },
    "activity_feedback": {
        "activity_id",
        "activity_name",
        "activity_date",
        "notes",
        "session_rpe",
        "deviation_reason",
        "created_at",
        "updated_at",
        "provider",
        "session_id",
    },
    "plan_adjustments": {"id", "payload", "status", "created_at", "applied_at"},
    "coach_action_proposals": {
        "id",
        "session_csrf_hash",
        "action_type",
        "target_system",
        "object_ids",
        "diff",
        "payload",
        "payload_hash",
        "action_token_hash",
        "status",
        "expires_at",
        "created_at",
        "used_at",
    },
    "change_history": {
        "id",
        "entity_type",
        "entity_id",
        "action",
        "source",
        "created_at",
        "before_hash",
        "after_hash",
        "diff",
    },
    "provider_refresh_history": {
        "id",
        "provider",
        "area",
        "operation_id",
        "trigger",
        "started_at",
        "finished_at",
        "phase",
        "status",
        "error_code",
        "next_retry_at",
    },
    "public_event_sources": {
        "id",
        "name",
        "url",
        "last_sync_at",
        "last_error",
        "created_at",
        "updated_at",
    },
    "public_event_candidates": {
        "id",
        "source_id",
        "uid",
        "name",
        "event_date",
        "sport",
        "distance",
        "location",
        "url",
        "description",
        "imported_competition_id",
        "created_at",
        "updated_at",
    },
    "external_calendar_events": {
        "id",
        "uid",
        "name",
        "event_date",
        "start_local",
        "end_local",
        "duration_minutes",
        "all_day",
        "training_relevant",
        "no_training",
        "no_intensity",
        "short_only",
        "updated_at",
    },
    "nutrition_logs": {
        "nutrition_basis",
        "id",
        "meal_date",
        "logged_at",
        "meal_type",
        "description",
        "kcal",
        "carbs_g",
        "protein_g",
        "fat_g",
        "source",
        "sync_state",
        "created_at",
        "updated_at",
        "logged_time_known",
    },
    "nutrition_sync_dates": {"meal_date", "revision", "sync_state", "updated_at"},
    "nutrition_templates": {"id", "name", "payload", "updated_at"},
    "nutrition_products": {
        "id",
        "barcode",
        "name",
        "brand",
        "basis_amount",
        "basis_unit",
        "kcal",
        "carbs_g",
        "protein_g",
        "fat_g",
        "sugar_g",
        "fiber_g",
        "salt_g",
        "source",
        "source_url",
        "external_id",
        "status",
        "provenance",
        "extraction_confidence",
        "created_at",
        "updated_at",
    },
    "provider_records": {
        "id",
        "provider",
        "record_kind",
        "source_record_id",
        "payload",
        "payload_hash",
        "fetched_at",
        "mapped_version",
        "state",
        "created_at",
        "updated_at",
        "observed_on",
    },
    "activity_sessions": {
        "activity_id",
        "primary_provider",
        "primary_provider_activity_id",
        "link_kind",
        "athlete_confirmed",
        "state",
        "merged_into",
        "started_at",
        "local_date",
        "created_at",
        "updated_at",
        "merged_into_retained",
    },
    "activity_records": {
        "provider",
        "provider_activity_id",
        "activity_id",
        "state",
        "mapper_version",
        "source_kind",
        "recorded_by",
        "source_record_id",
        "sport",
        "environment",
        "started_at",
        "local_date",
        "duration_s",
        "distance_m",
        "load",
        "load_model",
        "avg_hr",
        "avg_power",
        "moving_duration_s",
        "elevation_gain_m",
        "intensity_pct",
        "max_hr",
        "normalized_power",
        "avg_cadence",
        "energy_kj",
        "name",
        "details",
        "fetched_at",
        "created_at",
        "updated_at",
    },
    "observations": {
        "id",
        "natural_key",
        "metric",
        "value",
        "unit",
        "method",
        "aggregation",
        "source_kind",
        "recorded_by",
        "provider",
        "source_record_id",
        "sport",
        "observed_on",
        "observed_at",
        "retrieved_at",
        "label",
        "details",
        "mapper_version",
        "created_at",
        "updated_at",
    },
    "sessions": {"token_hash", "csrf_hash", "expires_at", "created_at", "last_seen"},
    "activity_detail_sets": {
        "provider",
        "provider_activity_id",
        "detail_kind",
        "mapper_version",
        "origin",
        "source_kind",
        "recorded_by",
        "source_record_id",
        "resolution",
        "lap_source",
        "zone_boundary_source",
        "summary_sha256",
        "content_sha256",
        "fetched_at",
        "created_at",
        "updated_at",
    },
    "activity_stream_channels": {
        "provider",
        "provider_activity_id",
        "detail_kind",
        "channel",
        "point_count",
        "valid_count",
        "data",
    },
    "activity_laps": {
        "provider",
        "provider_activity_id",
        "detail_kind",
        "lap_index",
        "kind",
        "start_offset_s",
        "end_offset_s",
        "name",
        "moving_duration_s",
        "distance_m",
        "avg_hr",
        "max_hr",
        "avg_power",
        "max_power",
        "normalized_power",
        "avg_cadence",
        "avg_speed_mps",
        "elevation_gain_m",
        "load",
        "intensity_pct",
        "max_speed_mps",
    },
    "activity_zone_times": {
        "provider",
        "provider_activity_id",
        "detail_kind",
        "zone_index",
        "seconds",
        "lower_bound",
        "upper_bound",
        "label",
    },
    "activity_detail_analysis": {
        "activity_id",
        "analysis_version",
        "input_sha256",
        "payload",
        "computed_at",
        "created_at",
        "updated_at",
    },
    "food_database_entries": {
        "food_id",
        "barcode",
        "name",
        "brand",
        "payload",
        "fetched_at",
        "updated_at",
    },
    "sleep_periods": {
        "provider",
        "started_at",
        "ended_at",
        "wake_date",
        "timezone",
        "kind",
        "reported_duration_s",
        "bounds_method",
        "source_kind",
        "recorded_by",
        "source_record_id",
        "retrieved_at",
        "label",
        "details",
        "mapper_version",
        "state",
        "created_at",
        "updated_at",
    },
    "zone_configurations": {
        "config_key",
        "provider",
        "sport",
        "metric",
        "environment",
        "valid_from",
        "valid_until",
        "threshold",
        "maximum",
        "resting",
        "limits",
        "percent_limits",
        "percent_basis",
        "source_kind",
        "recorded_by",
        "source_record_id",
        "retrieved_at",
        "label",
        "details",
        "mapper_version",
        "state",
        "created_at",
        "updated_at",
    },
    "categorical_observations": {
        "natural_key",
        "domain",
        "code",
        "provider",
        "sport",
        "observed_on",
        "observed_at",
        "source_kind",
        "recorded_by",
        "source_record_id",
        "retrieved_at",
        "label",
        "details",
        "mapper_version",
        "state",
        "created_at",
        "updated_at",
    },
    "gear_items": {
        "provider",
        "gear_id",
        "name",
        "type_label",
        "activity_type_label",
        "status_label",
        "maximum_distance_m",
        "total_distance_m",
        "total_activities",
        "source_kind",
        "recorded_by",
        "source_record_id",
        "retrieved_at",
        "label",
        "details",
        "mapper_version",
        "state",
        "created_at",
        "updated_at",
    },
    "gear_activity_links": {
        "provider",
        "gear_id",
        "provider_activity_id",
        "source_kind",
        "recorded_by",
        "source_record_id",
        "retrieved_at",
        "label",
        "mapper_version",
        "state",
        "created_at",
        "updated_at",
    },
}

CURRENT_DATABASE_INDEXES = {
    "idx_activity_feedback_session",
    "idx_activity_records_activity",
    "idx_activity_records_local_date",
    "idx_activity_records_started",
    "idx_activity_sessions_local_date",
    "idx_activity_sessions_merged_into",
    "idx_categorical_observations_domain_date",
    "idx_categorical_observations_source",
    "idx_change_history_created_at",
    "idx_change_history_entity",
    "idx_coach_plan_artifacts_conversation",
    "idx_food_database_entries_name",
    "idx_gear_activity_links_activity",
    "idx_gear_activity_links_source",
    "idx_nutrition_logs_date",
    "idx_nutrition_products_name",
    "idx_nutrition_products_status",
    "idx_observations_metric_date",
    "idx_planned_units_date",
    "idx_planned_units_external_id",
    "idx_planned_units_local_id",
    "idx_provider_records_observed",
    "idx_provider_records_reprojection",
    "idx_provider_refresh_area",
    "idx_provider_refresh_created_at",
    "idx_remote_links_remote_id",
    "idx_sleep_periods_source",
    "idx_sleep_periods_wake_date",
    "idx_sync_job_items_status",
    "idx_sync_jobs_status_available",
    "idx_workout_library_external_id",
}


CURRENT_SCHEMA_VERSION = 15

# Provider-neutral canonical tables (schema version 6). Only closed lifecycle
# enums are CHECKed here; they are generated from backend.canonical.vocabulary so
# the SQL cannot drift from Python. Open vocabularies (provider, sport,
# environment, metric, unit, load model, source kind, recording origin) and
# numeric ranges are validated by backend.canonical before a row is written, so
# one invalid record is skipped and counted instead of aborting an ingest.
# tests/test_db_provider_schema.py checks the generated lists and the table shape.


def _sql_in_list(enum_type: type[StrEnum]) -> str:
    return _sql_in_list_of(enum_type.__members__.values())


def _sql_in_list_of(members: Iterable[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in members)


_PROVIDER_RECORD_STATES = _sql_in_list(ProviderRecordState)
_ACTIVITY_RECORD_STATES = _sql_in_list(ActivityRecordState)
_LINK_KINDS = _sql_in_list(ActivityLinkKind)
_SESSION_STATES = _sql_in_list(ActivitySessionState)

PROVIDER_TABLES_DDL = f"""
    CREATE TABLE provider_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        record_kind TEXT NOT NULL CHECK (length(record_kind) BETWEEN 1 AND 64),
        source_record_id TEXT NOT NULL CHECK (length(source_record_id) BETWEEN 1 AND 256),
        payload TEXT NOT NULL DEFAULT '{{}}' CHECK (json_valid(payload) AND json_type(payload) = 'object'),
        payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
        fetched_at TEXT NOT NULL,
        mapped_version INTEGER,
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_PROVIDER_RECORD_STATES})),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        observed_on TEXT,
        UNIQUE (provider, record_kind, source_record_id)
    );
    CREATE INDEX idx_provider_records_reprojection ON provider_records(provider, record_kind, mapped_version);
    CREATE INDEX idx_provider_records_observed ON provider_records(provider, record_kind, observed_on);
    CREATE TABLE activity_sessions (
        activity_id TEXT PRIMARY KEY CHECK (substr(activity_id, 1, 4) = 'act_' AND length(activity_id) BETWEEN 5 AND 128),
        primary_provider TEXT NOT NULL CHECK (length(primary_provider) BETWEEN 1 AND 64),
        primary_provider_activity_id TEXT NOT NULL CHECK (length(primary_provider_activity_id) BETWEEN 1 AND 256),
        link_kind TEXT NOT NULL DEFAULT 'single' CHECK (link_kind IN ({_LINK_KINDS})),
        athlete_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (athlete_confirmed IN (0, 1)),
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_SESSION_STATES})),
        merged_into TEXT REFERENCES activity_sessions(activity_id),
        started_at TEXT NOT NULL,
        local_date TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK ((state = 'duplicate') = (merged_into IS NOT NULL))
    );
    CREATE INDEX idx_activity_sessions_local_date ON activity_sessions(local_date);
    CREATE INDEX idx_activity_sessions_merged_into ON activity_sessions(merged_into);
    CREATE TABLE activity_records (
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        provider_activity_id TEXT NOT NULL CHECK (length(provider_activity_id) BETWEEN 1 AND 256),
        activity_id TEXT REFERENCES activity_sessions(activity_id),
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_ACTIVITY_RECORD_STATES})),
        mapper_version INTEGER NOT NULL,
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT CHECK (source_record_id IS NULL OR length(source_record_id) BETWEEN 1 AND 256),
        sport TEXT NOT NULL,
        environment TEXT NOT NULL,
        started_at TEXT NOT NULL,
        local_date TEXT,
        duration_s REAL,
        distance_m REAL,
        load REAL,
        load_model TEXT NOT NULL,
        avg_hr REAL,
        avg_power REAL,
        moving_duration_s REAL,
        elevation_gain_m REAL,
        intensity_pct REAL,
        max_hr REAL,
        normalized_power REAL,
        avg_cadence REAL,
        energy_kj REAL,
        name TEXT,
        details TEXT NOT NULL DEFAULT '{{}}' CHECK (json_valid(details) AND json_type(details) = 'object'),
        fetched_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, provider_activity_id)
    );
    CREATE INDEX idx_activity_records_local_date ON activity_records(local_date);
    CREATE INDEX idx_activity_records_activity ON activity_records(activity_id);
    CREATE INDEX idx_activity_records_started ON activity_records(started_at);
    CREATE TABLE observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        natural_key TEXT NOT NULL UNIQUE CHECK (length(natural_key) BETWEEN 1 AND 512),
        metric TEXT NOT NULL CHECK (length(metric) BETWEEN 1 AND 64),
        value REAL NOT NULL,
        unit TEXT NOT NULL CHECK (length(unit) BETWEEN 1 AND 16),
        method TEXT,
        aggregation TEXT,
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        provider TEXT CHECK (provider IS NULL OR length(provider) BETWEEN 1 AND 64),
        source_record_id TEXT CHECK (source_record_id IS NULL OR length(source_record_id) BETWEEN 1 AND 256),
        sport TEXT,
        observed_on TEXT NOT NULL,
        observed_at TEXT,
        retrieved_at TEXT,
        label TEXT,
        details TEXT NOT NULL DEFAULT '{{}}' CHECK (json_valid(details) AND json_type(details) = 'object'),
        mapper_version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_observations_metric_date ON observations(metric, observed_on);
"""

NUTRITION_PRODUCTS_DDL = """
    CREATE TABLE nutrition_products (
        id TEXT PRIMARY KEY,
        barcode TEXT UNIQUE,
        name TEXT NOT NULL,
        brand TEXT NOT NULL DEFAULT '',
        basis_amount REAL NOT NULL CHECK (basis_amount > 0),
        basis_unit TEXT NOT NULL CHECK (basis_unit IN ('g', 'ml', 'portion')),
        kcal REAL,
        carbs_g REAL,
        protein_g REAL,
        fat_g REAL,
        sugar_g REAL,
        fiber_g REAL,
        salt_g REAL,
        source TEXT NOT NULL CHECK (source IN ('packaging_label', 'manual', 'open_food_facts', 'yazio', 'bls', 'fddb_export')),
        source_url TEXT NOT NULL DEFAULT '',
        external_id TEXT NOT NULL DEFAULT '',
        provenance TEXT NOT NULL DEFAULT 'manual',
        extraction_confidence REAL,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_nutrition_products_name ON nutrition_products(name COLLATE NOCASE);
    CREATE INDEX idx_nutrition_products_status ON nutrition_products(status, updated_at DESC);
"""


# Shared by initialize_schema and the schema-version-7 migration, which rebuilds
# the table so its stored definition matches this text exactly.
ACTIVITY_FEEDBACK_TABLE_SQL = """
    CREATE TABLE activity_feedback (
        activity_id TEXT PRIMARY KEY,
        activity_name TEXT NOT NULL DEFAULT '',
        activity_date TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        session_rpe REAL CHECK (session_rpe IS NULL OR (session_rpe >= 0 AND session_rpe <= 10)),
        deviation_reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        provider TEXT
    )"""


# Shared by initialize_schema and the schema-version-9 migration, which rebuilds
# the table so its stored definition matches this text exactly. sport is a
# canonical Sport value; environment (Environment) and sport_detail (the original
# sport text kept losslessly when it has no canonical counterpart) are NULL on
# rows written before schema version 9 or when nothing more is known.
COMPETITIONS_TABLE_SQL = """
    CREATE TABLE competitions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        event_date TEXT NOT NULL,
        sport TEXT NOT NULL,
        environment TEXT,
        sport_detail TEXT,
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
    )"""

# Shared by initialize_schema and the schema-version-8 migration, which rebuilds
# the table so its stored definition matches this text exactly. The provider
# column is NULL for rows written before provider-neutral remote links.
COMPETITION_SYNC_TOMBSTONES_TABLE_SQL = """
    CREATE TABLE competition_sync_tombstones (
        id TEXT PRIMARY KEY,
        intervals_event_id TEXT,
        external_id TEXT,
        created_at TEXT NOT NULL,
        provider TEXT
    )"""

# Provider-neutral link between one local entity and its counterpart at one
# remote provider (schema version 8). It is separate from PROVIDER_TABLES_DDL so
# the schema-version-6 upgrade keeps creating exactly the version-6 tables. The
# open vocabularies (entity kind, provider, state) are validated by
# backend.db.remote_links before a row is written, like the canonical tables.
REMOTE_LINKS_DDL = """
    CREATE TABLE remote_links (
        entity_kind TEXT NOT NULL CHECK (length(entity_kind) BETWEEN 1 AND 64),
        local_id TEXT NOT NULL CHECK (length(local_id) >= 1),
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        remote_id TEXT,
        remote_external_id TEXT,
        baseline_hash TEXT,
        sync_state TEXT NOT NULL CHECK (length(sync_state) BETWEEN 1 AND 64),
        last_synced_at TEXT,
        PRIMARY KEY (entity_kind, local_id, provider)
    );
    CREATE UNIQUE INDEX idx_remote_links_remote_id
        ON remote_links(provider, entity_kind, remote_id) WHERE remote_id IS NOT NULL;
"""


# Canonical activity detail (schema version 10): one set per provider activity
# and detail kind, so every provider keeps its own alternative streams, laps and
# zone times for the same session. Sets reference their activity record, whose
# deletion is a tombstone; readers filter on active records and sessions, so the
# detail of a deleted activity is hidden, not destroyed. Only the closed kind and
# origin vocabularies are CHECKed; resolution, lap source, boundary source,
# channel and lap kind are validated by backend.canonical.activity_detail.
# Stream channels hold zlib-compressed little-endian float64 points (NaN = gap).
# The analysis row caches values computed for one canonical session.
# The schema-version-10 migration executes this same text.
_DETAIL_KINDS = _sql_in_list(ActivityDetailKind)
_DETAIL_ORIGINS = _sql_in_list(ActivityDetailOrigin)
_ZONE_DETAIL_KINDS = _sql_in_list_of(ZONE_DETAIL_KINDS.values())

ACTIVITY_DETAIL_DDL = f"""
    CREATE TABLE activity_detail_sets (
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        provider_activity_id TEXT NOT NULL CHECK (length(provider_activity_id) BETWEEN 1 AND 256),
        detail_kind TEXT NOT NULL CHECK (detail_kind IN ({_DETAIL_KINDS})),
        mapper_version INTEGER NOT NULL CHECK (mapper_version >= 1),
        origin TEXT NOT NULL CHECK (origin IN ({_DETAIL_ORIGINS})),
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT CHECK (source_record_id IS NULL OR length(source_record_id) BETWEEN 1 AND 256),
        resolution TEXT CHECK (resolution IS NULL OR length(resolution) BETWEEN 1 AND 32),
        lap_source TEXT CHECK (lap_source IS NULL OR length(lap_source) BETWEEN 1 AND 32),
        zone_boundary_source TEXT CHECK (zone_boundary_source IS NULL OR length(zone_boundary_source) BETWEEN 1 AND 32),
        summary_sha256 TEXT CHECK (summary_sha256 IS NULL OR length(summary_sha256) = 64),
        content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
        fetched_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, provider_activity_id, detail_kind),
        FOREIGN KEY (provider, provider_activity_id)
            REFERENCES activity_records(provider, provider_activity_id),
        CHECK ((detail_kind = 'streams') = (resolution IS NOT NULL)),
        CHECK ((detail_kind = 'laps') = (lap_source IS NOT NULL)),
        CHECK ((detail_kind IN ({_ZONE_DETAIL_KINDS})) = (zone_boundary_source IS NOT NULL))
    );
    CREATE TABLE activity_stream_channels (
        provider TEXT NOT NULL,
        provider_activity_id TEXT NOT NULL,
        detail_kind TEXT NOT NULL DEFAULT 'streams' CHECK (detail_kind = 'streams'),
        channel TEXT NOT NULL CHECK (length(channel) BETWEEN 1 AND 64),
        point_count INTEGER NOT NULL CHECK (point_count BETWEEN 1 AND 172800),
        valid_count INTEGER NOT NULL CHECK (valid_count BETWEEN 0 AND point_count),
        data BLOB NOT NULL CHECK (typeof(data) = 'blob' AND length(data) BETWEEN 1 AND 4194304),
        PRIMARY KEY (provider, provider_activity_id, channel),
        FOREIGN KEY (provider, provider_activity_id, detail_kind)
            REFERENCES activity_detail_sets(provider, provider_activity_id, detail_kind)
            ON DELETE CASCADE
    );
    CREATE TABLE activity_laps (
        provider TEXT NOT NULL,
        provider_activity_id TEXT NOT NULL,
        detail_kind TEXT NOT NULL DEFAULT 'laps' CHECK (detail_kind = 'laps'),
        lap_index INTEGER NOT NULL CHECK (lap_index BETWEEN 0 AND 199),
        kind TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 32),
        start_offset_s REAL NOT NULL CHECK (start_offset_s >= 0),
        end_offset_s REAL NOT NULL CHECK (end_offset_s >= start_offset_s),
        name TEXT CHECK (name IS NULL OR length(name) BETWEEN 1 AND 200),
        moving_duration_s REAL,
        distance_m REAL,
        avg_hr REAL,
        max_hr REAL,
        avg_power REAL,
        max_power REAL,
        normalized_power REAL,
        avg_cadence REAL,
        avg_speed_mps REAL,
        elevation_gain_m REAL,
        load REAL,
        intensity_pct REAL,
        max_speed_mps REAL,
        PRIMARY KEY (provider, provider_activity_id, lap_index),
        FOREIGN KEY (provider, provider_activity_id, detail_kind)
            REFERENCES activity_detail_sets(provider, provider_activity_id, detail_kind)
            ON DELETE CASCADE
    );
    CREATE TABLE activity_zone_times (
        provider TEXT NOT NULL,
        provider_activity_id TEXT NOT NULL,
        detail_kind TEXT NOT NULL CHECK (detail_kind IN ({_ZONE_DETAIL_KINDS})),
        zone_index INTEGER NOT NULL CHECK (zone_index BETWEEN 1 AND 20),
        seconds REAL NOT NULL CHECK (seconds >= 0),
        lower_bound REAL,
        upper_bound REAL,
        label TEXT CHECK (label IS NULL OR length(label) BETWEEN 1 AND 64),
        PRIMARY KEY (provider, provider_activity_id, detail_kind, zone_index),
        FOREIGN KEY (provider, provider_activity_id, detail_kind)
            REFERENCES activity_detail_sets(provider, provider_activity_id, detail_kind)
            ON DELETE CASCADE
    );
    CREATE TABLE activity_detail_analysis (
        activity_id TEXT PRIMARY KEY REFERENCES activity_sessions(activity_id),
        analysis_version INTEGER NOT NULL CHECK (analysis_version >= 1),
        input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
        payload TEXT NOT NULL CHECK (json_valid(payload) AND json_type(payload) = 'object'),
        computed_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
"""


# Local mirror of external food database hits (schema version 11, Yazio ids
# since 14). The payload is the projected, validated food record; name and
# brand are searchable copies.
FOOD_DATABASE_DDL = """
    CREATE TABLE food_database_entries (
        food_id TEXT PRIMARY KEY CHECK (food_id GLOB 'off:*' OR food_id GLOB 'yazio:*'),
        barcode TEXT NOT NULL,
        name TEXT NOT NULL,
        brand TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL CHECK (json_valid(payload) AND json_type(payload) = 'object'),
        fetched_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_food_database_entries_name ON food_database_entries(name COLLATE NOCASE);
"""


# Canonical model extensions (schema version 15). initialize_schema and the
# schema-version-15 migration execute this same text, ALTER statements included,
# so new and upgraded databases store identical definitions. Rows keep their
# provider, source record and mapper version; a reprojection that no longer
# emits a row retires it (state) instead of deleting it. Zone limits are JSON
# arrays of ascending upper zone limits, absolute in the metric's canonical unit
# or as percentages of percent_basis; a local zone configuration has no
# provider. Open vocabularies and value ranges are validated by
# backend.canonical before a row is written.
# activity_feedback.session_id is the session the feedback was written for; a
# merge never re-points it. merged_into_retained keeps the survivor of a merged
# session whose deletion had to clear merged_into.
_PROJECTION_STATES = _sql_in_list(ProjectionState)

CANONICAL_EXTENSIONS_DDL = f"""
    CREATE TABLE sleep_periods (
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        wake_date TEXT NOT NULL CHECK (length(wake_date) = 10),
        timezone TEXT CHECK (timezone IS NULL OR length(timezone) BETWEEN 1 AND 64),
        kind TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 32),
        reported_duration_s REAL,
        bounds_method TEXT CHECK (bounds_method IS NULL OR length(bounds_method) BETWEEN 1 AND 64),
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT NOT NULL CHECK (length(source_record_id) BETWEEN 1 AND 256),
        retrieved_at TEXT,
        label TEXT,
        details TEXT NOT NULL DEFAULT '{{}}' CHECK (json_valid(details) AND json_type(details) = 'object'),
        mapper_version INTEGER NOT NULL CHECK (mapper_version >= 1),
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_PROJECTION_STATES})),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, started_at)
    );
    CREATE INDEX idx_sleep_periods_wake_date ON sleep_periods(wake_date);
    CREATE INDEX idx_sleep_periods_source ON sleep_periods(provider, source_record_id);
    CREATE TABLE zone_configurations (
        config_key TEXT PRIMARY KEY CHECK (length(config_key) BETWEEN 1 AND 512),
        provider TEXT CHECK (provider IS NULL OR length(provider) BETWEEN 1 AND 64),
        sport TEXT CHECK (sport IS NULL OR length(sport) BETWEEN 1 AND 32),
        metric TEXT NOT NULL CHECK (length(metric) BETWEEN 1 AND 32),
        environment TEXT CHECK (environment IS NULL OR length(environment) BETWEEN 1 AND 32),
        valid_from TEXT,
        valid_until TEXT,
        threshold REAL,
        maximum REAL,
        resting REAL,
        limits TEXT CHECK (limits IS NULL OR (json_valid(limits) AND json_type(limits) = 'array')),
        percent_limits TEXT CHECK (percent_limits IS NULL OR (json_valid(percent_limits) AND json_type(percent_limits) = 'array')),
        percent_basis TEXT CHECK (percent_basis IS NULL OR length(percent_basis) BETWEEN 1 AND 32),
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT CHECK (source_record_id IS NULL OR length(source_record_id) BETWEEN 1 AND 256),
        retrieved_at TEXT,
        label TEXT,
        details TEXT NOT NULL DEFAULT '{{}}' CHECK (json_valid(details) AND json_type(details) = 'object'),
        mapper_version INTEGER CHECK (mapper_version IS NULL OR mapper_version >= 1),
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_PROJECTION_STATES})),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE categorical_observations (
        natural_key TEXT PRIMARY KEY CHECK (length(natural_key) BETWEEN 1 AND 512),
        domain TEXT NOT NULL CHECK (length(domain) BETWEEN 1 AND 64),
        code TEXT NOT NULL CHECK (length(code) BETWEEN 1 AND 64),
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        sport TEXT CHECK (sport IS NULL OR length(sport) BETWEEN 1 AND 32),
        observed_on TEXT NOT NULL CHECK (length(observed_on) = 10),
        observed_at TEXT,
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT NOT NULL CHECK (length(source_record_id) BETWEEN 1 AND 256),
        retrieved_at TEXT,
        label TEXT,
        details TEXT NOT NULL DEFAULT '{{}}' CHECK (json_valid(details) AND json_type(details) = 'object'),
        mapper_version INTEGER NOT NULL CHECK (mapper_version >= 1),
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_PROJECTION_STATES})),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_categorical_observations_domain_date ON categorical_observations(domain, observed_on);
    CREATE INDEX idx_categorical_observations_source ON categorical_observations(provider, source_record_id);
    CREATE TABLE gear_items (
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        gear_id TEXT NOT NULL CHECK (length(gear_id) BETWEEN 1 AND 256),
        name TEXT CHECK (name IS NULL OR length(name) BETWEEN 1 AND 200),
        type_label TEXT CHECK (type_label IS NULL OR length(type_label) BETWEEN 1 AND 100),
        activity_type_label TEXT CHECK (activity_type_label IS NULL OR length(activity_type_label) BETWEEN 1 AND 100),
        status_label TEXT CHECK (status_label IS NULL OR length(status_label) BETWEEN 1 AND 100),
        maximum_distance_m REAL,
        total_distance_m REAL,
        total_activities INTEGER,
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT NOT NULL CHECK (length(source_record_id) BETWEEN 1 AND 256),
        retrieved_at TEXT,
        label TEXT,
        details TEXT NOT NULL DEFAULT '{{}}' CHECK (json_valid(details) AND json_type(details) = 'object'),
        mapper_version INTEGER NOT NULL CHECK (mapper_version >= 1),
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_PROJECTION_STATES})),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, gear_id)
    );
    CREATE TABLE gear_activity_links (
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        gear_id TEXT NOT NULL CHECK (length(gear_id) BETWEEN 1 AND 256),
        provider_activity_id TEXT NOT NULL CHECK (length(provider_activity_id) BETWEEN 1 AND 256),
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT NOT NULL CHECK (length(source_record_id) BETWEEN 1 AND 256),
        retrieved_at TEXT,
        label TEXT,
        mapper_version INTEGER NOT NULL CHECK (mapper_version >= 1),
        state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ({_PROJECTION_STATES})),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (provider, gear_id, provider_activity_id)
    );
    CREATE INDEX idx_gear_activity_links_activity ON gear_activity_links(provider, provider_activity_id);
    CREATE INDEX idx_gear_activity_links_source ON gear_activity_links(provider, source_record_id);
    ALTER TABLE activity_feedback ADD COLUMN session_id TEXT REFERENCES activity_sessions(activity_id);
    CREATE INDEX idx_activity_feedback_session ON activity_feedback(session_id);
    ALTER TABLE activity_sessions ADD COLUMN merged_into_retained TEXT REFERENCES activity_sessions(activity_id) CHECK (merged_into_retained IS NULL OR state = 'deleted')
"""


def execute_ddl(db: Any, ddl: str) -> None:
    """Run DDL statement by statement inside the caller's transaction.

    executescript() would commit first, so creation and migration could not
    stay atomic. None of the DDL constants contains a semicolon inside a string.
    """
    for statement in ddl.split(";"):
        if statement.strip():
            db.execute(statement)


def initialize_schema(db: Any) -> None:
    """Create the exact current schema on a new database connection, atomically.

    executescript() would commit each statement on its own, so an interrupted
    creation could leave a partial schema. The statements run in one transaction.
    """
    try:
        _create_schema_statements(db)
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


def _create_schema_statements(db: Any) -> None:
    db.executescript(
        """
    PRAGMA journal_mode=WAL;
    BEGIN IMMEDIATE;
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
        created_at TEXT NOT NULL,
        synced_at TEXT NOT NULL DEFAULT '',
        recent_activity_count INTEGER NOT NULL DEFAULT 0
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
    """
        + COMPETITIONS_TABLE_SQL
        + """;
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
    """
        + ACTIVITY_FEEDBACK_TABLE_SQL
        + ";\n"
        + COMPETITION_SYNC_TOMBSTONES_TABLE_SQL
        + """;
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
        no_training INTEGER NOT NULL DEFAULT 0,
        UNIQUE(uid, start_local)
    );
    CREATE TABLE nutrition_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE nutrition_logs (
        id TEXT PRIMARY KEY,
        nutrition_basis TEXT NOT NULL DEFAULT '{}',
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
        updated_at TEXT NOT NULL , logged_time_known INTEGER NOT NULL DEFAULT 1);
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
    for statement in NUTRITION_PRODUCTS_DDL.split(";"):
        if statement.strip():
            db.execute(statement)
    db.execute(
        "CREATE UNIQUE INDEX idx_workout_library_external_id ON workout_library(external_id) WHERE external_id IS NOT NULL"
    )
    db.execute(
        "CREATE UNIQUE INDEX idx_planned_units_local_id ON planned_units(local_id)"
    )
    db.execute(
        "CREATE INDEX idx_planned_units_external_id ON planned_units(external_id)"
    )
    db.execute(
        "CREATE INDEX idx_planned_units_date ON planned_units(json_extract(payload, '$.date'))"
    )

    execute_ddl(db, PROVIDER_TABLES_DDL)
    execute_ddl(db, REMOTE_LINKS_DDL)
    execute_ddl(db, ACTIVITY_DETAIL_DDL)
    execute_ddl(db, FOOD_DATABASE_DDL)
    execute_ddl(db, CANONICAL_EXTENSIONS_DDL)
    db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")


def configure_cipher(db: Any, password: str) -> None:
    db.execute(f"PRAGMA key='{password.replace(chr(39), chr(39) * 2)}'")
    db.execute("PRAGMA cipher_compatibility = 4")
    # The database file stays encrypted. Memory security would mlock every
    # SQLCipher allocation; interleaved locked and unlocked heap ranges split
    # the process into tens of thousands of mappings until mmap fails near the
    # kernel's vm.max_map_count. Anyone able to read process memory or swap on
    # this host can also read APP_PASSWORD, so it adds little protection here.
    db.execute("PRAGMA cipher_memory_security = OFF")


def database_table_names(db: Any) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if not str(row["name"]).startswith("sqlite_")
    }


def database_index_names(db: Any) -> set[str]:
    return {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        if not str(row["name"]).startswith("sqlite_")
    }


def database_schema_signature(db: Any) -> tuple[tuple[str, str, str, str], ...]:
    """Compare all declared tables, constraints, indexes, triggers and views."""
    return tuple(
        (row["type"], row["name"], row["tbl_name"], " ".join(row["sql"].split()))
        for row in db.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT GLOB 'sqlite_*' ORDER BY type, name"
        )
    )


@lru_cache(maxsize=1)
def current_schema_signature() -> tuple[tuple[str, str, str, str], ...]:
    # An empty in-memory reference contains schema only, never athlete data.
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.row_factory = sqlite3.Row
        initialize_schema(reference)
        return database_schema_signature(reference)


def database_schema_is_current(db: Any) -> bool:
    if (
        db.execute("PRAGMA user_version").fetchone()["user_version"]
        not in (0, CURRENT_SCHEMA_VERSION)
        or database_table_names(db) != set(CURRENT_DATABASE_SCHEMA)
        or database_index_names(db) != CURRENT_DATABASE_INDEXES
    ):
        return False
    return database_schema_signature(db) == current_schema_signature() and all(
        columns
        == {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        for table, columns in CURRENT_DATABASE_SCHEMA.items()
    )
