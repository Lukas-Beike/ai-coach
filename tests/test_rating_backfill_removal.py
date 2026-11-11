"""One-time removal of the retired Garmin rating backfill's state (#2067)."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import Mock

from test_sync_queue import SyncQueueFixtureMixin

from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.sync.executor import SyncJobExecutor
from backend.sync.jobs import JOB_TYPES
from backend.sync.rating_backfill_removal import (
    RETIRED_JOB_TYPE,
    RETIRED_STATE_KEY,
    STATE_KEY,
    RatingBackfillRemoval,
)

NOW = "2026-11-11T08:00:00+00:00"
FINISHED = json.dumps({"finished": True, "backfilled": 12, "skipped_ids": ["7"]})


class RatingBackfillRemovalTests(SyncQueueFixtureMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE provider_sync_cursors (provider TEXT NOT NULL, "
                "stream TEXT NOT NULL, cursor TEXT, high_water_mark TEXT, "
                "updated_at TEXT, PRIMARY KEY(provider, stream))"
            )
        self.key_values = KeyValueRepository(lambda: NOW)
        self.stage = RatingBackfillRemoval(
            key_values=self.key_values, clock=lambda: NOW
        )

    def add_job(self, job_id: str, job_type: str, status: str) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO sync_jobs(id, provider, type, status, payload, "
                "requested_by, attempts, progress_total, progress_completed, "
                "created_at, updated_at) VALUES (?, 'garmin', ?, ?, '{}', 'startup', "
                "0, 1, 0, ?, ?)",
                (job_id, job_type, status, NOW, NOW),
            )
            db.execute(
                "INSERT INTO sync_job_items(id, job_id, item_key, operation, "
                "payload_hash, status, attempts, created_at, updated_at) "
                "VALUES (?, ?, 'k', 'sync', 'h', ?, 0, ?, ?)",
                (f"item-{job_id}", job_id, status, NOW, NOW),
            )

    def seed(self) -> None:
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, RETIRED_STATE_KEY, FINISHED)
            self.key_values.set(db, "stream_backfill_state:garmin", "{}")
            self.key_values.set(db, "garmin_rating_backfill_state_other", "kept")
            for stream in ("rating_history", "stream_history"):
                db.execute(
                    "INSERT INTO provider_sync_cursors(provider, stream, cursor) "
                    "VALUES ('garmin', ?, '2000-01-01')",
                    (stream,),
                )
        for status in ("queued", "running", "failed", "completed"):
            self.add_job(f"old-{status}", RETIRED_JOB_TYPE, status)
        self.add_job("kept-stream", "stream_backfill", "queued")

    def run_stage(self) -> Any:
        with self.manager.unit_of_work() as db:
            return self.stage.run_batch(db)

    def rows(self, sql: str) -> list[Any]:
        with self.manager.reader() as db:
            return [tuple(row) for row in db.execute(sql).fetchall()]

    def test_only_the_backfills_own_keys_cursor_and_jobs_are_removed(self) -> None:
        self.seed()

        report = self.run_stage()

        self.assertTrue(report.done)
        self.assertEqual(
            [
                ("garmin_rating_backfill_state_other",),
                (STATE_KEY,),
                ("stream_backfill_state:garmin",),
            ],
            self.rows("SELECT key FROM kv ORDER BY key"),
        )
        self.assertEqual(
            [("stream_history",)],
            self.rows("SELECT stream FROM provider_sync_cursors"),
        )
        self.assertEqual(
            [
                ("kept-stream", "stream_backfill", "queued"),
                ("old-completed", RETIRED_JOB_TYPE, "completed"),
                ("old-failed", RETIRED_JOB_TYPE, "failed"),
            ],
            self.rows("SELECT id, type, status FROM sync_jobs ORDER BY id"),
        )
        self.assertEqual(
            [("item-kept-stream",), ("item-old-completed",), ("item-old-failed",)],
            self.rows("SELECT id FROM sync_job_items ORDER BY id"),
        )
        with self.manager.reader() as db:
            state = json.loads(self.key_values.get(db, STATE_KEY) or "{}")
        self.assertEqual(
            {"state_keys": 1, "cursors": 1, "job_items": 2, "jobs": 2},
            state["removed"],
        )

    def test_a_database_without_the_keys_completes_and_a_rerun_changes_nothing(
        self,
    ) -> None:
        self.assertTrue(self.run_stage().done)
        self.seed()

        report = self.run_stage()

        self.assertEqual((0, True), (report.items, report.done))
        self.assertEqual(5, len(self.rows("SELECT id FROM sync_jobs")))

    def test_a_stored_job_of_the_removed_type_is_listed_and_fails_cleanly(
        self,
    ) -> None:
        self.add_job("old-queued", RETIRED_JOB_TYPE, "queued")
        self.add_job("old-completed", RETIRED_JOB_TYPE, "completed")
        self.assertNotIn(RETIRED_JOB_TYPE, JOB_TYPES)

        listed = self.store.list(50)
        claimed = self.store.claim()

        self.assertEqual({"old-queued", "old-completed"}, {job["id"] for job in listed})
        self.assertEqual({RETIRED_JOB_TYPE}, {job["type"] for job in listed})
        self.assertIsNotNone(claimed)
        executor = SyncJobExecutor(
            job_owners={"garmin": Mock()},
            historical_sync=Mock(),
            outcome_service=Mock(),
            all_sync_days=-1,
        )
        with self.assertRaises(AppError) as raised:
            executor.execute(claimed)
        self.assertEqual("invalid_job_request", raised.exception.reason)

    def test_mark_failed_keeps_the_state_and_the_stage_runs_again(self) -> None:
        self.seed()
        with self.manager.unit_of_work() as db:
            self.stage.mark_failed(db)
            self.assertEqual(
                "failed",
                json.loads(self.key_values.get(db, STATE_KEY) or "{}")["status"],
            )

        self.assertGreater(self.run_stage().items, 0)
        self.assertEqual(
            [("kept-stream",), ("old-completed",), ("old-failed",)],
            self.rows("SELECT id FROM sync_jobs ORDER BY id"),
        )


if __name__ == "__main__":
    unittest.main()
