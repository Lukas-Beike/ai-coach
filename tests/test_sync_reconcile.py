import json
import sqlite3
import unittest

from backend.sync.reconcile import ReconcileDependencies, persist_planned_unit_state


class SyncReconcileTests(unittest.TestCase):
    def test_persists_remote_state_and_uses_caller_connection(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE planned_units (local_id TEXT, payload TEXT, sync_dirty INTEGER, sync_state TEXT, sync_error TEXT, sync_conflict TEXT, external_id TEXT, baseline_hash TEXT, last_synced_at TEXT, updated_at TEXT)")
        db.execute("INSERT INTO planned_units(local_id, payload) VALUES (?, ?)", ("unit-1", json.dumps({"name": "Run"})))
        bumped = []
        self.assertTrue(persist_planned_unit_state(
            db, "unit-1", "synced", None, {"id": "remote-1", "external_id": "ext-1", "moving_time": 600},
            dependencies=ReconcileDependencies(
                redact=lambda value: value, payload_hash=lambda value: "hash", now="now",
                bump_revision=lambda connection: bumped.append(connection),
            ),
        ))
        row = db.execute("SELECT payload, sync_state, sync_dirty, external_id, baseline_hash FROM planned_units").fetchone()
        payload = json.loads(row["payload"])
        self.assertEqual((row["sync_state"], row["sync_dirty"], row["external_id"], row["baseline_hash"]), ("synced", 0, "ext-1", "hash"))
        self.assertEqual(payload["remote_event_id"], "remote-1")
        self.assertEqual(len(bumped), 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
