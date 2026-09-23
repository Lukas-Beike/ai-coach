from __future__ import annotations

import copy
import json
import sqlite3
import unittest

from backend.db import row_factory
from backend.db.repositories import PlanningStateRepository
from backend.planning.planned_units import planned_unit_payload_hash
from backend.planning.revision import PlanningRevisionService
from backend.sync.reconcile import PlannedUnitSyncStateWriter


class TestRedactor:
    def __init__(self):
        self.calls = []
        self.output = None

    def redact_text(self, text):
        self.calls.append(text)
        return self.output if self.output is not None else f"redacted:{text}"


class SyncReconcileTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = row_factory
        self.db.execute(
            "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT, "
            "sync_dirty INTEGER, sync_state TEXT, sync_error TEXT, sync_conflict TEXT, "
            "external_id TEXT, baseline_hash TEXT, last_synced_at TEXT, updated_at TEXT)"
        )
        self.db.execute(
            "CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        self.db.execute(
            "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 7, 'initial')"
        )
        self.revisions = PlanningRevisionService(
            PlanningStateRepository(), lambda: "revision-time"
        )
        self.redactor = TestRedactor()
        self.writer = PlannedUnitSyncStateWriter(self.revisions, self.redactor)

    def tearDown(self):
        self.db.close()

    def add_unit(self, local_id, payload="{}", **columns):
        values = {
            "payload": payload
            if isinstance(payload, str) or payload is None
            else json.dumps(payload),
            "sync_dirty": 1,
            "sync_state": "pending",
            "sync_error": None,
            "sync_conflict": "",
            "external_id": None,
            "baseline_hash": None,
            "last_synced_at": None,
            "updated_at": None,
        }
        values.update(columns)
        self.db.execute(
            "INSERT INTO planned_units(local_id, payload, sync_dirty, sync_state, sync_error, "
            "sync_conflict, external_id, baseline_hash, last_synced_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (local_id, *values.values()),
        )

    def unit(self, local_id):
        return self.db.execute(
            "SELECT * FROM planned_units WHERE local_id = ?", (local_id,)
        ).fetchone()

    def test_synced_persists_remote_fields_hash_and_one_revision(self):
        original_payload = {
            "name": "Run",
            "moving_time": 300,
            "workout_doc": "old",
            "icu_training_load": 1,
            "icu_intensity": 2,
        }
        remote_event = {
            "id": 42,
            "external_id": "external-1",
            "moving_time": 600,
            "workout_doc": "new workout",
            "icu_training_load": 4,
            "icu_intensity": 5,
        }
        payload_before = copy.deepcopy(original_payload)
        remote_before = copy.deepcopy(remote_event)
        self.add_unit("unit-1", original_payload)

        self.assertTrue(
            self.writer.persist(
                self.db, "unit-1", "synced", None, remote_event, now="sync-time"
            )
        )

        row = self.unit("unit-1")
        payload = json.loads(row["payload"])
        self.assertEqual(row["sync_state"], "synced")
        self.assertEqual(row["sync_dirty"], 0)
        self.assertIsNone(row["sync_error"])
        self.assertEqual(row["sync_conflict"], "")
        self.assertEqual(row["external_id"], "external-1")
        self.assertEqual(row["baseline_hash"], planned_unit_payload_hash(payload))
        self.assertEqual(row["last_synced_at"], "sync-time")
        self.assertEqual(row["updated_at"], "sync-time")
        self.assertEqual(
            payload,
            {
                "name": "Run",
                "sync_status": "synced",
                "remote_event_id": "42",
                "remote_event_external_id": "external-1",
                "external_id": "external-1",
                "moving_time": 600,
                "workout_doc": "new workout",
                "icu_training_load": 4,
                "icu_intensity": 5,
            },
        )
        self.assertEqual(self.revisions.read(self.db), 8)
        self.assertEqual(original_payload, payload_before)
        self.assertEqual(remote_event, remote_before)
        self.assertTrue(self.db.in_transaction)

    def test_synced_keeps_missing_moving_time_and_pops_other_missing_fields(self):
        self.add_unit(
            "unit-1",
            {
                "moving_time": 300,
                "workout_doc": "old",
                "icu_training_load": 1,
                "icu_intensity": 2,
            },
        )
        remote_event = {"id": "remote-1", "external_id": " external-1 "}

        self.writer.persist(
            self.db, "unit-1", "synced", None, remote_event, now="sync-time"
        )

        payload = json.loads(self.unit("unit-1")["payload"])
        self.assertEqual(payload["moving_time"], 300)
        self.assertNotIn("workout_doc", payload)
        self.assertNotIn("icu_training_load", payload)
        self.assertNotIn("icu_intensity", payload)
        self.assertEqual(payload["external_id"], " external-1 ")
        self.assertEqual(self.unit("unit-1")["external_id"], "external-1")
        self.assertEqual(self.revisions.read(self.db), 8)

    def test_error_conflict_and_remote_missing_state_rules(self):
        cases = (
            ("error", 1, "", "redacted:provider error"),
            ("conflict", 1, None, "redacted:provider error"),
            ("remote_missing", 0, "", None),
        )
        for index, (state, dirty, conflict, error) in enumerate(cases):
            local_id = f"unit-{index}"
            self.add_unit(local_id, {"name": "Run"})
            self.writer.persist(
                self.db,
                local_id,
                state,
                "provider error" if index < 2 else None,
                {"id": f"remote-{index}", "external_id": f"external-{index}"},
                now="sync-time",
            )
            row = self.unit(local_id)
            payload = json.loads(row["payload"])
            self.assertEqual(row["sync_state"], state)
            self.assertEqual(row["sync_dirty"], dirty)
            self.assertEqual(row["sync_conflict"], conflict)
            self.assertEqual(row["sync_error"], error)
            self.assertEqual(row["external_id"], f"external-{index}")
            self.assertEqual(payload["remote_event_id"], f"remote-{index}")
            self.assertEqual(row["baseline_hash"], None)
            self.assertIsNone(row["last_synced_at"])
            self.assertEqual(row["updated_at"], "sync-time")

        self.assertEqual(self.redactor.calls, ["provider error", "provider error"])
        self.assertEqual(self.revisions.read(self.db), 10)

    def test_error_redaction_is_limited_to_1000_characters(self):
        self.add_unit("unit-1")
        self.redactor.output = "r" * 1200

        self.writer.persist(
            self.db, "unit-1", "error", "failure", None, now="sync-time"
        )

        self.assertEqual(self.unit("unit-1")["sync_error"], "r" * 1000)
        self.assertEqual(self.redactor.calls, ["failure"])

    def test_missing_and_corrupt_payloads_become_empty_objects(self):
        payloads = (None, "{broken", "[]", "null")
        for index, raw_payload in enumerate(payloads):
            local_id = f"unit-{index}"
            self.add_unit(local_id, raw_payload)
            self.assertTrue(
                self.writer.persist(
                    self.db, local_id, "error", None, None, now="sync-time"
                )
            )
            self.assertEqual(
                json.loads(self.unit(local_id)["payload"]), {"sync_status": "error"}
            )

        self.assertEqual(self.revisions.read(self.db), 11)

    def test_missing_record_returns_false_without_revision_or_redaction(self):
        self.assertFalse(
            self.writer.persist(
                self.db, "absent", "error", "failure", None, now="sync-time"
            )
        )

        self.assertEqual(self.revisions.read(self.db), 7)
        self.assertEqual(self.redactor.calls, [])

    def test_non_synced_external_fields_preserve_existing_values_with_coalesce(self):
        self.add_unit(
            "unit-1",
            {"name": "Run"},
            external_id="stored-external",
            baseline_hash="stored-hash",
            last_synced_at="stored-time",
        )

        self.writer.persist(
            self.db,
            "unit-1",
            "error",
            None,
            {"id": "remote-1", "external_id": "  "},
            now="sync-time",
        )

        row = self.unit("unit-1")
        self.assertEqual(row["external_id"], "stored-external")
        self.assertEqual(row["baseline_hash"], "stored-hash")
        self.assertEqual(row["last_synced_at"], "stored-time")
        self.assertEqual(self.revisions.read(self.db), 8)


if __name__ == "__main__":
    unittest.main()
