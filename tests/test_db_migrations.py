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
    released_shape,
)

INTERVALS = ProviderId.INTERVALS.value
STAMP = "2026-10-16T08:00:00+00:00"
OLDEST_SUPPORTED_VERSION = 9
FIXTURES = Path(__file__).with_name("fixtures")
OLDEST_SUPPORTED_FIXTURE = FIXTURES / "schema_v9.sql.txt"
V10_FIXTURE = FIXTURES / "schema_v10.sql.txt"
V11_FIXTURE = FIXTURES / "schema_v11.sql.txt"
V12_FIXTURE = FIXTURES / "schema_v12.sql.txt"
CURRENT_FIXTURE = FIXTURES / f"schema_v{CURRENT_SCHEMA_VERSION}.sql.txt"
DETAIL_TABLES = {
    "activity_detail_sets",
    "activity_stream_channels",
    "activity_laps",
    "activity_zone_times",
    "activity_detail_analysis",
}
MIRROR_TABLES = {"food_database_entries"}

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

    def table_rows(self, db, tables):
        return {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]
            for table in tables
        }

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
        before = self.table_rows(db, v9_tables)
        migrate_schema(db)
        db.commit()
        self.assertEqual(self.table_rows(db, v9_tables), before)
        self.assertTrue(database_schema_is_current(db))
        for table in sorted(set(self.user_tables(db)) - set(v9_tables)):
            with self.subTest(table=table):
                self.assertIn(table, DETAIL_TABLES | MIRROR_TABLES)
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
        before = self.table_rows(db, v10_tables)
        migrate_schema(db)
        db.commit()
        self.assertEqual(self.table_rows(db, v10_tables), before)
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(set(self.user_tables(db)) - set(v10_tables), MIRROR_TABLES)
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
        lap_columns = "provider, provider_activity_id, lap_index, kind, avg_speed_mps"
        before = self.table_rows(db, [t for t in tables if t != "activity_laps"])
        laps_before = db.execute(f"SELECT {lap_columns} FROM activity_laps").fetchall()
        migrate_schema(db)
        db.commit()
        self.assertEqual(
            self.table_rows(db, [t for t in tables if t != "activity_laps"]), before
        )
        self.assertEqual(
            db.execute(f"SELECT {lap_columns} FROM activity_laps").fetchall(),
            laps_before,
        )
        lap = db.execute("SELECT * FROM activity_laps").fetchone()
        self.assertIsNone(lap["max_speed_mps"])
        self.assertEqual(lap["intensity_pct"], 80)
        self.assertEqual(self.user_tables(db), tables)
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
