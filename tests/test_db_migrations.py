"""Schema gate: the production baseline reaches the live schema; all else stays unchanged."""

import hashlib
import json
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

# The repository root, for running this file as a script with --write.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from support import temp_database

from backend.canonical.vocabulary import ProviderId
from backend.db import migrations, repositories, schema_history
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
    SHAPE_SCHEMA_V27,
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
SCHEMA_REFERENCE = Path(__file__).resolve().parents[1] / "docs" / "schema-reference.md"
REFERENCE_BEGIN = "<!-- BEGIN GENERATED SCHEMA -->\n"
REFERENCE_END = "<!-- END GENERATED SCHEMA -->\n"


def schema_reference() -> str:
    """The current schema as ``docs/schema-reference.md`` carries it."""
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        initialize_schema(db)
        digest = signature_digest(database_schema_signature(db))
        rows = db.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT GLOB 'sqlite_*' ORDER BY type, name"
        ).fetchall()
    lines = [
        f"Schema version: `{CURRENT_SCHEMA_VERSION}` (`PRAGMA user_version`).",
        "",
        f"Shape digest: `{digest}`.",
        "",
        (
            f"{sum(row['type'] == 'table' for row in rows)} tables and "
            f"{sum(row['type'] == 'index' for row in rows)} named indexes, in signature order."
        ),
    ]
    for row in rows:
        sql = textwrap.dedent("        " + row["sql"]).strip()
        lines += [
            "",
            f"### {row['type']} `{row['name']}`",
            "",
            "```sql",
            sql + ";",
            "```",
        ]
    return "\n".join(lines) + "\n"


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


# SHA-256 of the baseline's product rows after the v26 to v27 step (#2364).
V27_PRODUCT_ROWS_DIGEST = (
    "f7d7c73f042c17cebc01b0486195189428de376ecd1911b9339533965a2c7595"
)


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


# Schema v27, releases 2.1.2 to 2.1.8, has no fixture of its own: the baseline
# after its product step is that shape, here with calendar events of a feed.
V27_CALENDAR_EVENTS = (
    ("event-1", "team@example.test", "Teammeeting", "2026-10-19T09:00:00", 0, 0),
    ("event-2", "team@example.test", "Teammeeting", "2026-10-26T09:00:00", 0, 0),
    ("event-3", "trip@example.test", "Dienstreise", "2026-10-21T00:00:00", 1, 1),
)


def populated_v27_database(db) -> None:
    populated_baseline_database(db)
    migrations._canonical_products(db)
    db.execute("PRAGMA user_version = 27")
    db.executemany(
        "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, "
        "end_local, duration_minutes, all_day, training_relevant, no_training, "
        "updated_at) VALUES (?, ?, ?, substr(?, 1, 10), ?, ?, 60, ?, 1, ?, ?)",
        [
            (event_id, uid, name, start, start, start, all_day, blocked, STAMP)
            for event_id, uid, name, start, all_day, blocked in V27_CALENDAR_EVENTS
        ],
    )
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

    def test_v27_product_step_is_frozen_against_live_repository_changes(self):
        # #2364: the step neither calls the live product repositories nor
        # moves with them; its rows match the result recorded for schema v27
        # by the step before it was frozen.
        source = Path(migrations.__file__).read_text(encoding="utf-8")
        for live in (
            "backend.db.repositories",
            "NUTRITION_PRODUCTS_DDL",
            "NUTRIENT_COLUMNS",
        ):
            self.assertNotIn(live, source)
        db = self.connect()
        populated_baseline_database(db)
        # A 50 g own product: scaled fills, a passed-on origin, another unit.
        ean_half = "4000000000031"
        db.execute(
            "INSERT INTO nutrition_products(id, barcode, name, basis_amount, basis_unit, "
            "source, created_at, updated_at) VALUES ('prod-half', ?, 'Halb', 50, 'g', "
            "'manual', ?, ?)",
            (ean_half, STAMP, STAMP),
        )
        passed_on = {
            **mirror_food(f"off:{ean_half}", "g", kcal=200.0, fat_g=3.0),
            "filled_fields": {"kcal": {"origin": "bls", "fetched_at": "2026-09-01"}},
        }
        other_unit = mirror_food(YAZIO_ID.replace("1", "3"), "ml", protein_g=5.0)
        db.executemany(
            "INSERT INTO food_database_entries(food_id, barcode, name, brand, payload, "
            "fetched_at, updated_at) VALUES (?, ?, ?, 'Marke', ?, ?, ?)",
            [
                (food["id"], ean_half, food["name"], json.dumps(food), day, day)
                for food, day in ((passed_on, "2026-10-04"), (other_unit, "2026-10-05"))
            ],
        )
        with (
            mock.patch.object(
                repositories.FoodDatabaseEntryRepository,
                "upsert",
                side_effect=AssertionError,
            ),
            mock.patch.object(
                repositories.NutritionProductRepository,
                "fill_from_database_entries",
                side_effect=AssertionError,
            ),
            mock.patch.object(
                repositories, "fill_empty_product_fields", side_effect=AssertionError
            ),
        ):
            migrate_schema(db)
        rows = [
            dict(row)
            for row in db.execute("SELECT * FROM nutrition_products ORDER BY id")
        ]
        half = next(row for row in rows if row["id"] == "prod-half")
        # 200 kcal and 3 g fat per 100 g fill 50 g; the ml food fills no nutrient.
        self.assertEqual(
            (half["kcal"], half["fat_g"], half["protein_g"], half["brand"]),
            (100.0, 1.5, None, "Marke"),
        )
        self.assertEqual(
            json.loads(half["details"])["filled_fields"]["kcal"]["origin"], "bls"
        )
        self.assertEqual(
            hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            V27_PRODUCT_ROWS_DIGEST,
        )

    def test_failing_baseline_upgrade_rolls_back_and_a_retry_succeeds(self):
        db = self.connect()
        populated_baseline_database(db)
        before = list(db.iterdump())
        store = migrations._v27_store_food
        calls = []

        def failing_store(*args, **kwargs):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("injected migration failure")
            return store(*args, **kwargs)

        with (
            mock.patch.object(migrations, "_v27_store_food", failing_store),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

    def test_schema_reference_is_current(self):
        document = SCHEMA_REFERENCE.read_text(encoding="utf-8")
        self.assertEqual(
            document.split(REFERENCE_BEGIN, 1)[1].split(REFERENCE_END, 1)[0],
            schema_reference(),
            "Regenerate with: python tests/test_db_migrations.py --write",
        )

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
        for populate in (populated_baseline_database, populated_v27_database):
            with (
                self.subTest(populate=populate.__name__),
                tempfile.TemporaryDirectory() as root,
            ):
                path = Path(root) / "upgrade.db"
                db = sqlite3.connect(path)
                db.row_factory = sqlite3.Row
                try:
                    populate(db)
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

    def test_frozen_v27_shape_is_the_baseline_after_its_product_step(self):
        db = self.connect()
        db.executescript(BASELINE_FIXTURE.read_text(encoding="utf-8"))
        migrations._canonical_products(db)
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V27
        )

    def test_populated_v27_database_gains_the_decision_table_with_every_row(self):
        db = self.connect()
        populated_v27_database(db)
        tables = self.user_tables(db)
        before = self.table_rows(db, tables)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        self.assertEqual(self.table_rows(db, tables), before)
        self.assertEqual(
            self.user_tables(db), sorted([*tables, "external_calendar_decisions"])
        )
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM external_calendar_decisions").fetchone()[
                0
            ],
            0,
        )
        insert = "INSERT INTO external_calendar_decisions VALUES (?, ?, ?, ?)"
        db.execute(insert, ("team@example.test", "", "none", STAMP))
        for row in (
            ("team@example.test", "", "block", STAMP),
            ("team@example.test", "2026-10-19T09:00:00", "maybe", STAMP),
            ("", "", "none", STAMP),
        ):
            with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                db.execute(insert, row)

    def test_failing_v28_step_rolls_back_the_v27_database_and_a_retry_succeeds(self):
        db = self.connect()
        populated_v27_database(db)
        before = list(db.iterdump())

        def failing_step(connection):
            migrations._calendar_decisions(connection)
            raise RuntimeError("injected migration failure")

        with (
            mock.patch.dict(
                migrations.UPGRADE_STEPS,
                {SHAPE_SCHEMA_V27: (SHAPE_CURRENT, failing_step)},
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 27)
        migrate_schema(db)
        db.commit()
        self.assertTrue(database_schema_is_current(db))

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

    @unittest.skipIf(
        cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
    )
    def test_encrypted_v27_database_upgrades_and_restarts_with_its_rows(self):
        password = "synthetic-migration-test-key"
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "encrypted-v27.db"
            db = cipher_backend.connect(str(path))
            db.row_factory = cipher_backend.Row
            try:
                configure_cipher(db, password)
                populated_v27_database(db)
                tables = self.user_tables(db)
                before = self.table_rows(db, tables)
            finally:
                db.close()
            options = {
                "backend": cipher_backend,
                "password": password,
                "configure": configure_cipher,
            }
            for _start in range(2):
                manager = temp_database(self, path=path, **options)
                try:
                    with manager.unit_of_work() as db:
                        migrate_schema(db)
                        self.assertTrue(database_schema_is_current(db))
                        self.assertEqual(self.table_rows(db, tables), before)
                        self.assertEqual(
                            db.execute("PRAGMA cipher_integrity_check").fetchall(), []
                        )
                finally:
                    manager.close()
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")


if __name__ == "__main__":
    if "--write" in sys.argv:
        before, rest = SCHEMA_REFERENCE.read_text(encoding="utf-8").split(
            REFERENCE_BEGIN, 1
        )
        SCHEMA_REFERENCE.write_text(
            before
            + REFERENCE_BEGIN
            + schema_reference()
            + REFERENCE_END
            + rest.split(REFERENCE_END, 1)[1],
            encoding="utf-8",
            newline="\n",
        )
    else:
        unittest.main()
