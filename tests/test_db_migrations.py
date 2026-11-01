"""Schema gate: supported released schemas upgrade, anything else stays unchanged."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from backend.canonical.vocabulary import ProviderId
from backend.db import migrations
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
    database_schema_signature,
    initialize_schema,
)
from backend.db.schema_history import (
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V16,
    SHAPE_SCHEMA_V17,
    released_shape,
)

INTERVALS = ProviderId.INTERVALS.value
GARMIN = ProviderId.GARMIN.value
STAMP = "2026-10-16T08:00:00+00:00"
OLDEST_SUPPORTED_VERSION = 16
FIXTURES = Path(__file__).with_name("fixtures")
V9_FIXTURE = FIXTURES / "schema_v9.sql.txt"
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
OLDEST_SUPPORTED_FIXTURE = V16_FIXTURE
# Release schema 17: power curve; version 18 adds the session RPE rating time.
V17_FIXTURE = FIXTURES / "schema_v17.sql.txt"
RELEASED_FIXTURES = (
    V16_FIXTURE,
    FIXTURES / "schema_v17.sql.txt",
    FIXTURES / "schema_v18.sql.txt",
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
        # Release 1.13.32 is the migration baseline.
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

    def test_lost_savepoint_does_not_mask_the_original_upgrade_error(self):
        # The step ends the transaction or drops the savepoint, as an engine
        # error can, before it fails; cleanup must keep the original error.
        for statement in ("ROLLBACK", "RELEASE schema_migration"):
            with self.subTest(statement=statement):
                db = self.connect()
                db.executescript(V16_FIXTURE.read_text(encoding="utf-8"))
                before = list(db.iterdump())

                def failing_step(connection, statement=statement):
                    connection.execute("CREATE TABLE migration_probe(value TEXT)")
                    connection.execute(statement)
                    raise RuntimeError("injected migration failure")

                steps = {SHAPE_SCHEMA_V16: (SHAPE_CURRENT, failing_step)}
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
                db.executescript(V16_FIXTURE.read_text(encoding="utf-8"))
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
        released.executescript(V16_FIXTURE.read_text(encoding="utf-8"))
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
