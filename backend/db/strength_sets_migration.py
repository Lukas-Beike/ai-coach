"""Schema version 22: the strength set detail kind, as a frozen upgrade step.

SQLite cannot alter the kind CHECK of ``activity_detail_sets``, so the step
rebuilds the detail set tables and adds ``activity_strength_sets``. Foreign keys
stay enforced, as the application connects: the released tables are renamed
aside (the parent rename retargets the child references to the renamed parent),
the tables are created again from the schema version 22 text, every row is
copied once inside the database file, and the renamed children are dropped
before their parent, so no cascade deletes a row. The DDL is frozen here so later
schema changes cannot alter what this step produces; ``set_source`` stays NULL,
as no released set is a strength set.
"""

from __future__ import annotations

from typing import Any, Final

_RETIRED_SUFFIX: Final = "_v21"

DETAIL_SETS_V22_DDL: Final = """
    CREATE TABLE activity_detail_sets (
        provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
        provider_activity_id TEXT NOT NULL CHECK (length(provider_activity_id) BETWEEN 1 AND 256),
        detail_kind TEXT NOT NULL CHECK (detail_kind IN ('streams', 'laps', 'heart_rate_zones', 'power_zones', 'strength_sets')),
        mapper_version INTEGER NOT NULL CHECK (mapper_version >= 1),
        origin TEXT NOT NULL CHECK (origin IN ('fetch', 'legacy_backfill')),
        source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 64),
        recorded_by TEXT NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 64),
        source_record_id TEXT CHECK (source_record_id IS NULL OR length(source_record_id) BETWEEN 1 AND 256),
        resolution TEXT CHECK (resolution IS NULL OR length(resolution) BETWEEN 1 AND 32),
        lap_source TEXT CHECK (lap_source IS NULL OR length(lap_source) BETWEEN 1 AND 32),
        zone_boundary_source TEXT CHECK (zone_boundary_source IS NULL OR length(zone_boundary_source) BETWEEN 1 AND 32),
        set_source TEXT CHECK (set_source IS NULL OR length(set_source) BETWEEN 1 AND 32),
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
        CHECK ((detail_kind IN ('heart_rate_zones', 'power_zones')) = (zone_boundary_source IS NOT NULL)),
        CHECK ((detail_kind = 'strength_sets') = (set_source IS NOT NULL))
    )"""

STRENGTH_SETS_V22_DDL: Final = """
    CREATE TABLE activity_strength_sets (
        provider TEXT NOT NULL,
        provider_activity_id TEXT NOT NULL,
        detail_kind TEXT NOT NULL DEFAULT 'strength_sets' CHECK (detail_kind = 'strength_sets'),
        set_index INTEGER NOT NULL CHECK (set_index BETWEEN 0 AND 499),
        set_type TEXT NOT NULL CHECK (length(set_type) BETWEEN 1 AND 16),
        exercise_category TEXT CHECK (exercise_category IS NULL OR length(exercise_category) BETWEEN 1 AND 64),
        exercise_name TEXT CHECK (exercise_name IS NULL OR length(exercise_name) BETWEEN 1 AND 64),
        reps INTEGER CHECK (reps IS NULL OR reps BETWEEN 0 AND 1000),
        weight_kg REAL CHECK (weight_kg IS NULL OR (weight_kg > 0 AND weight_kg <= 1000)),
        duration_s REAL CHECK (duration_s IS NULL OR duration_s >= 0),
        start_offset_s REAL CHECK (start_offset_s IS NULL OR start_offset_s >= 0),
        workout_step_index INTEGER CHECK (workout_step_index IS NULL OR workout_step_index BETWEEN 0 AND 999),
        PRIMARY KEY (provider, provider_activity_id, set_index),
        FOREIGN KEY (provider, provider_activity_id, detail_kind)
            REFERENCES activity_detail_sets(provider, provider_activity_id, detail_kind)
            ON DELETE CASCADE
    )"""


ACTIVITY_STREAM_CHANNELS_V22_DDL: Final = """
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
    )"""

ACTIVITY_LAPS_V22_DDL: Final = """
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
    )"""

ACTIVITY_ZONE_TIMES_V22_DDL: Final = """
    CREATE TABLE activity_zone_times (
        provider TEXT NOT NULL,
        provider_activity_id TEXT NOT NULL,
        detail_kind TEXT NOT NULL CHECK (detail_kind IN ('heart_rate_zones', 'power_zones')),
        zone_index INTEGER NOT NULL CHECK (zone_index BETWEEN 1 AND 20),
        seconds REAL NOT NULL CHECK (seconds >= 0),
        lower_bound REAL,
        upper_bound REAL,
        label TEXT CHECK (label IS NULL OR length(label) BETWEEN 1 AND 64),
        PRIMARY KEY (provider, provider_activity_id, detail_kind, zone_index),
        FOREIGN KEY (provider, provider_activity_id, detail_kind)
            REFERENCES activity_detail_sets(provider, provider_activity_id, detail_kind)
            ON DELETE CASCADE
    )"""

# (table, frozen DDL, copied columns of schema version 21), parent first.
_REBUILT_TABLES: Final = (
    (
        "activity_detail_sets",
        DETAIL_SETS_V22_DDL,
        (
            "provider, provider_activity_id, detail_kind, mapper_version, origin, "
            "source_kind, recorded_by, source_record_id, resolution, lap_source, "
            "zone_boundary_source, summary_sha256, content_sha256, fetched_at, "
            "created_at, updated_at"
        ),
    ),
    (
        "activity_stream_channels",
        ACTIVITY_STREAM_CHANNELS_V22_DDL,
        (
            "provider, provider_activity_id, detail_kind, channel, point_count, "
            "valid_count, data"
        ),
    ),
    (
        "activity_laps",
        ACTIVITY_LAPS_V22_DDL,
        (
            "provider, provider_activity_id, detail_kind, lap_index, kind, "
            "start_offset_s, end_offset_s, name, moving_duration_s, distance_m, "
            "avg_hr, max_hr, avg_power, max_power, normalized_power, avg_cadence, "
            "avg_speed_mps, elevation_gain_m, load, intensity_pct, max_speed_mps"
        ),
    ),
    (
        "activity_zone_times",
        ACTIVITY_ZONE_TIMES_V22_DDL,
        (
            "provider, provider_activity_id, detail_kind, zone_index, seconds, "
            "lower_bound, upper_bound, label"
        ),
    ),
)


def add_strength_sets(db: Any) -> None:
    """Rebuild the detail set tables for the strength kind inside the caller's transaction."""
    for table, _ddl, _columns in _REBUILT_TABLES:
        db.execute(f"ALTER TABLE {table} RENAME TO {table}{_RETIRED_SUFFIX}")
    for table, ddl, columns in _REBUILT_TABLES:
        db.execute(ddl)
        db.execute(
            f"INSERT INTO {table}({columns}) "
            f"SELECT {columns} FROM {table}{_RETIRED_SUFFIX}"
        )
    # Children first, so dropping the renamed parent cascades into nothing.
    for table, _ddl, _columns in reversed(_REBUILT_TABLES):
        db.execute(f"DROP TABLE {table}{_RETIRED_SUFFIX}")
    db.execute(STRENGTH_SETS_V22_DDL)
    # Enforced keys already reject an orphan; this also covers a connection
    # without enforcement. Other tables are not this step's concern.
    for table in (*(item[0] for item in _REBUILT_TABLES), "activity_strength_sets"):
        if db.execute(f"PRAGMA main.foreign_key_check({table})").fetchall():
            raise RuntimeError("Die Datenbankmigration konnte nicht validiert werden.")
