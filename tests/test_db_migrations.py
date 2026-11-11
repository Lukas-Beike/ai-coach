"""Schema gate: the production baseline reaches the live schema; all else stays unchanged."""

import json
import sqlite3
import tempfile
import unittest
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from support import temp_database

from backend.canonical.vocabulary import ProviderId
from backend.db import migrations, schema_history
from backend.db.bootstrap import initialize_application_database
from backend.db.migrations import OlderSchemaError, migrate_schema
from backend.db.repositories import FoodDatabaseEntryRepository, KeyValueRepository
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    SYNC_JOBS_BACKFILL_INDEX_DDL,
    configure_cipher,
    database_schema_is_current,
    database_schema_signature,
    execute_ddl,
    initialize_schema,
)
from backend.db.schema_history import (
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V26,
    released_shape,
    signature_digest,
)

INTERVALS = ProviderId.INTERVALS.value
STAMP = "2026-10-16T08:00:00+00:00"
# Schema v26, release 2.0.5: the schema production runs and the only baseline.
OLDEST_SUPPORTED_VERSION = 26
BASELINE_FIXTURE = Path(__file__).with_name("fixtures") / "schema_v26.sql.txt"
# No released schema precedes the baseline, so the upgrade path runs on a
# stand-in: the live schema one index short, stored with the previous version.
PREVIOUS_SHAPE = "synthetic-previous"
PREVIOUS_VERSION = CURRENT_SCHEMA_VERSION - 1


def previous_shape_database(db) -> None:
    """Store the live schema without the backfill index as the previous version."""
    initialize_schema(db)
    db.execute("DROP INDEX idx_sync_jobs_backfill_end")
    db.execute(f"PRAGMA user_version = {PREVIOUS_VERSION}")
    db.commit()


def add_index_step(db) -> None:
    execute_ddl(db, SYNC_JOBS_BACKFILL_INDEX_DDL)


@contextmanager
def registered_previous_shape(
    db, step: Callable[..., None] = add_index_step
) -> Iterator[None]:
    """Make the stand-in shape of ``db`` the baseline, one step below the live schema."""
    digest = signature_digest(database_schema_signature(db))
    with (
        mock.patch.object(
            migrations, "OLDEST_SUPPORTED_SCHEMA_VERSION", PREVIOUS_VERSION
        ),
        mock.patch.dict(
            schema_history.RELEASED_SHAPE_DIGESTS, {PREVIOUS_SHAPE: digest}
        ),
        mock.patch.dict(
            schema_history.ACCEPTED_SHAPES_BY_VERSION,
            {PREVIOUS_VERSION: frozenset({PREVIOUS_SHAPE})},
        ),
        mock.patch.dict(
            migrations.UPGRADE_STEPS, {PREVIOUS_SHAPE: (SHAPE_CURRENT, step)}
        ),
    ):
        yield


EAN_OWN, EAN_OTHER = "4006381333931", "4000000000017"
YAZIO_ID = "yazio:0f0f0f0f-0000-4000-8000-000000000001"
OWN_FOOD_ID = "off:4000000000024"
NUTRIENTS = ("kcal", "carbs_g", "protein_g", "fat_g", "sugar_g", "fiber_g", "salt_g")


def mirror_food(food_id: str, unit: str | None, **per_100: float | None) -> dict:
    return {
        "id": food_id,
        "name": "Riegel " + food_id,
        "brands": "Marke",
        "source": "Open Food Facts",
        "source_url": "https://example.test/" + food_id,
        "license": "ODbL",
        "basis_amount": 100,
        "basis_unit": unit,
        "per_100": per_100,
        "quality": "community_label_data",
    }


# Mirrored foods of the baseline: (food, barcode column, fetched_at).
BASELINE_MIRROR = (
    # Newest food with the own product's EAN: fills its empty fields first.
    (
        mirror_food(f"off:{EAN_OWN}", "g", **dict.fromkeys(NUTRIENTS, 1.0)),
        EAN_OWN,
        "2026-10-03",
    ),
    # Older food with the same EAN from Yazio: takes only what is still empty.
    (mirror_food(YAZIO_ID, "g", fiber_g=7.0), EAN_OWN, "2026-10-02"),
    # Unknown unit and a payload from before sugar, fibre and salt were read.
    (
        mirror_food(
            f"off:{EAN_OTHER}", None, kcal=80.0, carbs_g=None, protein_g=2.0, fat_g=1.0
        ),
        EAN_OTHER,
        "2026-10-01",
    ),
    # A food without brand and source page keeps both absent.
    (
        {
            **{
                key: value
                for key, value in mirror_food(
                    YAZIO_ID.replace("1", "2"), "ml", **dict.fromkeys(NUTRIENTS)
                ).items()
                if key != "source_url"
            },
            "brands": None,
        },
        "",
        "2026-10-01",
    ),
    # An own product already holds this food's id: it wins and keeps its row.
    (mirror_food(OWN_FOOD_ID, "g", kcal=99.0), OWN_FOOD_ID[4:], "2026-10-01"),
)


def add_baseline_nutrition_rows(db) -> None:
    """An own product with gaps and mirrored foods of the v26 baseline."""
    db.execute(
        "INSERT INTO nutrition_products(id, barcode, name, brand, basis_amount, "
        "basis_unit, kcal, fat_g, source, created_at, updated_at, favorite) "
        "VALUES ('prod-own', ?, 'Mein Riegel', '', 100, 'g', 500, 30, "
        "'packaging_label', ?, ?, 1)",
        (EAN_OWN, STAMP, STAMP),
    )
    db.execute(
        "INSERT INTO nutrition_products(id, name, basis_amount, basis_unit, source, "
        "created_at, updated_at) VALUES (?, 'Eigenes', 100, 'g', 'manual', ?, ?)",
        (OWN_FOOD_ID, STAMP, STAMP),
    )
    db.executemany(
        "INSERT INTO food_database_entries(food_id, barcode, name, brand, payload, "
        "fetched_at, updated_at) VALUES (?, ?, ?, 'Marke', ?, ?, ?)",
        [
            (food["id"], barcode, food["name"], json.dumps(food), fetched, fetched)
            for food, barcode, fetched in BASELINE_MIRROR
        ],
    )


def populated_baseline_database(db) -> None:
    db.executescript(BASELINE_FIXTURE.read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO messages(role, content, created_at) VALUES ('user', 'Hallo', ?)",
        (STAMP,),
    )
    add_baseline_nutrition_rows(db)
    db.commit()


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

    def test_populated_baseline_reaches_the_live_schema_with_its_rows(self):
        db = self.connect()
        populated_baseline_database(db)
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], OLDEST_SUPPORTED_VERSION
        )
        migrate_schema(db)
        db.commit()
        live = self.connect()
        initialize_schema(live)
        self.assertEqual(database_schema_signature(db), database_schema_signature(live))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("SELECT content FROM messages").fetchone()[0], "Hallo"
        )

    def test_baseline_mirror_rows_become_canonical_products_without_loss(self):
        db = self.connect()
        populated_baseline_database(db)
        migrate_schema(db)
        db.commit()
        own = db.execute(
            "SELECT * FROM nutrition_products WHERE origin = 'own' ORDER BY id DESC"
        ).fetchall()
        self.assertEqual([row["id"] for row in own], ["prod-own", OWN_FOOD_ID])
        self.assertEqual((own[1]["kcal"], own[1]["name"]), (99.0, "Eigenes"))
        self.assertEqual(
            [own[0][key] for key in ("id", "barcode", "brand", "favorite", *NUTRIENTS)],
            ["prod-own", EAN_OWN, "Marke", 1, 500, 1.0, 1.0, 30, 1.0, 1.0, 1.0],
        )
        self.assertEqual(
            set(json.loads(own[0]["details"])["filled_fields"]),
            {"brand", "carbs_g", "protein_g", "sugar_g", "fiber_g", "salt_g"},
        )
        entries = FoodDatabaseEntryRepository()
        # Every mirrored food stays stored with all its fields; the own
        # product's EAN lists none of them as a separate entry.
        for food, barcode, fetched in BASELINE_MIRROR[:-1]:
            with self.subTest(food=food["id"]):
                stored = entries.get(db, food["id"])
                self.assertEqual(stored.pop("fetched_at"), fetched)
                expected = dict(food)
                if barcode and food["id"].startswith("yazio:"):
                    expected["barcode"] = barcode
                self.assertEqual(stored, expected)
        self.assertIsNone(entries.get(db, OWN_FOOD_ID))
        self.assertEqual(
            {entry["id"] for entry in entries.search(db, "")},
            {f"off:{EAN_OTHER}", YAZIO_ID.replace("1", "2")},
        )
        self.assertEqual(
            [
                tuple(row)
                for row in db.execute(
                    "SELECT origin, COUNT(*) FROM nutrition_products GROUP BY origin"
                )
            ],
            [("open_food_facts", 2), ("own", 2), ("yazio", 2)],
        )

    def test_failing_baseline_upgrade_rolls_back_and_a_retry_succeeds(self):
        db = self.connect()
        populated_baseline_database(db)
        before = list(db.iterdump())
        upsert = FoodDatabaseEntryRepository.upsert
        calls = []

        def failing_upsert(repository, *args, **kwargs):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("injected migration failure")
            return upsert(repository, *args, **kwargs)

        with (
            mock.patch.object(FoodDatabaseEntryRepository, "upsert", failing_upsert),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_frozen_baseline_fixture_is_the_recorded_production_shape(self):
        db = self.connect()
        db.executescript(BASELINE_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V26
        )

    def test_older_or_newer_schema_version_is_rejected_without_modification(self):
        for version in (0, 1, OLDEST_SUPPORTED_VERSION - 1, CURRENT_SCHEMA_VERSION + 1):
            with self.subTest(version=version):
                db = self.current_database()
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                self.assert_rejected_unchanged(db)

    def test_older_database_file_is_refused_at_startup_without_changes(self):
        # A release before 2.0.5 wrote a schema below 26: startup names the
        # release to upgrade with first and leaves every row and the version.
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "older.db"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(BASELINE_FIXTURE.read_text(encoding="utf-8"))
                db.execute(
                    "INSERT INTO messages(role, content, created_at) "
                    "VALUES ('user', 'Hallo', ?)",
                    (STAMP,),
                )
                db.execute(f"PRAGMA user_version = {OLDEST_SUPPORTED_VERSION - 1}")
                db.commit()
                before = list(db.iterdump())
            manager = temp_database(self, path=path)
            try:
                with (
                    self.assertRaisesRegex(OlderSchemaError, "Release 2.0.5"),
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

    def test_a_previous_shape_upgrades_in_one_step_with_its_rows(self):
        db = self.connect()
        previous_shape_database(db)
        db.execute(
            "INSERT INTO messages(role, content, created_at) "
            "VALUES ('user', 'Hallo', '2026-10-16T08:00:00Z')"
        )
        db.commit()
        with registered_previous_shape(db):
            migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(
            db.execute("SELECT content FROM messages").fetchone()[0], "Hallo"
        )

    def test_lost_savepoint_does_not_mask_the_original_upgrade_error(self):
        # The step fails after its change, or first ends the transaction or
        # drops the savepoint as an engine error can; cleanup keeps the error.
        for statement in ("", "ROLLBACK", "RELEASE schema_migration"):
            with self.subTest(statement=statement):
                db = self.connect()
                previous_shape_database(db)
                before = list(db.iterdump())

                def failing_step(connection, statement=statement):
                    add_index_step(connection)
                    if statement:
                        connection.execute(statement)
                    raise RuntimeError("injected migration failure")

                with (
                    registered_previous_shape(db, failing_step),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], PREVIOUS_VERSION
                )

    def test_upgraded_database_restarts_with_the_same_build_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "upgrade.db"
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            try:
                populated_baseline_database(db)
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
        previous = self.connect()
        previous_shape_database(previous)
        with registered_previous_shape(previous):
            current = self.current_database()
            current.execute(f"PRAGMA user_version = {PREVIOUS_VERSION}")
            current.commit()
            self.assert_rejected_unchanged(current)
            previous.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            previous.commit()
            self.assert_rejected_unchanged(previous)

    @unittest.skipIf(
        cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
    )
    def test_encrypted_current_database_reopens_with_same_key(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "encrypted.db"
            options = {
                "backend": cipher_backend,
                "password": "synthetic-migration-test-key",
                "configure": configure_cipher,
            }
            manager = temp_database(self, path=path, **options)
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                    migrate_schema(db)
            finally:
                manager.close()
            reopened = temp_database(self, path=path, **options)
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
