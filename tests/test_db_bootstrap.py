import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import backend
from backend.db.bootstrap import initialize_application_database
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import (
    database_schema_is_current,
)


class DatabaseBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.now = "2026-09-15T12:00:00+00:00"
        self.current_time = datetime(2026, 9, 15, 12, tzinfo=UTC)
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

    def test_non_positive_retention_values_keep_old_messages_and_snapshots(self):
        for retention_days in (0, -5):
            with self.subTest(retention_days=retention_days):
                db = self.make_connection()
                self.addCleanup(db.close)
                self.bootstrap(db)
                old = (self.current_time - timedelta(days=4000)).isoformat()
                db.execute(
                    "INSERT INTO messages(role, content, created_at) VALUES ('user', 'old', ?)",
                    (old,),
                )
                db.execute(
                    "INSERT INTO snapshots(payload, created_at) VALUES ('old', ?)",
                    (old,),
                )

                self.bootstrap(db, retention_days=retention_days)

                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1
                )

    def test_positive_retention_purges_rows_older_than_clamped_window(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db)
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

        with self.assertLogs("intervals_coach", level="INFO") as logs:
            self.bootstrap(db, retention_days=10)

        self.assertEqual(
            [row["content"] for row in db.execute("SELECT content FROM messages")],
            ["recent"],
        )
        self.assertEqual(
            [row["payload"] for row in db.execute("SELECT payload FROM snapshots")],
            ["recent"],
        )
        (record,) = logs.records
        self.assertEqual(record.event, "data_retention_purged")
        self.assertEqual(
            record.context,
            {
                "retention_days": 30,
                "messages_deleted": 1,
                "snapshots_deleted": 1,
                "coach_commands_deleted": 0,
                "coach_plan_artifacts_deleted": 0,
                "coach_action_proposals_deleted": 0,
            },
        )

    def _insert_command(self, db, turn_id, created_at, receipt, *, status="completed"):
        db.execute(
            "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, "
            "status, receipt, created_at, updated_at, artifact_id) "
            "VALUES (?, ?, 'chat', 'none', ?, ?, ?, ?, NULL)",
            (turn_id, turn_id, status, receipt, created_at, created_at),
        )

    def _insert_artifact(self, db, artifact_id, status, created_at):
        db.execute(
            "INSERT INTO coach_plan_artifacts(id, base_revision, status, payload, "
            "created_at, updated_at) VALUES (?, 0, ?, '{}', ?, ?)",
            (artifact_id, status, created_at, created_at),
        )

    def test_retention_purges_old_receipts_artifacts_and_expired_proposals(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db)
        old = (self.current_time - timedelta(days=45)).isoformat()
        recent = (self.current_time - timedelta(days=5)).isoformat()

        def undoable(change_id: str) -> str:
            return json.dumps(
                {
                    "change_summary": {"undoable": True, "undone_at": None},
                    "command_receipts": [
                        "malformed",
                        {"tool": "update_profile", "changes": [{"id": change_id}]},
                    ],
                }
            )

        # Undoable only while the history rows it names are kept (#2134, K-003).
        open_undo = undoable("kept")
        for change_id, created_at in (
            ("kept", recent),
            ("expired", (self.current_time - timedelta(days=181)).isoformat()),
        ):
            db.execute(
                "INSERT INTO change_history(id, entity_type, entity_id, action, "
                "source, created_at, before_hash, after_hash, diff) "
                "VALUES (?, 'profile', 'profile', 'update', 'local', ?, 'a', 'b', '{}')",
                (change_id, created_at),
            )
        undone = json.dumps(
            {"change_summary": {"undoable": True, "undone_at": "2026-08-01"}}
        )
        not_undoable = json.dumps(
            {"change_summary": {"undoable": False, "undone_at": None}}
        )
        self._insert_command(db, "old-plain", old, json.dumps({"text": "chat copy"}))
        self._insert_command(db, "old-open-undo", old, open_undo)
        self._insert_command(db, "old-undo-history-gone", old, undoable("pruned"))
        self._insert_command(db, "old-undo-history-expired", old, undoable("expired"))
        self._insert_command(
            db,
            "old-undo-without-reference",
            old,
            json.dumps({"change_summary": {"undoable": True, "undone_at": None}}),
        )
        self._insert_command(db, "old-undone", old, undone)
        self._insert_command(db, "old-not-undoable", old, not_undoable)
        self._insert_command(db, "old-broken", old, "not json")
        self._insert_command(db, "old-null", old, None)
        self._insert_command(db, "old-running", old, "{}", status="running")
        self._insert_command(db, "recent", recent, "{}")
        self._insert_artifact(db, "art-old-committed", "committed", old)
        self._insert_artifact(db, "art-old-superseded", "superseded", old)
        self._insert_artifact(db, "art-old-draft", "draft", old)
        self._insert_artifact(db, "art-recent", "committed", recent)
        self._insert_artifact(db, "art-linked", "committed", old)
        db.execute(
            "UPDATE coach_commands SET artifact_id='art-linked' "
            "WHERE client_turn_id='old-open-undo'"
        )
        now = self.current_time.timestamp()
        for proposal_id, expires_at in (
            ("expired", now - 1),
            ("live", now + 600),
        ):
            db.execute(
                "INSERT INTO coach_action_proposals(id, session_csrf_hash, "
                "action_type, target_system, object_ids, diff, payload, "
                "payload_hash, status, expires_at, created_at) "
                "VALUES (?, 'h', 'local_coach_write', 'local', '{}', '{}', '{}', "
                "'p', 'ready', ?, ?)",
                (proposal_id, expires_at, recent),
            )
        db.execute(
            "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
            "VALUES ('unit', 'unit', '{}', ?, ?)",
            (old, old),
        )
        profile_before = self.key_values.get(db, "profile")

        with self.assertLogs("intervals_coach", level="INFO") as logs:
            self.bootstrap(db, retention_days=30)

        self.assertEqual(
            sorted(
                row[0]
                for row in db.execute("SELECT client_turn_id FROM coach_commands")
            ),
            ["old-open-undo", "old-running", "recent"],
        )
        self.assertEqual(
            sorted(row[0] for row in db.execute("SELECT id FROM coach_plan_artifacts")),
            ["art-linked", "art-old-draft", "art-recent"],
        )
        self.assertEqual(
            [row[0] for row in db.execute("SELECT id FROM coach_action_proposals")],
            ["live"],
        )
        (record,) = logs.records
        self.assertEqual(record.context["coach_commands_deleted"], 8)
        self.assertEqual(record.context["coach_plan_artifacts_deleted"], 2)
        self.assertEqual(record.context["coach_action_proposals_deleted"], 1)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM planned_units").fetchone()[0], 1
        )
        self.assertEqual(self.key_values.get(db, "profile"), profile_before)

    def test_unlimited_retention_keeps_old_receipts_and_expired_proposals(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db)
        old = (self.current_time - timedelta(days=4000)).isoformat()
        self._insert_command(db, "old", old, "{}")
        db.execute(
            "INSERT INTO coach_action_proposals(id, session_csrf_hash, action_type, "
            "target_system, object_ids, diff, payload, payload_hash, status, "
            "expires_at, created_at) VALUES ('e', 'h', 'local_coach_write', 'local', "
            "'{}', '{}', '{}', 'p', 'ready', 1.0, ?)",
            (old,),
        )

        self.bootstrap(db)

        for table in ("coach_commands", "coach_action_proposals"):
            self.assertEqual(
                db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1
            )

    def test_retention_keeps_the_newest_snapshot_after_a_long_sync_gap(self):
        db = self.make_connection()
        self.addCleanup(db.close)
        self.bootstrap(db)
        older = (self.current_time - timedelta(days=90)).isoformat()
        old = (self.current_time - timedelta(days=45)).isoformat()
        db.executemany(
            "INSERT INTO snapshots(payload, created_at) VALUES (?, ?)",
            [("older", older), ("newest-but-old", old)],
        )

        self.bootstrap(db, retention_days=30)

        self.assertEqual(
            [row["payload"] for row in db.execute("SELECT payload FROM snapshots")],
            ["newest-but-old"],
        )
        self.assertEqual(SnapshotRepository().latest_payload(db), "newest-but-old")

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
