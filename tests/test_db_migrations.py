"""Schema gate: supported released schemas upgrade, anything else stays unchanged."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from backend.canonical.vocabulary import ProviderId
from backend.db import migrations
from backend.db.bootstrap import initialize_application_database
from backend.db.manager import DatabaseManager
from backend.db.migrations import OlderSchemaError, migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
    database_schema_signature,
    initialize_schema,
)
from backend.db.schema_history import (
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V21,
    SHAPE_SCHEMA_V22,
    SHAPE_SCHEMA_V23,
    released_shape,
)

INTERVALS = ProviderId.INTERVALS.value
STAMP = "2026-10-16T08:00:00+00:00"
OLDEST_SUPPORTED_VERSION = 21
FIXTURES = Path(__file__).with_name("fixtures")
# Schema v21, releases 1.13.41 to 1.13.44: the oldest supported schema.
V21_FIXTURE = FIXTURES / "schema_v21.sql.txt"
# Schema version 22, release 2.0.0 candidate: executed strength sets.
V22_FIXTURE = FIXTURES / "schema_v22.sql.txt"
# Schema version 23: the athlete's session purpose marking.
V23_FIXTURE = FIXTURES / "schema_v23.sql.txt"
OLDEST_SUPPORTED_FIXTURE = V21_FIXTURE
RELEASED_FIXTURES = (V21_FIXTURE, V22_FIXTURE, V23_FIXTURE)
CURRENT_FIXTURE = FIXTURES / f"schema_v{CURRENT_SCHEMA_VERSION}.sql.txt"

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
        # Release 1.13.44 is the migration baseline.
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
        for version in (0, 1, OLDEST_SUPPORTED_VERSION - 1, CURRENT_SCHEMA_VERSION + 1):
            with self.subTest(version=version):
                db = self.current_database()
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                self.assert_rejected_unchanged(db)

    def test_older_database_file_is_refused_at_startup_without_changes(self):
        # A release before 1.13.41 wrote a schema below 21: startup names the
        # release to upgrade with first and leaves every row and the version.
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "older.db"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(V21_FIXTURE.read_text(encoding="utf-8"))
                db.execute(
                    "INSERT INTO messages(role, content, created_at) "
                    "VALUES ('user', 'Hallo', ?)",
                    (STAMP,),
                )
                db.execute(f"PRAGMA user_version = {OLDEST_SUPPORTED_VERSION - 1}")
                db.commit()
                before = list(db.iterdump())
            manager = DatabaseManager(path, sqlite3, row_factory=sqlite3.Row)
            try:
                with (
                    self.assertRaisesRegex(OlderSchemaError, "Release 1.13.44"),
                    manager.unit_of_work() as db,
                ):
                    initialize_application_database(
                        db,
                        key_values=KeyValueRepository(lambda: STAMP),
                        now=STAMP,
                        current_time=datetime.now(UTC),
                        default_profile_json="{}",
                        provider_resync_keys=(),
                        retention_days=-1,
                    )
            finally:
                manager.close()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    OLDEST_SUPPORTED_VERSION - 1,
                )

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
            selected = (
                ", ".join(f'"{name}"' for name in columns[table]) if columns else "*"
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

    def test_frozen_v21_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V21_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V21
        )

    def test_frozen_v22_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V22_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V22
        )

    def test_frozen_v23_fixture_is_the_recorded_released_shape(self):
        db = self.connect()
        db.executescript(V23_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V23
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
                db.executescript(V21_FIXTURE.read_text(encoding="utf-8"))
                before = list(db.iterdump())

                def failing_step(connection, statement=statement):
                    connection.execute("CREATE TABLE migration_probe(value TEXT)")
                    connection.execute(statement)
                    raise RuntimeError("injected migration failure")

                steps = {SHAPE_SCHEMA_V21: (SHAPE_CURRENT, failing_step)}
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
                db.executescript(V21_FIXTURE.read_text(encoding="utf-8"))
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
        released.executescript(V21_FIXTURE.read_text(encoding="utf-8"))
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
