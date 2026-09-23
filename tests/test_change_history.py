import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from backend import change_history
from backend.errors import AppError


class ChangeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE change_history ("
            "id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, action TEXT, "
            "source TEXT, created_at TEXT, before_hash TEXT, after_hash TEXT, diff TEXT)"
        )

    def tearDown(self):
        self.db.close()

    def test_projection_keeps_allowlisted_bounded_fields_only(self):
        projected = change_history.audit_projection(
            "profile",
            {
                "name": "Ada",
                "weather_location": "Münster",
                "secret": "never retained",
                "notes": "x" * 5000,
            },
        )
        self.assertEqual(projected, {"name": "Ada", "weather_location": "Münster"})

    def test_record_change_persists_hashes_and_private_diff(self):
        record = change_history.record_change(
            self.db,
            "profile",
            "profile",
            "update",
            {"name": "Before", "secret": "old"},
            {"name": "After", "secret": "new"},
        )
        self.assertIsNotNone(record)
        row = dict(self.db.execute("SELECT * FROM change_history").fetchone())
        self.assertEqual(
            json.loads(row["diff"])["fields"]["name"],
            {
                "before": "Before",
                "after": "After",
            },
        )
        self.assertNotIn("secret", row["diff"])
        self.assertEqual(row["before_hash"], record["before_hash"])

    def test_unchanged_record_is_skipped_but_undo_is_retained(self):
        value = {"name": "Same"}
        self.assertIsNone(
            change_history.record_change(
                self.db, "profile", "profile", "update", value, value
            )
        )
        self.assertIsNotNone(
            change_history.record_change(
                self.db, "profile", "profile", "undo", value, value
            )
        )

    def test_cleanup_and_capacity_preserve_bounds(self):
        old = (datetime.now(timezone.utc) - timedelta(days=181)).isoformat()
        self.db.execute(
            "INSERT INTO change_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old", "profile", "profile", "update", "local", old, "a", "b", "{}"),
        )
        change_history.cleanup(self.db)
        self.assertIsNone(
            self.db.execute("SELECT id FROM change_history WHERE id='old'").fetchone()
        )
        with self.assertRaises(AppError) as raised:
            change_history.reserve_capacity(self.db, change_history.MAX_ROWS + 1)
        self.assertEqual(raised.exception.reason, "change_history_limit")

    def test_public_view_never_exposes_diff_values(self):
        row = {
            "id": "one",
            "entity_type": "profile",
            "entity_id": "profile",
            "action": "update",
            "source": "local",
            "created_at": "2026-09-20T00:00:00+00:00",
            "before_hash": "before",
            "after_hash": "after",
            "diff": json.dumps(
                {
                    "fields": {
                        "name": {"before": "Ada", "after": "Grace"},
                        "unsafe-field": {"before": "x", "after": "y"},
                    },
                    "before_present": True,
                    "after_present": True,
                }
            ),
        }
        view = change_history.public_view(row)
        self.assertEqual(view["diff"]["fields"], {"name": {"changed": True}})
        self.assertNotIn("Ada", json.dumps(view))
        self.assertEqual(view["remote_sync"], "local_only")


if __name__ == "__main__":
    unittest.main()
