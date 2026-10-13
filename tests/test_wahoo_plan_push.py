"""Explicit Wahoo plan push: remote links, update-not-duplicate, no partial writes."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from backend.canonical.vocabulary import RemoteEntityKind
from backend.db import DatabaseManager, row_factory
from backend.db.remote_links import RemoteLinkRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning import library as planning_library
from backend.providers.wahoo_client import WahooReconnectRequiredError
from backend.sync.wahoo_plan_push import WahooPlanPushService
from backend.sync.wahoo_workout_export import WahooWorkoutExport, wahoo_external_id

W1 = "11111111-1111-4111-8111-111111111111"
W2 = "22222222-2222-4222-8222-222222222222"
MISSING = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)
RIDE = {
    "type": "Ride",
    "name": "Tempo",
    "description": "Warmup\n- 10m 150W\n\nMain Set\n- 5m 250-280W",
}


class FakeWahoo:
    """In-memory Wahoo plans keyed by id; records every call, never the network."""

    def __init__(self) -> None:
        self.plans: dict[int, dict] = {}
        self.calls: list[tuple] = []
        self.next_id = 100

    def create_plan(self, plan, *, filename, external_id, provider_updated_at):
        self.calls.append(("create", external_id))
        self.next_id += 1
        self.plans[self.next_id] = {
            "id": self.next_id,
            "external_id": external_id,
            "plan": plan,
        }
        return {"id": self.next_id, "external_id": external_id}

    def update_plan(self, plan_id, plan, *, filename, provider_updated_at):
        self.calls.append(("update", plan_id))
        if plan_id not in self.plans:
            raise AppError(502, "gone", reason="upstream_rejected", upstream_status=404)
        self.plans[plan_id]["plan"] = plan
        return {"id": plan_id}

    def delete_plan(self, plan_id):
        self.calls.append(("delete", plan_id))
        self.plans.pop(plan_id, None)

    def list_plans(self):
        self.calls.append(("list",))
        return tuple(
            {"id": p["id"], "external_id": p["external_id"]}
            for p in self.plans.values()
        )

    def writes(self) -> list[tuple]:
        return [
            call for call in self.calls if call[0] in {"create", "update", "delete"}
        ]


class PushCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.directory.name) / "push.sqlite", sqlite3, row_factory=row_factory
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.wahoo: Any = FakeWahoo()
        self.connected = True
        self.export = WahooWorkoutExport(lambda: self.wahoo, now=lambda: NOW)
        self.service = WahooPlanPushService(
            configured=lambda: self.connected,
            database_manager=lambda: self.database_manager,
            export=lambda: self.export,
            now=lambda: NOW,
            redactor=lambda text: text.replace("SECRET", "[redacted]"),
        )

    def tearDown(self) -> None:
        self.database_manager.close()
        self.directory.cleanup()

    def insert(self, local_id: str, payload: dict) -> str:
        raw = json.dumps(payload)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (local_id, local_id, raw, "2026-10-01T00:00:00+00:00"),
            )
        return planning_library.library_payload_hash(raw)

    def push(self, *entries: tuple[str, str]) -> dict:
        return self.service.sync(
            {
                "entries": [
                    {"library_workout_id": i, "expected_payload_hash": h}
                    for i, h in entries
                ]
            }
        )

    def link(self, local_id: str):
        with self.database_manager.unit_of_work() as db:
            return RemoteLinkRepository().get(
                db, RemoteEntityKind.LIBRARY_WORKOUT, local_id, "wahoo"
            )

    def library_row(self, local_id: str):
        with self.database_manager.unit_of_work() as db:
            return db.execute(
                "SELECT * FROM workout_library WHERE local_id=?", (local_id,)
            ).fetchone()


class PushTests(PushCase):
    def test_first_push_creates_a_plan_and_stores_the_remote_link(self) -> None:
        digest = self.insert(W1, RIDE)

        result = self.push((W1, digest))

        self.assertTrue(result["ok"])
        self.assertEqual("ok", result["status"])
        self.assertEqual("synced", result["results"][0]["status"])
        self.assertEqual([("create", wahoo_external_id(W1))], self.wahoo.writes())
        link = self.link(W1)
        self.assertEqual("101", link.remote_id)
        self.assertEqual(wahoo_external_id(W1), link.remote_external_id)
        self.assertEqual(digest, link.baseline_hash)

    def test_second_push_updates_the_same_plan_without_duplicating(self) -> None:
        digest = self.insert(W1, RIDE)
        self.push((W1, digest))

        result = self.push((W1, digest))

        self.assertEqual("synced", result["results"][0]["status"])
        self.assertEqual(1, len(self.wahoo.plans))
        self.assertEqual(
            [("create", wahoo_external_id(W1)), ("update", 101)],
            self.wahoo.writes(),
        )
        self.assertEqual("101", self.link(W1).remote_id)

    def test_a_plan_deleted_at_wahoo_is_created_again(self) -> None:
        digest = self.insert(W1, RIDE)
        self.push((W1, digest))
        self.wahoo.plans.clear()

        result = self.push((W1, digest))

        self.assertEqual("synced", result["results"][0]["status"])
        self.assertEqual("102", self.link(W1).remote_id)

    def test_an_earlier_upload_without_a_link_is_adopted_by_external_id(self) -> None:
        digest = self.insert(W1, RIDE)
        self.wahoo.plans[7] = {
            "id": 7,
            "external_id": wahoo_external_id(W1),
            "plan": {},
        }

        self.push((W1, digest))

        self.assertEqual([("update", 7)], self.wahoo.writes())
        self.assertEqual("7", self.link(W1).remote_id)

    def test_intervals_slots_of_the_library_row_stay_untouched(self) -> None:
        digest = self.insert(W1, RIDE)
        before = dict(self.library_row(W1))

        self.push((W1, digest))

        self.assertEqual(before, dict(self.library_row(W1)))

    def test_changed_workout_is_a_conflict_and_nothing_is_written(self) -> None:
        self.insert(W1, RIDE)

        result = self.push((W1, "0" * 64))

        self.assertEqual("conflict", result["results"][0]["status"])
        self.assertEqual("error", result["status"])
        self.assertEqual([], self.wahoo.writes())
        self.assertIsNone(self.link(W1))

    def test_unknown_workout_is_a_conflict(self) -> None:
        result = self.push((MISSING, "0" * 64))

        self.assertEqual("conflict", result["results"][0]["status"])
        self.assertEqual([], self.wahoo.calls)

    def test_unsupported_workout_is_a_per_workout_error_others_still_sync(self) -> None:
        bad = self.insert(W1, {**RIDE, "type": "Swim"})
        good = self.insert(W2, RIDE)

        result = self.push((W1, bad), (W2, good))

        self.assertEqual("partial", result["status"])
        self.assertEqual([W1], result["failed_object_ids"])
        self.assertEqual("error", result["results"][0]["status"])
        self.assertIn("Rad- und Laufeinheiten", result["results"][0]["error"])
        self.assertEqual("synced", result["results"][1]["status"])
        self.assertIsNone(self.link(W1))
        self.assertIsNotNone(self.link(W2))

    def test_not_connected_raises_before_any_read_or_write(self) -> None:
        digest = self.insert(W1, RIDE)
        self.connected = False

        with self.assertRaises(AppError) as caught:
            self.push((W1, digest))

        self.assertEqual(409, caught.exception.status)
        self.assertEqual("not_configured", caught.exception.reason)
        self.assertEqual([], self.wahoo.calls)
        self.assertIsNone(self.link(W1))

    def test_reconnect_required_aborts_the_run_without_a_link(self) -> None:
        digest = self.insert(W1, RIDE)
        self.wahoo.create_plan = Mock(side_effect=WahooReconnectRequiredError())

        with self.assertRaises(WahooReconnectRequiredError):
            self.push((W1, digest))

        self.assertIsNone(self.link(W1))

    def test_remote_errors_are_redacted_per_entry(self) -> None:
        digest = self.insert(W1, RIDE)
        self.wahoo.create_plan = Mock(
            side_effect=AppError(502, "boom SECRET", reason="upstream_rejected")
        )

        result = self.push((W1, digest))

        self.assertEqual("error", result["results"][0]["status"])
        self.assertNotIn("SECRET", result["results"][0]["error"])
        self.assertIsNone(self.link(W1))

    def test_repair_is_not_available(self) -> None:
        with self.assertRaises(AppError) as caught:
            self.service.sync({"entries": [], "repair": True})

        self.assertEqual(400, caught.exception.status)

    def test_entries_require_an_expected_hash(self) -> None:
        self.insert(W1, RIDE)

        with self.assertRaises(AppError):
            self.service.sync({"entries": [{"library_workout_id": W1}]})
        self.assertEqual([], self.wahoo.calls)


class DeleteTests(PushCase):
    def test_deleting_a_missing_plan_counts_as_deleted(self) -> None:
        self.export.delete_library("55")

        self.assertEqual([("delete", 55)], self.wahoo.calls)

    def test_a_404_on_delete_is_ignored(self) -> None:
        self.wahoo.delete_plan = Mock(
            side_effect=AppError(
                502, "x", reason="upstream_rejected", upstream_status=404
            )
        )

        self.export.delete_library("55")

    def test_other_delete_failures_surface(self) -> None:
        self.wahoo.delete_plan = Mock(
            side_effect=AppError(
                502, "x", reason="upstream_rejected", upstream_status=500
            )
        )

        with self.assertRaises(AppError):
            self.export.delete_library("55")


if __name__ == "__main__":
    unittest.main()
