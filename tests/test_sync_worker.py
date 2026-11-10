"""Isolated tests for the persistent sync-job worker runtime."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

from backend.db.manager import DatabaseManager
from backend.errors import AppError, DatabaseBusyError
from backend.runtime.events import StateEventBuffer
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.executor import SyncJobExecutor
from backend.sync.job_outcomes import SyncJobOutcomeService
from backend.sync.jobs import SyncJobStore
from backend.sync.worker import SyncJobWorker


class SyncJobWorkerTests(unittest.TestCase):
    def test_injected_wake_event_is_the_worker_signal(self) -> None:
        wake_event = threading.Event()
        worker = SyncJobWorker(
            object(),
            _RecordingRunner(),
            MaintenanceGate(),
            poll_seconds=1,
            wake_event=wake_event,
        )

        self.assertIs(worker.wake_event, wake_event)
        worker.wake()
        self.assertTrue(wake_event.is_set())

    def test_start_is_idempotent_under_concurrent_calls(self) -> None:
        claim_entered = threading.Event()
        release_claim = threading.Event()

        class BlockingStore:
            def claim(self) -> None:
                claim_entered.set()
                release_claim.wait(2)

        created: list[threading.Thread] = []

        def thread_factory(**kwargs: Any) -> threading.Thread:
            thread = threading.Thread(**kwargs)
            created.append(thread)
            return thread

        worker = SyncJobWorker(
            BlockingStore(),
            _RecordingRunner(),
            MaintenanceGate(),
            poll_seconds=2,
            thread_factory=thread_factory,
        )
        try:
            worker.start()
            self.assertTrue(claim_entered.wait(1))
            barrier = threading.Barrier(8)
            starters = [
                threading.Thread(target=lambda: (barrier.wait(), worker.start()))
                for _ in range(8)
            ]
            for starter in starters:
                starter.start()
            for starter in starters:
                starter.join(1)
                self.assertFalse(starter.is_alive())

            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].name, "sync-job-worker")
            self.assertTrue(created[0].daemon)
        finally:
            worker.stop()
            release_claim.set()
            _join_worker(worker)

    def test_claim_sets_generation_and_runs_job_inside_gate(self) -> None:
        job = {"id": "job-1"}

        class OneJobStore:
            claims = 0

            def claim(self) -> dict[str, Any] | None:
                self.claims += 1
                return job

        store = OneJobStore()
        gate = MaintenanceGate()
        runner = _StoppingRunner()
        worker = SyncJobWorker(store, runner, gate, poll_seconds=1)
        runner.worker = worker
        runner.gate = gate

        worker.run_loop()

        self.assertEqual(store.claims, 1)
        self.assertEqual(runner.jobs, [job])
        self.assertEqual(job["_maintenance_generation"], gate.current_generation())
        self.assertTrue(worker._stop_event.is_set())

    def test_empty_claim_waits_for_and_clears_wake_event(self) -> None:
        second_claim = threading.Event()

        class EmptyStore:
            claims = 0

            def claim(self) -> None:
                self.claims += 1
                if self.claims >= 2:
                    second_claim.set()

        store = EmptyStore()
        worker = SyncJobWorker(
            store, _RecordingRunner(), MaintenanceGate(), poll_seconds=5
        )
        worker.wake()
        try:
            worker.start()
            self.assertTrue(second_claim.wait(1))
            self.assertFalse(worker.wake_event.is_set())
        finally:
            worker.stop()
            _join_worker(worker)

    def test_maintenance_app_error_waits_without_crashing(self) -> None:
        entered = threading.Event()

        class MaintenanceBlockedGate:
            @contextmanager
            def operation(self):
                entered.set()
                raise AppError(503, "maintenance", reason="maintenance")
                yield

        class UnusedStore:
            def claim(self) -> None:
                raise AssertionError(
                    "claim must not run while maintenance blocks the operation"
                )

        worker = SyncJobWorker(
            UnusedStore(), _RecordingRunner(), MaintenanceBlockedGate(), poll_seconds=5
        )
        worker.start()
        self.assertTrue(entered.wait(1))
        worker.stop()
        _join_worker(worker)
        self.assertFalse(worker._worker_thread.is_alive())

    def test_non_maintenance_app_error_is_logged_and_worker_continues(self) -> None:
        class FlakyStore:
            claims = 0

            def claim(self) -> dict[str, str] | None:
                self.claims += 1
                if self.claims == 1:
                    raise AppError(500, "claim failed secret", reason="store_failure")
                if self.claims == 2:
                    return {"id": "job-1"}
                return None

        class FailingThenStoppingRunner:
            def run(self, job: dict[str, Any]) -> None:
                raise AppError(500, "runner failed secret", reason="runner_failure")

        store = FlakyStore()
        worker = SyncJobWorker(
            cast(SyncJobStore, store),
            FailingThenStoppingRunner(),
            MaintenanceGate(),
            poll_seconds=0,
        )

        def stop_on_third_claim() -> None:
            if store.claims >= 3:
                worker.stop()

        original_claim = store.claim

        def claim() -> dict[str, str] | None:
            result = original_claim()
            stop_on_third_claim()
            return result

        store.claim = claim  # type: ignore[method-assign]

        with patch("backend.sync.worker._LOGGER.error") as log_error:
            worker.run_loop()

        self.assertGreaterEqual(store.claims, 3)
        reasons = [call.kwargs["extra"]["reason"] for call in log_error.call_args_list]
        self.assertEqual(reasons, ["store_failure", "runner_failure"])
        self.assertNotIn("secret", repr(log_error.call_args_list))

    def test_transient_claim_error_keeps_worker_alive_without_replaying_job(
        self,
    ) -> None:
        class RecoveringStore:
            claims = 0

            def claim(self) -> dict[str, str] | None:
                self.claims += 1
                if self.claims == 1:
                    raise sqlite3.OperationalError("private detail")
                return {"id": "job-1"}

        store = RecoveringStore()
        runner = _StoppingRunner()
        worker = SyncJobWorker(store, runner, MaintenanceGate(), poll_seconds=0)
        runner.worker = worker
        runner.gate = worker._maintenance_gate

        with patch("backend.sync.worker._LOGGER.error") as log_error:
            worker.run_loop()

        self.assertEqual(store.claims, 2)
        self.assertEqual([job["id"] for job in runner.jobs], ["job-1"])
        self.assertEqual(
            log_error.call_args.kwargs["extra"]["error_class"], "OperationalError"
        )
        self.assertNotIn("private detail", repr(log_error.call_args))

    def test_runner_error_does_not_retry_claimed_effect_in_same_worker_loop(
        self,
    ) -> None:
        class TwoJobs:
            jobs = iter(({"id": "uncertain"}, {"id": "next"}))

            def claim(self) -> dict[str, str] | None:
                return next(self.jobs, None)

        class FailOnceRunner:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def run(self, job: dict[str, Any]) -> None:
                self.calls.append(job["id"])
                if job["id"] == "uncertain":
                    raise RuntimeError("effect may have completed")
                worker.stop()

        runner = FailOnceRunner()
        worker = SyncJobWorker(TwoJobs(), runner, MaintenanceGate(), poll_seconds=0)

        with patch("backend.sync.worker._LOGGER.error") as log_error:
            worker.run_loop()

        self.assertEqual(runner.calls, ["uncertain", "next"])
        self.assertEqual(
            log_error.call_args.kwargs["extra"]["error_class"], "RuntimeError"
        )

    def test_stop_wakes_worker_and_start_restarts_after_exit(self) -> None:
        claim_seen = threading.Event()

        class EmptyStore:
            claims = 0

            def claim(self) -> None:
                self.claims += 1
                claim_seen.set()

        store = EmptyStore()
        worker = SyncJobWorker(
            store, _RecordingRunner(), MaintenanceGate(), poll_seconds=5
        )
        worker.start()
        first_thread = worker._worker_thread
        self.assertTrue(claim_seen.wait(1))
        worker.stop()
        _join_worker(worker)
        self.assertFalse(first_thread.is_alive())

        claim_seen.clear()
        worker.start()
        second_thread = worker._worker_thread
        try:
            self.assertTrue(claim_seen.wait(1))
            self.assertIsNot(first_thread, second_thread)
            self.assertTrue(second_thread.is_alive())
        finally:
            worker.stop()
            _join_worker(worker)


class LostOutcomeTests(unittest.TestCase):
    """A job whose outcome cannot be stored must not stay running."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = DatabaseManager(
            Path(self.directory.name) / "jobs.sqlite",
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
        self.identifiers = iter(f"job-{index}" for index in range(1, 10))
        self.store = SyncJobStore(
            self.manager,
            lambda: datetime(2026, 11, 10, 8, 0, tzinfo=UTC).isoformat(),
            lambda: next(self.identifiers),
        )

    def test_row_does_not_stay_running_after_two_writer_timeouts(self) -> None:
        job, _ = self.store.enqueue(
            {"provider": "garmin", "type": "refresh", "payload": {}}, "test", None, None
        )
        outcomes = SyncJobOutcomeService(
            self.store,
            Mock(spec=StateEventBuffer),
            threading.Event(),
            str,
            Mock(),
            lambda: datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            retry_base_seconds=1,
            retry_max_seconds=2,
        )
        writer_down = {"down": True}

        class WriterTimeouts:
            """The real outcome service, whose writes time out while the writer is down."""

            def __getattr__(self, name: str) -> Any:
                if writer_down["down"]:
                    raise DatabaseBusyError("synthetic writer timeout")
                return getattr(outcomes, name)

        executor = SyncJobExecutor(
            historical_sync=Mock(),
            outcome_service=cast(SyncJobOutcomeService, WriterTimeouts()),
            all_sync_days=-1,
            job_owners={},
        )
        worker = SyncJobWorker(
            self.store,
            executor,
            MaintenanceGate(),
            poll_seconds=0,
            requeue_unowned=self.store.requeue_unowned_running,
        )
        runs: list[str] = []

        def finish_after_two_runs(claimed: dict[str, Any]) -> dict[str, Any]:
            state = self.store.state(claimed["id"])
            assert state is not None
            runs.append(state["status"])
            if len(runs) == 2:
                # The writer is back and this run ends the loop.
                writer_down["down"] = False
                worker.stop()
            return {"status": "ok"}

        # Without the requeue the row stays running and the loop would never end.
        watchdog = threading.Timer(5, worker.stop)
        self.addCleanup(watchdog.cancel)
        watchdog.start()
        with (
            patch.object(executor, "execute", side_effect=finish_after_two_runs),
            self.assertLogs("backend.sync.executor", level="ERROR"),
            self.assertLogs("backend.sync.worker", level="WARNING") as worker_logs,
        ):
            worker.run_loop()

        self.assertEqual(["running", "running"], runs)
        self.assertIn(
            "sync_job_outcome_lost",
            [r.__dict__.get("event") for r in worker_logs.records],
        )
        final = self.store.state(job["id"])
        assert final is not None
        self.assertEqual("completed", final["status"])
        self.assertEqual(2, final["attempts"])


class _RecordingRunner:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def run(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)


class _StoppingRunner(_RecordingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.worker: SyncJobWorker | None = None
        self.gate: MaintenanceGate | None = None

    def run(self, job: dict[str, Any]) -> None:
        super().run(job)
        assert self.worker is not None
        assert self.gate is not None
        if self.gate.active != 1:
            raise AssertionError("job runner must run inside the maintenance gate")
        self.worker.stop()


def _join_worker(worker: SyncJobWorker) -> None:
    thread = worker._worker_thread
    if thread is not None:
        thread.join(2)
        if thread.is_alive():
            raise AssertionError("sync worker did not stop")


if __name__ == "__main__":
    unittest.main()
