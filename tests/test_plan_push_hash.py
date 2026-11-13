"""Plan-push previews survive sync writes, retries keep settled items (#1885)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from datetime import date
from unittest.mock import Mock

from remote_link_fixtures import create_remote_links_table
from support import temp_database

from backend.db import row_factory
from backend.db.repositories import KeyValueRepository
from backend.planning.planned_units import (
    plan_push_hash_matches,
    plan_push_payload_hash,
)
from backend.planning.workout_export import past_export_horizon
from backend.sync.authority import PlanningAuthorityService
from backend.sync.executor import _unsettled_plan_entries
from backend.sync.jobs import SyncJobStore
from backend.sync.library import WorkoutLibrarySyncStateService

NOW = "2026-11-09T12:00:00+00:00"
UNIT = {
    "name": "Tempo",
    "date": "2026-11-12",
    "type": "Run",
    "description": "- 10m Z2",
    "planned_duration_s": 3600,
}


def _raw(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class PlanPushHashTests(unittest.TestCase):
    def test_sync_written_fields_do_not_move_the_hash(self) -> None:
        before = plan_push_payload_hash(_raw(UNIT))
        synced = {
            **UNIT,
            "sync_status": "synced",
            "remote_event_id": "991",
            "remote_event_external_id": "pacecraft-1",
            "external_id": "pacecraft-1",
            "sync_error": "timeout",
            "planned_load": 64,
            "planned_intensity": 0.8,
            "workout_doc": {"steps": []},
        }
        self.assertEqual(plan_push_payload_hash(_raw(synced)), before)
        # A card recorded before the Intervals.icu push still matches after it.
        self.assertTrue(plan_push_hash_matches(_raw(synced), before))

    def test_content_changes_move_the_hash(self) -> None:
        before = plan_push_payload_hash(_raw(UNIT))
        for key, value in (
            ("name", "Schwelle"),
            ("date", "2026-11-13"),
            ("description", "- 20m Z3"),
            ("planned_duration_s", 4200),
        ):
            with self.subTest(key=key):
                changed = _raw({**UNIT, key: value})
                self.assertNotEqual(plan_push_payload_hash(changed), before)
                self.assertFalse(plan_push_hash_matches(changed, before))

    def test_legacy_raw_hash_is_accepted_while_the_payload_is_unchanged(self) -> None:
        raw = _raw(UNIT)
        legacy = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.assertTrue(plan_push_hash_matches(raw, legacy))
        self.assertTrue(plan_push_hash_matches(raw, legacy.upper()))
        self.assertFalse(plan_push_hash_matches(_raw({**UNIT, "name": "x"}), legacy))
        self.assertFalse(plan_push_hash_matches(raw, ""))

    def test_export_horizon_is_yesterday(self) -> None:
        today = date(2026, 11, 9)
        self.assertFalse(past_export_horizon("2026-11-08", today))
        self.assertTrue(past_export_horizon("2026-11-07", today))
        self.assertTrue(past_export_horizon("2026-10-01T00:00:00", today))
        self.assertFalse(past_export_horizon("", today))
        self.assertFalse(past_export_horizon(None, today))


def _state(store: SyncJobStore, job_id: str) -> dict:
    state = store.state(job_id)
    assert state is not None
    return state


class SettledItemsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(self, "jobs.sqlite", row_factory=sqlite3.Row)
        with self.manager.unit_of_work() as db:
            db.executescript(
                """
                CREATE TABLE sync_jobs (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, type TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, requested_by TEXT NOT NULL,
                    attempts INTEGER NOT NULL, progress_total INTEGER NOT NULL,
                    progress_completed INTEGER NOT NULL, error_class TEXT,
                    available_at TEXT, started_at TEXT, finished_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE sync_job_items (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, item_key TEXT NOT NULL,
                    operation TEXT NOT NULL, payload_hash TEXT NOT NULL, remote_id TEXT,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL, error_class TEXT,
                    error_detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(job_id, item_key)
                );
                CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT NOT NULL);
                """
            )
        ids = iter(f"id-{index}" for index in range(1000))
        self.store = SyncJobStore(self.manager, lambda: NOW, lambda: next(ids))

    def _states(self, job_id: str) -> dict[str, str]:
        return {
            item["item_key"]: item["status"]
            for item in _state(self.store, job_id)["items"]
        }

    def test_retry_reruns_only_open_items_and_never_downgrades_completed(
        self,
    ) -> None:
        entries = [
            {"library_workout_id": key, "expected_payload_hash": "a" * 64}
            for key in ("done", "retry")
        ]
        job, _ = self.store.enqueue(
            {
                "provider": "garmin",
                "type": "plan_push",
                "payload": {"entries": entries},
            },
            "user",
            [
                {"item_key": "done", "operation": "push"},
                {"item_key": "retry", "operation": "push"},
            ],
            None,
        )
        first = self.store.claim()
        assert first is not None
        self.assertEqual(first["settled_item_keys"], [])
        self.store.update_from_result(
            job["id"],
            {
                "results": [
                    {"library_workout_id": "done", "status": "synced"},
                    {"library_workout_id": "retry", "status": "error", "error": "x"},
                ]
            },
            "completed",
            str,
        )
        self.store.resolve(job["id"])
        claimed = self.store.claim()
        assert claimed is not None
        self.assertEqual(claimed["settled_item_keys"], ["done"])
        self.assertEqual(
            _unsettled_plan_entries({"entries": entries}, claimed["settled_item_keys"])[
                "entries"
            ],
            [entries[1]],
        )
        # A stale result for the completed item never turns it into a failure.
        self.store.update_from_result(
            job["id"],
            {
                "results": [
                    {"library_workout_id": "done", "status": "conflict", "error": "x"},
                    {"library_workout_id": "retry", "status": "synced"},
                ]
            },
            "completed",
            str,
        )
        self.assertEqual(
            self._states(job["id"]), {"done": "completed", "retry": "completed"}
        )
        self.assertEqual(_state(self.store, job["id"])["status"], "completed")

    def test_all_settled_keeps_the_payload(self) -> None:
        payload = {"entries": [{"library_workout_id": "a"}]}
        self.assertEqual(_unsettled_plan_entries(payload, ["a"]), payload)
        self.assertEqual(_unsettled_plan_entries(payload, None), payload)


class PlanningRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(self, "rows.db", row_factory=row_factory)
        with self.manager.unit_of_work() as db:
            create_remote_links_table(db)
            db.execute(
                "CREATE TABLE workout_library (id TEXT NOT NULL, local_id TEXT PRIMARY KEY, "
                "external_id TEXT, payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, "
                "sync_state TEXT NOT NULL, sync_error TEXT, last_synced_at TEXT, "
                "updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL, "
                "sync_error TEXT, sync_conflict TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            for local_id, day, state in (
                ("stuck", "2026-11-12", "syncing"),
                ("future", "2026-11-12", "local"),
                ("yesterday", "2026-11-08", "sync_error"),
                ("past", "2026-10-20", "sync_error"),
            ):
                db.execute(
                    "INSERT INTO planned_units VALUES (?, NULL, ?, 1, ?, NULL, '', 'old')",
                    (
                        local_id,
                        _raw({**UNIT, "type": "VirtualRide", "date": day}),
                        state,
                    ),
                )
        self.state = WorkoutLibrarySyncStateService(
            self.manager, Mock(), KeyValueRepository(lambda: NOW), lambda: NOW
        )

    def test_startup_offers_a_stranded_syncing_unit_again(self) -> None:
        self.assertEqual(self.state.reset_interrupted(), 1)
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT sync_state, sync_error FROM planned_units WHERE local_id='stuck'"
            ).fetchone()
        self.assertEqual(row["sync_state"], "sync_error")
        self.assertTrue(row["sync_error"])
        self.assertEqual(self.state.reset_interrupted(), 0)

    def test_units_before_the_export_horizon_are_not_pending(self) -> None:
        authority = PlanningAuthorityService(
            self.manager,
            self.state,
            Mock(),
            lambda: NOW,
            local_today=lambda: date(2026, 11, 9),
        )
        pending = {
            entry["library_workout_id"]
            for entry in authority.pending_plan_push_entries()
        }
        self.assertEqual(pending, {"future", "yesterday"})


if __name__ == "__main__":
    unittest.main()
