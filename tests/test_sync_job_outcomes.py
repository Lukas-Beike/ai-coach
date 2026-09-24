import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import Mock

from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.runtime.events import StateEventBuffer
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import SyncJobStore


class SyncJobOutcomeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "sync-jobs.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.manager.close)
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
                    UNIQUE(job_id, item_key),
                    FOREIGN KEY(job_id) REFERENCES sync_jobs(id) ON DELETE CASCADE
                );
                """
            )
        self.current_time = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        self.identifiers = iter(f"job-{index}" for index in range(1, 100))
        self.store = SyncJobStore(
            self.manager,
            lambda: self.current_time.isoformat(),
            lambda: next(self.identifiers),
        )
        self.publisher = StateEventBuffer()
        self.wake_event = Event()
        self.logger = Mock()
        self.service = SyncJobOutcomeService(
            self.store,
            self.publisher,
            self.wake_event,
            lambda value: value.replace("token-secret", "[REDACTED]"),
            self.logger,
            lambda: self.current_time,
            retry_base_seconds=10,
            retry_max_seconds=30,
        )

    def enqueue(self, operations=None):
        return self.store.enqueue(
            {"provider": "garmin", "type": "refresh", "payload": {}},
            "test",
            operations,
            None,
        )[0]

    def claim(self, job):
        claimed = self.store.claim()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], job["id"])
        return claimed

    def events(self):
        return self.publisher.since()["events"]

    def test_complete_maps_fallback_statuses_and_publishes_snapshots(self):
        completed = self.enqueue()
        self.assertEqual(
            self.service.complete(completed["id"], {"status": "ok"}), "completed"
        )
        self.assertEqual(self.events()[-1]["event"], "job")
        self.assertEqual(self.events()[-1]["data"]["status"], "completed")

        partial = self.enqueue()
        self.assertEqual(
            self.service.complete(partial["id"], {"status": "partial"}), "partial"
        )
        self.assertEqual(self.events()[-1]["data"]["status"], "partial")

        for result_status in ("error", "failed"):
            with self.subTest(result_status=result_status):
                failed = self.enqueue()
                self.assertEqual(
                    self.service.complete(failed["id"], {"status": result_status}),
                    "failed",
                )
                self.assertEqual(self.events()[-1]["data"]["status"], "failed")

    def test_complete_uses_store_item_aggregation_for_result_items(self):
        job = self.enqueue(
            [
                {"item_key": "workout-a", "operation": "push"},
                {"item_key": "workout-b", "operation": "push"},
            ]
        )
        fallback_status = self.service.complete(
            job["id"],
            {
                "results": [
                    {"item_key": "workout-a", "status": "synced"},
                    {
                        "item_key": "workout-b",
                        "status": "error",
                        "error": "token-secret",
                    },
                ]
            },
        )

        self.assertEqual(fallback_status, "completed")
        self.assertEqual(self.events()[-1]["data"]["status"], "partial")
        state = self.store.state(job["id"])
        self.assertEqual(
            [item["status"] for item in state["items"]], ["completed", "failed"]
        )
        self.assertEqual(state["items"][1]["error_detail"], "[REDACTED]")

    def test_already_running_raises_temporary_conflict_without_event(self):
        job = self.enqueue()

        with self.assertRaises(AppError) as raised:
            self.service.complete(job["id"], {"status": "already_running"})

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "temporary_error")
        self.assertEqual(self.events(), [])
        self.assertEqual(self.store.state(job["id"])["status"], "queued")

    def test_retryable_failure_requeues_wakes_and_publishes_no_event(self):
        job = self.enqueue()
        claimed = self.claim(job)
        exception = AppError(
            502,
            "Bearer token-secret " + "x" * 600,
            reason="provider_network_error",
        )

        self.service.record_failure(claimed, exception)

        state = self.store.state(job["id"])
        self.assertEqual(state["status"], "queued")
        self.assertEqual(state["available_at"], "2026-09-20T12:00:10+00:00")
        self.assertEqual(len(state["items"][0]["error_detail"]), 500)
        self.assertNotIn("token-secret", state["items"][0]["error_detail"])
        self.assertTrue(self.wake_event.is_set())
        self.assertEqual(self.events(), [])
        self.logger.error.assert_not_called()

    def test_nonretryable_failure_updates_publishes_and_logs_only_safe_context(self):
        job = self.enqueue()
        claimed = self.claim(job)

        self.service.record_failure(
            claimed, AppError(401, "token-secret", reason="auth_required")
        )

        self.assertEqual(self.store.state(job["id"])["status"], "failed")
        self.assertEqual(self.events()[-1]["event"], "job")
        self.assertEqual(self.events()[-1]["data"]["error_class"], "auth_required")
        self.assertFalse(self.wake_event.is_set())
        (message,) = self.logger.error.call_args.args
        extra = self.logger.error.call_args.kwargs["extra"]
        self.assertEqual(message, "Persistent synchronization job failed")
        self.assertNotIn("token-secret", message)
        self.assertEqual(
            extra["context"],
            {
                "job_id": job["id"],
                "provider": "garmin",
                "type": "refresh",
                "error_class": "auth_required",
            },
        )

    def test_exhausted_retry_updates_and_publishes_final_failure(self):
        job = self.enqueue()
        claimed = self.claim(job)
        claimed["attempts"] = 3

        self.service.record_failure(
            claimed, AppError(502, "temporary", reason="provider_network_error")
        )

        self.assertEqual(self.store.state(job["id"])["status"], "failed")
        self.assertEqual(self.events()[-1]["data"]["status"], "failed")
        self.assertEqual(self.events()[-1]["data"]["error_class"], "network_error")
        self.assertFalse(self.wake_event.is_set())
        self.logger.error.assert_called_once()

    def test_update_maps_invalid_status_and_missing_snapshot_is_ignored(self):
        job = self.enqueue()
        with self.assertRaisesRegex(ValueError, "invalid sync item status"):
            self.service.update(job["id"], "invalid")

        self.assertEqual(
            self.service.complete("missing", {"status": "ok"}), "completed"
        )
        self.service.update("missing", "failed")
        self.assertEqual(self.events(), [])
        self.assertEqual(self.store.state(job["id"])["status"], "queued")


if __name__ == "__main__":
    unittest.main()
