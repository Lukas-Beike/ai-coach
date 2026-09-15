import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import backend
from backend.db.bootstrap import initialize_application_database
from backend.db.repositories import KeyValueRepository
from backend.db.schema import database_schema_is_current


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
                {"running": "intervals_resync_running", "status": "intervals_resync_status"},
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
        self.key_values.set(db, "morning_checkin_running", "1")
        self.key_values.set(db, "morning_checkin_status", "working")
        self.key_values.set(db, "morning_checkin_attempted", "2026-09-15")

        self.bootstrap(db)

        self.assertTrue(database_schema_is_current(db))
        self.assertEqual(self.key_values.get(db, "profile"), '{"name": "Synthetic athlete"}')
        self.assertEqual(self.key_values.get(db, "intervals_resync_running"), "0")
        self.assertEqual(self.key_values.get(db, "intervals_resync_status"), "")
        self.assertEqual(self.key_values.get(db, "garmin_resync_running"), "0")
        self.assertEqual(self.key_values.get(db, "garmin_resync_status"), "")
        self.assertEqual(self.key_values.get(db, "morning_checkin_running"), "0")
        self.assertEqual(self.key_values.get(db, "morning_checkin_status"), "waiting")
        self.assertEqual(self.key_values.get(db, "morning_checkin_attempted"), "")
        self.assertEqual(db.execute("SELECT revision, updated_at FROM planning_state WHERE id=1").fetchone()["revision"], 0)
        self.assertEqual(db.execute("SELECT updated_at FROM planning_state WHERE id=1").fetchone()["updated_at"], self.now)

    def test_non_current_schema_is_rejected_without_mutation(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        db.execute("CREATE TABLE unexpected_records (id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO unexpected_records VALUES ('synthetic')")
        db.commit()

        with self.assertRaises(RuntimeError):
            self.bootstrap(db)

        self.assertEqual(
            [row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()],
            ["unexpected_records"],
        )
        self.assertEqual(db.execute("SELECT id FROM unexpected_records").fetchone()[0], "synthetic")

    def test_bounded_retention_clamps_to_thirty_days_and_resets_gemini(self):
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
        self.key_values.set(db, "gemini_conversation_history", '[{"role":"user"}]')
        self.key_values.set(db, "gemini_call_names", '{"one":"call"}')

        self.bootstrap(db, retention_days=1)

        self.assertEqual([row["content"] for row in db.execute("SELECT content FROM messages ORDER BY id")], ["recent"])
        self.assertEqual([row["payload"] for row in db.execute("SELECT payload FROM snapshots ORDER BY id")], ["recent"])
        self.assertEqual(self.key_values.get(db, "gemini_conversation_history"), "[]")
        self.assertEqual(self.key_values.get(db, "gemini_call_names"), "{}")

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

        self.assertEqual([row["content"] for row in db.execute("SELECT content FROM messages ORDER BY id")], ["recent"])
        self.assertEqual([row["payload"] for row in db.execute("SELECT payload FROM snapshots ORDER BY id")], ["recent"])

    def test_unlimited_retention_keeps_messages_snapshots_and_history(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db)
        old = (self.current_time - timedelta(days=4000)).isoformat()
        db.execute("INSERT INTO messages(role, content, created_at) VALUES ('user', 'old', ?)", (old,))
        db.execute("INSERT INTO snapshots(payload, created_at) VALUES ('old', ?)", (old,))
        self.key_values.set(db, "gemini_conversation_history", '[{"role":"user"}]')
        self.key_values.set(db, "gemini_call_names", '{"one":"call"}')

        self.bootstrap(db)

        self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
        self.assertEqual(self.key_values.get(db, "gemini_conversation_history"), '[{"role":"user"}]')
        self.assertEqual(self.key_values.get(db, "gemini_call_names"), '{"one":"call"}')

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
