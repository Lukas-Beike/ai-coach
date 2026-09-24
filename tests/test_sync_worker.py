"""Isolated tests for the persistent sync-job worker runtime."""

from __future__ import annotations

import threading
import unittest
from contextlib import contextmanager
from typing import Any

from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
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

    def test_non_maintenance_app_error_remains_visible(self) -> None:
        class FailingStore:
            def claim(self) -> None:
                raise AppError(500, "claim failed", reason="store_failure")

        worker = SyncJobWorker(
            FailingStore(), _RecordingRunner(), MaintenanceGate(), poll_seconds=1
        )

        with self.assertRaisesRegex(AppError, "claim failed"):
            worker.run_loop()

        class FailingRunner:
            def run(self, job: dict[str, Any]) -> None:
                raise AppError(500, "runner failed", reason="runner_failure")

        class OneJobStore:
            def claim(self) -> dict[str, str]:
                return {"id": "job-1"}

        worker = SyncJobWorker(
            OneJobStore(), FailingRunner(), MaintenanceGate(), poll_seconds=1
        )
        with self.assertRaisesRegex(AppError, "runner failed"):
            worker.run_loop()

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
