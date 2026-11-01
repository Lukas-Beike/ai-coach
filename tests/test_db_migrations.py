"""Schema gate: supported released schemas upgrade, anything else stays unchanged."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from backend.canonical.vocabulary import ProviderId
from backend.db import garmin_items_migration, garmin_store, migrations, row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    ACTIVITY_DETAIL_DDL,
    CURRENT_SCHEMA_VERSION,
    FOOD_DATABASE_DDL,
    configure_cipher,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
    initialize_schema,
)
from backend.db.schema_history import (
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V9,
    SHAPE_SCHEMA_V10,
    SHAPE_SCHEMA_V11,
    SHAPE_SCHEMA_V12,
    SHAPE_SCHEMA_V13,
    SHAPE_SCHEMA_V14,
    SHAPE_SCHEMA_V15,
    SHAPE_SCHEMA_V16,
    SHAPE_SCHEMA_V17,
    released_shape,
)

INTERVALS = ProviderId.INTERVALS.value
GARMIN = ProviderId.GARMIN.value
STAMP = "2026-10-16T08:00:00+00:00"
OLDEST_SUPPORTED_VERSION = 9
FIXTURES = Path(__file__).with_name("fixtures")
OLDEST_SUPPORTED_FIXTURE = FIXTURES / "schema_v9.sql.txt"
V10_FIXTURE = FIXTURES / "schema_v10.sql.txt"
V11_FIXTURE = FIXTURES / "schema_v11.sql.txt"
V12_FIXTURE = FIXTURES / "schema_v12.sql.txt"
V13_FIXTURE = FIXTURES / "schema_v13.sql.txt"
# Release schema 14: Yazio food sources; the canonical extensions are version 15.
V14_FIXTURE = FIXTURES / "schema_v14.sql.txt"
# Release schema 15: canonical extensions; version 16 renames planning fields.
V15_FIXTURE = FIXTURES / "schema_v15.sql.txt"
# Release schema 16: planning field names; version 17 adds the power curve.
V16_FIXTURE = FIXTURES / "schema_v16.sql.txt"
# Release schema 17: power curve; version 18 adds the session RPE rating time.
V17_FIXTURE = FIXTURES / "schema_v17.sql.txt"
RELEASED_FIXTURES = (
    OLDEST_SUPPORTED_FIXTURE,
    V10_FIXTURE,
    V11_FIXTURE,
    V12_FIXTURE,
    V13_FIXTURE,
    V14_FIXTURE,
    V15_FIXTURE,
    V16_FIXTURE,
    V17_FIXTURE,
)
# Columns an upgrade renamed: (table, released name) -> current name. Rows read
# with the columns of a released schema compare the same values afterwards.
RENAMED_COLUMNS = {
    ("competitions", "start_date_local"): "starts_at_local",
    ("competitions", "moving_time"): "planned_duration_s",
}
CURRENT_FIXTURE = FIXTURES / f"schema_v{CURRENT_SCHEMA_VERSION}.sql.txt"
DETAIL_TABLES = {
    "activity_detail_sets",
    "activity_stream_channels",
    "activity_laps",
    "activity_zone_times",
    "activity_detail_analysis",
}
MIRROR_TABLES = {"food_database_entries"}
EXTENSION_TABLES = {
    "sleep_periods",
    "zone_configurations",
    "categorical_observations",
    "gear_items",
    "gear_activity_links",
}
# Schema version 17: the canonical power curve; added empty by every upgrade
# whose newest snapshot stores no power curve.
POWER_CURVE_TABLES = {"power_curve_points", "power_curve_fetches"}

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None


class DatabaseSchemaGateTests(unittest.TestCase):
    def connect(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db

    def current_database(self):
        db = self.connect()
        initialize_schema(db)
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.commit()
        return db

    def assert_rejected_unchanged(self, db):
        before = list(db.iterdump())
        version = db.execute("PRAGMA user_version").fetchone()[0]
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], version)

    def test_current_schema_is_accepted_repeatedly_without_changes(self):
        db = self.current_database()
        before = list(db.iterdump())
        migrate_schema(db)
        migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)
        self.assertTrue(database_schema_is_current(db))

    def test_oldest_supported_release_schema_upgrades_to_current(self):
        # Release 1.13.6 is the migration baseline. A schema change must keep
        # this fixture and add a transactional upgrade step from version 9.
        db = self.connect()
        db.executescript(OLDEST_SUPPORTED_FIXTURE.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.commit()
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], OLDEST_SUPPORTED_VERSION
        )
        migrate_schema(db)
        db.commit()
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("SELECT content FROM messages").fetchone()[0], "Hallo"
        )

    def test_older_or_newer_schema_version_is_rejected_without_modification(self):
        for version in (0, OLDEST_SUPPORTED_VERSION - 1, CURRENT_SCHEMA_VERSION + 1):
            with self.subTest(version=version):
                db = self.current_database()
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                self.assert_rejected_unchanged(db)

    def test_unknown_schema_shape_is_rejected_without_modification(self):
        changes = (
            "ALTER TABLE messages ADD COLUMN unknown TEXT",
            "CREATE TABLE unknown_table(id INTEGER PRIMARY KEY)",
            (
                "CREATE TRIGGER unknown_trigger AFTER INSERT ON messages "
                "BEGIN SELECT 1; END"
            ),
        )
        for change in changes:
            with self.subTest(change=change):
                db = self.current_database()
                db.execute(change)
                db.commit()
                self.assert_rejected_unchanged(db)

    def test_remote_links_reject_duplicate_remote_ids_per_provider_and_kind(self):
        db = self.connect()
        initialize_schema(db)
        insert = (
            "INSERT INTO remote_links(entity_kind, local_id, provider, remote_id, "
            "sync_state) VALUES (?, ?, ?, ?, 'synced')"
        )
        db.execute(insert, ("competition", "1", INTERVALS, "9"))
        db.execute(insert, ("competition", "2", "other-provider", "9"))
        db.execute(insert, ("library_workout", "1", INTERVALS, "9"))
        db.execute(insert, ("competition", "3", INTERVALS, None))
        db.execute(insert, ("competition", "4", INTERVALS, None))
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(insert, ("competition", "5", INTERVALS, "9"))

    def populated_v9_database(self, db):
        db.executescript(OLDEST_SUPPORTED_FIXTURE.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            ("activity_detail:synthetic", '{"streams": {"watts": [100, 110]}}', STAMP),
        )
        db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, started_at, created_at, updated_at) "
            "VALUES ('act_1', ?, 'i1', ?, ?, ?)",
            (INTERVALS, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "mapper_version, source_kind, recorded_by, sport, environment, started_at, "
            "load_model, avg_power, fetched_at, created_at, updated_at) "
            "VALUES (?, 'i1', 'act_1', 1, 'provider_reported', 'garmin', 'ride', "
            "'outdoor', ?, 'unknown', 210.5, ?, ?, ?)",
            (INTERVALS, STAMP, STAMP, STAMP, STAMP),
        )
        db.commit()

    def table_columns(self, db, tables):
        return {
            table: [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            for table in tables
        }

    def table_rows(self, db, tables, columns=None):
        # With the columns of a released schema, the rows still compare every
        # original value after an upgrade that adds columns.
        rows = {}
        for table in tables:
            present = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            selected = (
                ", ".join(
                    f'"{name if name in present else RENAMED_COLUMNS.get((table, name), name)}"'
                    for name in columns[table]
                )
                if columns
                else "*"
            )
            rows[table] = [
                tuple(row) for row in db.execute(f"SELECT {selected} FROM {table}")
            ]
        return rows

    def user_tables(self, db):
        return sorted(
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        )

    def test_populated_v9_upgrade_keeps_every_row_and_adds_empty_detail_tables(self):
        db = self.connect()
        self.populated_v9_database(db)
        v9_tables = self.user_tables(db)
        columns = self.table_columns(db, v9_tables)
        before = self.table_rows(db, v9_tables, columns)
        migrate_schema(db)
        db.commit()
        self.assertEqual(self.table_rows(db, v9_tables, columns), before)
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            [
                tuple(row)
                for row in db.execute(
                    "SELECT merged_into_retained FROM activity_sessions"
                )
            ],
            [(None,)],
        )
        for table in sorted(set(self.user_tables(db)) - set(v9_tables)):
            with self.subTest(table=table):
                self.assertIn(
                    table,
                    DETAIL_TABLES
                    | MIRROR_TABLES
                    | EXTENSION_TABLES
                    | POWER_CURVE_TABLES,
                )
                self.assertEqual(
                    db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def populated_v10_database(self, db):
        db.executescript(V10_FIXTURE.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, started_at, created_at, updated_at) "
            "VALUES ('act_1', ?, 'i1', ?, ?, ?)",
            (INTERVALS, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO nutrition_products(id, barcode, name, basis_amount, "
            "basis_unit, kcal, source, created_at, updated_at) "
            "VALUES ('p1', '4001', 'Skyr', 100, 'g', 63, 'manual', ?, ?)",
            (STAMP, STAMP),
        )
        db.commit()
        return db

    def test_frozen_v10_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V10_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V10
        )

    def test_populated_v10_upgrade_keeps_every_row_and_adds_the_empty_mirror(self):
        db = self.populated_v10_database(self.connect())
        v10_tables = self.user_tables(db)
        columns = self.table_columns(db, v10_tables)
        before = self.table_rows(db, v10_tables, columns)
        migrate_schema(db)
        db.commit()
        self.assertEqual(self.table_rows(db, v10_tables, columns), before)
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(
            set(self.user_tables(db)) - set(v10_tables),
            MIRROR_TABLES | EXTENSION_TABLES | POWER_CURVE_TABLES,
        )
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM food_database_entries").fetchone()[0], 0
        )
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_failed_v10_upgrade_rolls_back_to_the_unchanged_v10_database(self):
        db = self.populated_v10_database(self.connect())
        before = list(db.iterdump())

        def failing_step(connection):
            execute_ddl(connection, FOOD_DATABASE_DDL)
            raise RuntimeError("injected migration failure")

        with (
            mock.patch.dict(
                migrations.UPGRADE_STEPS,
                {SHAPE_SCHEMA_V10: (SHAPE_CURRENT, failing_step)},
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 10)

    def test_upgraded_v10_database_restarts_with_the_same_build_unchanged(self):
        db = self.populated_v10_database(self.connect())
        migrate_schema(db)
        db.commit()
        upgraded = list(db.iterdump())
        migrate_schema(db)
        self.assertEqual(list(db.iterdump()), upgraded)

    GARMIN_BLOB: ClassVar[dict[str, Any]] = {
        "synced_at": "2026-10-20T06:00:00+00:00",
        "start": "2026-10-01",
        "end": "2026-10-20",
        "source_freshness": {
            "sleep": {"fetched_at": "2026-10-20T06:00:00+00:00", "freshness": "current"}
        },
        "provider_sync": {"read_window": {"start": "2026-10-01", "end": "2026-10-20"}},
        "sport_max_hr": {"run": 190},
        "sleep": [
            {"calendarDate": "2026-10-19", "sleepScore": 80},
            {"calendarDate": "2026-10-20", "sleepScore": 84},
            {"sleepScore": 70},
        ],
        "max_metrics": {"vo2MaxRunning": 52.0},
        "performance_history": [{"date": "2026-10-20", "metrics": {"x": 1}}],
        "activities": [
            {
                "activityId": 4001,
                "startTimeLocal": "2026-10-20 07:00:00",
                "activityName": "Morning run",
                "authToken": "never-stored",
            },
            {"activityId": "bad id!", "startTimeLocal": "2026-10-20 08:00:00"},
        ],
        "empty_section": [],
    }

    def populated_v11_database(self, db, blob=None):
        db.executescript(V11_FIXTURE.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES ('garmin_snapshot', ?, ?)",
            (json.dumps(self.GARMIN_BLOB if blob is None else blob), STAMP),
        )
        db.execute(
            "INSERT INTO provider_records(provider, record_kind, source_record_id, "
            "payload, payload_hash, fetched_at, mapped_version, state, created_at, "
            "updated_at) VALUES ('garmin', 'health', 'sleep', ?, ?, ?, 9, "
            "'active', ?, ?)",
            (
                json.dumps({"sleep": self.GARMIN_BLOB["sleep"]}),
                "0" * 64,
                STAMP,
                STAMP,
                STAMP,
            ),
        )
        db.commit()
        return db

    def garmin_rows(self, db, kind):
        return {
            row["source_record_id"]: row
            for row in db.execute(
                "SELECT * FROM provider_records WHERE provider = 'garmin' "
                "AND record_kind = ?",
                (kind,),
            )
        }

    def test_frozen_v11_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V11_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V11
        )

    def test_populated_v11_upgrade_splits_the_garmin_snapshot_into_rows(self):
        db = self.populated_v11_database(self.connect())
        messages = self.table_rows(db, ["messages"])
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(self.table_rows(db, ["messages"]), messages)
        health = self.garmin_rows(db, "health")
        self.assertNotIn("sleep", health)
        self.assertEqual(
            {name.split("/")[0] for name in health},
            {"sleep", "max_metrics", "performance_history"},
        )
        sleep = {n: r for n, r in health.items() if n.startswith("sleep/")}
        self.assertEqual(len(sleep), 3)
        self.assertEqual(sleep["sleep/2026-10-19"]["observed_on"], "2026-10-19")
        self.assertEqual(sleep["sleep/2026-10-19"]["mapped_version"], 0)
        self.assertEqual(sleep["sleep/2026-10-19"]["fetched_at"], STAMP)
        self.assertEqual(health["max_metrics"]["observed_on"], None)
        self.assertEqual(
            garmin_store.read_sections(db, ["sleep", "max_metrics"]),
            {
                "sleep": [
                    {"calendarDate": "2026-10-19", "sleepScore": 80},
                    {"calendarDate": "2026-10-20", "sleepScore": 84},
                    {"sleepScore": 70},
                ],
                "max_metrics": {"vo2MaxRunning": 52.0},
            },
        )
        self.assertEqual(
            garmin_store.read_sections(db, ["sleep"], start="2026-10-20"),
            {
                "sleep": [
                    {"calendarDate": "2026-10-20", "sleepScore": 84},
                    {"sleepScore": 70},
                ]
            },
        )
        state = garmin_store.read_state(db)
        self.assertEqual(state["sport_max_hr"], {"run": 190})
        self.assertEqual(state["synced_at"], self.GARMIN_BLOB["synced_at"])
        self.assertNotIn("sleep", state)
        self.assertNotIn("activities", state)
        activities = self.garmin_rows(db, "activity")
        self.assertEqual(set(activities), {"4001"})
        self.assertEqual(activities["4001"]["observed_on"], "2026-10-20")
        self.assertNotIn("authToken", activities["4001"]["payload"])
        kv = {
            row["key"]: row["value"]
            for row in db.execute("SELECT key, value FROM kv WHERE key LIKE 'garmin%'")
        }
        self.assertNotIn("garmin_snapshot", kv)
        self.assertEqual(json.loads(kv["garmin_snapshot_legacy"]), self.GARMIN_BLOB)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_v11_upgrade_without_a_garmin_snapshot_only_adds_the_day_column(self):
        db = self.populated_v11_database(self.connect(), blob={})
        db.execute("DELETE FROM kv WHERE key = 'garmin_snapshot'")
        db.execute("DELETE FROM provider_records")
        db.commit()
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0], 0
        )

    def test_failed_v11_upgrade_rolls_back_to_the_unchanged_v11_database(self):
        db = self.populated_v11_database(self.connect())
        before = list(db.iterdump())
        with (
            mock.patch.object(
                migrations,
                "split_garmin_snapshot",
                side_effect=RuntimeError("injected"),
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 11)

    def test_v11_upgrade_that_cannot_read_every_element_back_is_rolled_back(self):
        db = self.populated_v11_database(self.connect())
        before = list(db.iterdump())
        with (
            mock.patch.object(
                garmin_items_migration.garmin_store, "iter_items", return_value=iter(())
            ),
            self.assertRaises(RuntimeError),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)

    def test_upgraded_v11_database_restarts_with_the_same_build_unchanged(self):
        db = self.populated_v11_database(self.connect())
        migrate_schema(db)
        db.commit()
        upgraded = list(db.iterdump())
        migrate_schema(db)
        self.assertEqual(list(db.iterdump()), upgraded)

    def populated_v12_database(self, db):
        db.executescript(V12_FIXTURE.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, started_at, created_at, updated_at) "
            "VALUES ('act_1', ?, 'i1', ?, ?, ?)",
            (INTERVALS, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, "
            "activity_id, mapper_version, source_kind, recorded_by, sport, "
            "environment, started_at, load_model, fetched_at, created_at, "
            "updated_at) VALUES (?, 'i1', 'act_1', 1, 'device_measured', "
            "'intervals', 'ride', 'outdoor', ?, 'none', ?, ?, ?)",
            (INTERVALS, STAMP, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_detail_sets(provider, provider_activity_id, "
            "detail_kind, mapper_version, origin, source_kind, recorded_by, "
            "lap_source, content_sha256, fetched_at, created_at, updated_at) "
            "VALUES (?, 'i1', 'laps', 1, 'fetch', 'device_measured', 'intervals', "
            "'device_laps', ?, ?, ?, ?)",
            (INTERVALS, "0" * 64, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_laps(provider, provider_activity_id, lap_index, "
            "kind, start_offset_s, end_offset_s, avg_speed_mps, intensity_pct) "
            "VALUES (?, 'i1', 0, 'work', 0, 600, 8.5, 80)",
            (INTERVALS,),
        )
        db.commit()
        return db

    def test_frozen_v12_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V12_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V12
        )

    def test_populated_v12_upgrade_keeps_every_row_and_adds_an_empty_lap_max_speed(
        self,
    ):
        db = self.populated_v12_database(self.connect())
        tables = self.user_tables(db)
        columns = self.table_columns(db, tables)
        before = self.table_rows(db, tables, columns)
        migrate_schema(db)
        db.commit()
        self.assertEqual(self.table_rows(db, tables, columns), before)
        lap = db.execute("SELECT * FROM activity_laps").fetchone()
        self.assertIsNone(lap["max_speed_mps"])
        self.assertEqual(lap["intensity_pct"], 80)
        self.assertEqual(
            set(self.user_tables(db)) - set(tables),
            EXTENSION_TABLES | POWER_CURVE_TABLES,
        )
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_v12_upgrade_works_with_the_application_row_factory(self):
        # The application reads rows as plain mappings without positional access.
        db = self.populated_v12_database(self.connect())
        db.row_factory = row_factory
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assertIsNone(
            db.execute("SELECT max_speed_mps FROM activity_laps").fetchone()[
                "max_speed_mps"
            ]
        )

    def test_failed_v12_upgrade_rolls_back_to_the_unchanged_v12_database(self):
        db = self.populated_v12_database(self.connect())
        before = list(db.iterdump())

        def failing_step(connection):
            connection.execute(
                "ALTER TABLE activity_laps ADD COLUMN max_speed_mps REAL"
            )
            raise RuntimeError("injected migration failure")

        with (
            mock.patch.dict(
                migrations.UPGRADE_STEPS,
                {SHAPE_SCHEMA_V12: (SHAPE_CURRENT, failing_step)},
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 12)

    def test_upgraded_v12_database_restarts_with_the_same_build_unchanged(self):
        db = self.populated_v12_database(self.connect())
        migrate_schema(db)
        db.commit()
        upgraded = list(db.iterdump())
        migrate_schema(db)
        self.assertEqual(list(db.iterdump()), upgraded)

    # (activity_id, primary provider, provider activity id, state, merged_into)
    V13_SESSIONS: ClassVar[tuple[tuple[str, str, str, str, str | None], ...]] = (
        ("act_1", INTERVALS, "i1", "active", None),
        ("act_2", GARMIN, "g2", "active", None),
        ("act_3", INTERVALS, "shared", "active", None),
        ("act_4", GARMIN, "shared", "active", None),
        ("act_5", INTERVALS, "pair", "active", None),
        ("act_6", GARMIN, "pair", "active", None),
        ("act_7", GARMIN, "g7", "duplicate", "act_1"),
        ("act_8", INTERVALS, "i8", "deleted", None),
        ("act_9", GARMIN, "g9", "active", None),
    )
    # Feedback before schema version 15 names its activity by a provider id, or by
    # the local session id; (activity_id, provider) -> the session_id it must get.
    V13_FEEDBACK_SESSIONS: ClassVar[dict[tuple[str, str | None], str | None]] = {
        ("act_2", None): "act_2",
        ("i1", INTERVALS): "act_1",
        ("g9", None): "act_9",
        ("pair", GARMIN): "act_6",
        # The session the feedback was written for, not the merge survivor.
        ("g7", None): "act_7",
        ("i8", None): "act_8",
        # Ambiguous, provider mismatch, record without session, unmatched.
        ("shared", None): None,
        ("g2", INTERVALS): None,
        ("orphan", None): None,
        ("missing", None): None,
        ("act_99", None): None,
    }
    LONG_NOTE: ClassVar[str] = ("Beine schwer, Puls ruhig. " * 160)[:4000]

    def populated_v13_database(self, db, fixture=V13_FIXTURE):
        """A populated v13 database; with ``V14_FIXTURE`` the same rows in v14."""
        db.executescript(fixture.read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES ('garmin_sync', '{}', ?)",
            (STAMP,),
        )
        records = [(INTERVALS, "orphan", None, "active")]
        for activity_id, provider, provider_id, state, merged in self.V13_SESSIONS:
            db.execute(
                "INSERT INTO activity_sessions(activity_id, primary_provider, "
                "primary_provider_activity_id, state, merged_into, started_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    activity_id,
                    provider,
                    provider_id,
                    state,
                    merged,
                    STAMP,
                    STAMP,
                    STAMP,
                ),
            )
            record_state = "deleted" if state == "deleted" else "active"
            records.append((provider, provider_id, activity_id, record_state))
        for provider, provider_id, activity_id, state in records:
            db.execute(
                "INSERT INTO activity_records(provider, provider_activity_id, "
                "activity_id, state, mapper_version, source_kind, recorded_by, sport, "
                "environment, started_at, load_model, fetched_at, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, 1, 'device_measured', ?, 'run', "
                "'outdoor', ?, 'none', ?, ?, ?)",
                (provider, provider_id, activity_id, state, provider, STAMP, STAMP)
                + (STAMP, STAMP),
            )
        for activity_id, provider in self.V13_FEEDBACK_SESSIONS:
            db.execute(
                "INSERT INTO activity_feedback(activity_id, activity_name, "
                "activity_date, notes, session_rpe, deviation_reason, created_at, "
                "updated_at, provider) VALUES (?, 'Lauf', '2026-10-16', ?, 6, "
                "'krank', ?, '2026-10-17T08:00:00+00:00', ?)",
                (activity_id, self.LONG_NOTE, STAMP, provider),
            )
        # A provider value and the FORM that this release derived from CTL and ATL.
        for key, metric, value, source_kind in (
            ("intervals|ctl|||2026-10-16", "ctl", 60.0, "provider_reported"),
            ("intervals|form|||2026-10-16", "form", -5.0, "derived"),
        ):
            db.execute(
                "INSERT INTO observations(natural_key, metric, value, unit, "
                "source_kind, recorded_by, provider, source_record_id, observed_on, "
                "mapper_version, created_at, updated_at) VALUES (?, ?, ?, 'load', ?, "
                "'intervals', 'intervals', '2026-10-16', '2026-10-16', 6, ?, ?)",
                (key, metric, value, source_kind, STAMP, STAMP),
            )
        db.execute(
            "INSERT INTO provider_records(provider, record_kind, source_record_id, "
            "payload, payload_hash, fetched_at, mapped_version, state, created_at, "
            "updated_at, observed_on) VALUES ('garmin', 'health', 'sleep/2026-10-16', "
            "'{\"sleepScore\": 80}', ?, ?, 1, 'active', ?, ?, '2026-10-16')",
            ("0" * 64, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_detail_sets(provider, provider_activity_id, "
            "detail_kind, mapper_version, origin, source_kind, recorded_by, "
            "lap_source, content_sha256, fetched_at, created_at, updated_at) "
            "VALUES (?, 'i1', 'laps', 1, 'fetch', 'device_measured', 'intervals', "
            "'device_laps', ?, ?, ?, ?)",
            (INTERVALS, "0" * 64, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_laps(provider, provider_activity_id, lap_index, "
            "kind, start_offset_s, end_offset_s, avg_speed_mps, max_speed_mps, "
            "intensity_pct) VALUES (?, 'i1', 0, 'work', 0, 600, 3.5, 4.2, 80)",
            (INTERVALS,),
        )
        db.execute(
            "INSERT INTO food_database_entries(food_id, barcode, name, payload, "
            "fetched_at, updated_at) VALUES ('off:4001', '4001', 'Skyr', '{}', ?, ?)",
            (STAMP, STAMP),
        )
        db.commit()
        return db

    def feedback_sessions(self, db):
        return {
            (row["activity_id"], row["provider"]): row["session_id"]
            for row in db.execute(
                "SELECT activity_id, provider, session_id FROM activity_feedback"
            )
        }

    def test_frozen_v17_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V17_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V17
        )

    def test_frozen_v16_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V16_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V16
        )

    def test_frozen_v15_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V15_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V15
        )

    def test_frozen_v14_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V14_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V14
        )

    def test_frozen_v13_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V13_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V13
        )

    def test_populated_v13_upgrade_links_feedback_only_to_its_unique_session(self):
        for fixture in (V13_FIXTURE, V14_FIXTURE):
            with self.subTest(fixture=fixture.name):
                self.assert_feedback_upgrade(
                    self.populated_v13_database(self.connect(), fixture)
                )

    def assert_feedback_upgrade(self, db):
        tables = self.user_tables(db)
        columns = self.table_columns(db, tables)
        before = self.table_rows(db, tables, columns)
        migrate_schema(db)
        db.commit()
        self.assertEqual(self.table_rows(db, tables, columns), before)
        self.assertEqual(self.feedback_sessions(db), self.V13_FEEDBACK_SESSIONS)
        self.assertEqual(len(self.LONG_NOTE), 4000)
        self.assertEqual(
            {row[0] for row in db.execute("SELECT notes FROM activity_feedback")},
            {self.LONG_NOTE},
        )
        self.assertEqual(
            db.execute(
                "SELECT COUNT(*) FROM activity_sessions "
                "WHERE merged_into_retained IS NOT NULL"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            set(self.user_tables(db)) - set(tables),
            EXTENSION_TABLES | POWER_CURVE_TABLES,
        )
        for table in sorted(EXTENSION_TABLES | POWER_CURVE_TABLES):
            with self.subTest(table=table):
                self.assertEqual(
                    db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_failed_v13_upgrade_after_the_feedback_backfill_rolls_back(self):
        for fixture, version in ((V13_FIXTURE, 13), (V14_FIXTURE, 14)):
            with self.subTest(fixture=fixture.name):
                self.assert_failed_feedback_upgrade(
                    self.populated_v13_database(self.connect(), fixture), version
                )

    def assert_failed_feedback_upgrade(self, db, version):
        before = list(db.iterdump())
        linked = []

        def failing_step(connection):
            migrations._upgrade_v14_to_v15(connection)
            linked.append(
                connection.execute(
                    "SELECT COUNT(*) FROM activity_feedback "
                    "WHERE session_id IS NOT NULL"
                ).fetchone()[0]
            )
            raise RuntimeError("injected migration failure")

        with (
            mock.patch.dict(
                migrations.UPGRADE_STEPS,
                {SHAPE_SCHEMA_V14: (SHAPE_CURRENT, failing_step)},
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(linked, [6])
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], version)

    def test_upgraded_v13_database_restarts_with_the_same_build_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "upgrade.db"
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            try:
                self.populated_v13_database(db)
                migrate_schema(db)
                db.commit()
                upgraded = list(db.iterdump())
            finally:
                db.close()
            reopened = sqlite3.connect(path)
            reopened.row_factory = sqlite3.Row
            try:
                migrate_schema(reopened)
                self.assertEqual(list(reopened.iterdump()), upgraded)
                self.assertEqual(
                    self.feedback_sessions(reopened), self.V13_FEEDBACK_SESSIONS
                )
            finally:
                reopened.close()

    def test_v13_version_and_shape_must_belong_together(self):
        released = self.populated_v13_database(self.connect())
        released.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        released.commit()
        self.assert_rejected_unchanged(released)
        current = self.current_database()
        current.execute("PRAGMA user_version = 13")
        current.commit()
        self.assert_rejected_unchanged(current)
        older = self.populated_v12_database(self.connect())
        older.execute("PRAGMA user_version = 13")
        older.commit()
        self.assert_rejected_unchanged(older)

    def test_every_released_schema_upgrades_to_the_frozen_current_signature(self):
        frozen = self.connect()
        frozen.executescript(CURRENT_FIXTURE.read_text(encoding="utf-8"))
        live = self.connect()
        initialize_schema(live)
        expected = database_schema_signature(live)
        self.assertEqual(database_schema_signature(frozen), expected)
        for fixture in RELEASED_FIXTURES:
            with self.subTest(fixture=fixture.name):
                db = self.connect()
                db.executescript(fixture.read_text(encoding="utf-8"))
                migrate_schema(db)
                db.commit()
                self.assertEqual(database_schema_signature(db), expected)

    def test_failed_upgrade_step_rolls_back_to_the_unchanged_v9_database(self):
        db = self.connect()
        self.populated_v9_database(db)
        before = list(db.iterdump())

        def failing_step(connection):
            execute_ddl(connection, ACTIVITY_DETAIL_DDL)
            raise RuntimeError("injected migration failure")

        steps = {SHAPE_SCHEMA_V9: (SHAPE_CURRENT, failing_step)}
        with (
            mock.patch.dict(migrations.UPGRADE_STEPS, steps),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], OLDEST_SUPPORTED_VERSION
        )

    def test_lost_savepoint_does_not_mask_the_original_upgrade_error(self):
        # The step ends the transaction or drops the savepoint, as an engine
        # error can, before it fails; cleanup must keep the original error.
        for statement in ("ROLLBACK", "RELEASE schema_migration"):
            with self.subTest(statement=statement):
                db = self.connect()
                self.populated_v9_database(db)
                before = list(db.iterdump())

                def failing_step(connection, statement=statement):
                    execute_ddl(connection, ACTIVITY_DETAIL_DDL)
                    connection.execute(statement)
                    raise RuntimeError("injected migration failure")

                steps = {SHAPE_SCHEMA_V9: (SHAPE_CURRENT, failing_step)}
                with (
                    mock.patch.dict(migrations.UPGRADE_STEPS, steps),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)

    def test_upgraded_database_restarts_with_the_same_build_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "upgrade.db"
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            try:
                self.populated_v9_database(db)
                migrate_schema(db)
                db.commit()
                upgraded = list(db.iterdump())
            finally:
                db.close()
            reopened = sqlite3.connect(path)
            reopened.row_factory = sqlite3.Row
            try:
                migrate_schema(reopened)
                self.assertEqual(list(reopened.iterdump()), upgraded)
                self.assertEqual(
                    reopened.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
            finally:
                reopened.close()

    def test_version_and_shape_must_belong_together(self):
        current = self.current_database()
        current.execute(f"PRAGMA user_version = {OLDEST_SUPPORTED_VERSION}")
        current.commit()
        self.assert_rejected_unchanged(current)
        released = self.connect()
        self.populated_v9_database(released)
        released.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        released.commit()
        self.assert_rejected_unchanged(released)

    def test_frozen_current_schema_fixture_matches_the_live_schema(self):
        # When the schema changes again, move this fixture's digest into
        # backend.db.schema_history and add an upgrade step before refreezing.
        frozen = self.connect()
        frozen.executescript(CURRENT_FIXTURE.read_text(encoding="utf-8"))
        live = self.connect()
        initialize_schema(live)
        self.assertEqual(
            database_schema_signature(frozen), database_schema_signature(live)
        )
        self.assertEqual(
            frozen.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )

    @unittest.skipIf(
        cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
    )
    def test_encrypted_current_database_reopens_with_same_key(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "encrypted.db"
            options = {
                "password": "synthetic-migration-test-key",
                "configure": configure_cipher,
                "row_factory": cipher_backend.Row,
            }
            manager = DatabaseManager(path, cipher_backend, **options)
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                    migrate_schema(db)
            finally:
                manager.close()
            reopened = DatabaseManager(path, cipher_backend, **options)
            try:
                with reopened.unit_of_work() as db:
                    migrate_schema(db)
                    self.assertTrue(database_schema_is_current(db))
                    self.assertEqual(
                        db.execute("PRAGMA cipher_integrity_check").fetchall(), []
                    )
            finally:
                reopened.close()
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")


if __name__ == "__main__":
    unittest.main()
