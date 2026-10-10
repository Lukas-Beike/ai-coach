import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import backend
from backend.db.bootstrap import initialize_application_database
from backend.db.repositories import KeyValueRepository
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    initialize_schema,
)


class DatabaseBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.now = "2026-09-15T12:00:00+00:00"
        self.current_time = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
        self.key_values = KeyValueRepository(lambda: self.now)

    def make_connection(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        return connection

    def bootstrap(self, db, *, retention_days=-1):
        initialize_application_database(
            db,
            key_values=self.key_values,
            now=self.now,
            current_time=self.current_time,
            default_profile_json=json.dumps({"name": "Synthetic athlete"}),
            provider_resync_keys=(
                {
                    "running": "intervals_resync_running",
                    "status": "intervals_resync_status",
                },
                {"running": "garmin_resync_running", "status": "garmin_resync_status"},
            ),
            retention_days=retention_days,
            all_sync_days=-1,
        )

    def test_empty_database_gets_schema_defaults_and_transient_markers(self):
        db = self.make_connection()
        self.addCleanup(db.close)

        self.bootstrap(db)
        self.key_values.set(db, "intervals_resync_running", "1")
        self.key_values.set(db, "intervals_resync_status", "failed")
        self.key_values.set(db, "garmin_resync_running", "1")
        self.key_values.set(db, "garmin_resync_status", "failed")

        self.bootstrap(db)

        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            self.key_values.get(db, "profile"), '{"name": "Synthetic athlete"}'
        )
        self.assertEqual(self.key_values.get(db, "intervals_resync_running"), "0")
        self.assertEqual(self.key_values.get(db, "intervals_resync_status"), "")
        self.assertEqual(self.key_values.get(db, "garmin_resync_running"), "0")
        self.assertEqual(self.key_values.get(db, "garmin_resync_status"), "")
        self.assertEqual(
            db.execute(
                "SELECT revision, updated_at FROM planning_state WHERE id=1"
            ).fetchone()["revision"],
            0,
        )
        self.assertEqual(
            db.execute("SELECT updated_at FROM planning_state WHERE id=1").fetchone()[
                "updated_at"
            ],
            self.now,
        )

    def test_bootstrap_preserves_manual_morning_checkin_state(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db)
        self.key_values.set(db, "morning_checkin_status", "ready")
        self.key_values.set(db, "morning_checkin_date", "2026-09-15")

        self.bootstrap(db)

        self.assertEqual(self.key_values.get(db, "morning_checkin_status"), "ready")
        self.assertEqual(self.key_values.get(db, "morning_checkin_date"), "2026-09-15")
        self.assertIsNone(self.key_values.get(db, "morning_checkin_running"))

    def test_non_current_schema_is_rejected_without_mutation(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        db.execute("CREATE TABLE unexpected_records (id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO unexpected_records VALUES ('synthetic')")
        db.commit()

        with self.assertRaises(RuntimeError):
            self.bootstrap(db)

        self.assertEqual(
            [
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ],
            ["unexpected_records"],
        )
        self.assertEqual(
            db.execute("SELECT id FROM unexpected_records").fetchone()[0], "synthetic"
        )

    def test_tableless_nonfresh_database_is_rejected_without_mutation(self):
        for setup_sql in (
            "PRAGMA user_version = 99",
            "PRAGMA user_version = 1",
            "CREATE VIEW unexpected_view AS SELECT 1 AS id",
            "CREATE VIEW sqlitecustom AS SELECT 1 AS id",
        ):
            with self.subTest(setup_sql=setup_sql):
                db = self.make_connection()
                self.addCleanup(db.close)
                db.execute(setup_sql)
                db.commit()
                before = list(db.iterdump())
                version = db.execute("PRAGMA user_version").fetchone()[0]
                with self.assertRaises(RuntimeError):
                    self.bootstrap(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_1_12_19_schema_is_migrated_without_losing_existing_rows(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        initialize_schema(db)
        db.execute(
            "INSERT INTO nutrition_logs(id, meal_date, logged_at, meal_type, description, kcal, created_at, updated_at) VALUES ('meal-1', '2026-09-15', ?, 'lunch', 'Synthetic meal', 500, ?, ?)",
            (self.now, self.now, self.now),
        )
        db.execute("DROP TABLE nutrition_products")
        db.execute("ALTER TABLE external_calendar_events DROP COLUMN no_training")
        db.execute("PRAGMA user_version = 1")
        db.commit()

        self.bootstrap(db)

        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(
            db.execute(
                "SELECT description FROM nutrition_logs WHERE id='meal-1'"
            ).fetchone()[0],
            "Synthetic meal",
        )
        self.assertEqual(
            db.execute("PRAGMA user_version").fetchone()[0], CURRENT_SCHEMA_VERSION
        )
        db.execute(
            "INSERT INTO nutrition_products(id, name, basis_amount, basis_unit, source, created_at, updated_at) VALUES ('product-1', 'Synthetic oats', 100, 'g', 'manual', ?, ?)",
            (self.now, self.now),
        )
        self.assertEqual(
            db.execute("SELECT name FROM nutrition_products").fetchone()[0],
            "Synthetic oats",
        )

    def test_bounded_retention_keeps_removed_gemini_state_absent(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db, retention_days=1)
        old = (self.current_time - timedelta(days=31)).isoformat()
        recent = (self.current_time - timedelta(days=29)).isoformat()
        db.executemany(
            "INSERT INTO messages(role, content, created_at) VALUES ('user', ?, ?)",
            [("old", old), ("recent", recent)],
        )
        db.executemany(
            "INSERT INTO snapshots(payload, created_at) VALUES (?, ?)",
            [("old", old), ("recent", recent)],
        )
        db.execute("PRAGMA user_version = 3")

        self.bootstrap(db, retention_days=1)

        self.assertEqual(
            [
                row["content"]
                for row in db.execute("SELECT content FROM messages ORDER BY id")
            ],
            ["recent"],
        )
        self.assertEqual(
            [
                row["payload"]
                for row in db.execute("SELECT payload FROM snapshots ORDER BY id")
            ],
            ["recent"],
        )
        self.assertIsNone(self.key_values.get(db, "gemini_conversation_history"))
        self.assertIsNone(self.key_values.get(db, "gemini_call_names"))

    def test_release_1_12_26_reopen_does_not_recreate_retired_provider_state(self):
        fixture = Path(__file__).with_name("fixtures") / "schema_1_12_26.sql.txt"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.db"
            with closing(sqlite3.connect(path)) as db:
                db.row_factory = sqlite3.Row
                db.executescript(fixture.read_text(encoding="utf-8"))
                db.executemany(
                    "INSERT INTO kv VALUES (?, ?, 'before')",
                    [
                        ("selected_ai_provider", "gemini"),
                        ("selected_model_gemini", "gemini-test"),
                        ("gemini_conversation_history", "[]"),
                        ("gemini_call_names", "{}"),
                        ("gemini_usage", "{}"),
                        ("gemini_status", "{}"),
                        ("openai_conversation_id", "conv_openai"),
                    ],
                )
                self.bootstrap(db)
                db.commit()
                after_upgrade = list(db.iterdump())

            with closing(sqlite3.connect(path)) as db:
                db.row_factory = sqlite3.Row
                self.bootstrap(db)
                db.commit()
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(list(db.iterdump()), after_upgrade)
                values = dict(db.execute("SELECT key, value FROM kv"))
                self.assertEqual(values["selected_ai_provider"], "openai")
                self.assertEqual(values["openai_conversation_id"], "conv_openai")
                self.assertFalse(any(key.startswith("gemini_") for key in values))
                self.assertNotIn("selected_model_gemini", values)

    def test_bounded_retention_clamps_to_three_thousand_six_hundred_fifty_days(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db, retention_days=-1)
        old = (self.current_time - timedelta(days=3651)).isoformat()
        recent = (self.current_time - timedelta(days=3649)).isoformat()
        db.executemany(
            "INSERT INTO messages(role, content, created_at) VALUES ('user', ?, ?)",
            [("old", old), ("recent", recent)],
        )
        db.executemany(
            "INSERT INTO snapshots(payload, created_at) VALUES (?, ?)",
            [("old", old), ("recent", recent)],
        )

        self.bootstrap(db, retention_days=9999)

        self.assertEqual(
            [
                row["content"]
                for row in db.execute("SELECT content FROM messages ORDER BY id")
            ],
            ["recent"],
        )
        self.assertEqual(
            [
                row["payload"]
                for row in db.execute("SELECT payload FROM snapshots ORDER BY id")
            ],
            ["recent"],
        )

    def test_unlimited_retention_keeps_messages_and_snapshots(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db)
        old = (self.current_time - timedelta(days=4000)).isoformat()
        db.execute(
            "INSERT INTO messages(role, content, created_at) VALUES ('user', 'old', ?)",
            (old,),
        )
        db.execute(
            "INSERT INTO snapshots(payload, created_at) VALUES ('old', ?)", (old,)
        )

        self.bootstrap(db)

        self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_import_has_no_database_side_effects(self):
        with tempfile.TemporaryDirectory() as root:
            repository_root = Path(backend.__file__).resolve().parents[1]
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(repository_root)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", "import backend.db.bootstrap"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(root).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
