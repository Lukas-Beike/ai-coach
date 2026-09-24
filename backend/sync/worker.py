"""Persistent worker runtime for provider-independent synchronization jobs."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Protocol

from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.jobs import SyncJobStore

_SYNC_JOB_WAKE_EVENT = threading.Event()


def shared_sync_job_wake_event() -> threading.Event:
    """Return the process-wide wake signal shared by queue, outcome, and worker."""
    return _SYNC_JOB_WAKE_EVENT


class SyncJobRunner(Protocol):
    """Execute one claimed sync job synchronously."""

    def run(self, job: dict[str, Any]) -> None: ...


class SyncJobWorker:
    """Claim and run persistent jobs on one restartable daemon thread."""

    def __init__(
        self,
        store: SyncJobStore,
        runner: SyncJobRunner,
        maintenance_gate: MaintenanceGate,
        poll_seconds: float,
        *,
        thread_factory: Callable[..., threading.Thread] | None = None,
        wake_event: threading.Event | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._maintenance_gate = maintenance_gate
        self._poll_seconds = poll_seconds
        self._thread_factory = thread_factory or threading.Thread
        self._start_lock = threading.Lock()
        self._wake_event = wake_event or threading.Event()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

    @property
    def wake_event(self) -> threading.Event:
        """Return the shared event used to wake this worker after enqueue."""
        return self._wake_event

    def start(self) -> None:
        """Start the worker unless its current thread is already alive."""
        with self._start_lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return
            self._stop_event.clear()
            self._worker_thread = self._thread_factory(
                target=self.run_loop,
                name="sync-job-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def wake(self) -> None:
        self._wake_event.set()

    def stop(self) -> None:
        with self._start_lock:
            self._stop_event.set()
            self._wake_event.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._worker_thread
        if thread is not None:
            thread.join(timeout)

    def run_loop(self) -> None:
        """Run claims until stopped; non-maintenance errors remain visible."""
        while not self._stop_event.is_set():
            try:
                with self._maintenance_gate.operation():
                    job = self._store.claim()
                    if job is not None:
                        job["_maintenance_generation"] = (
                            self._maintenance_gate.current_generation()
                        )
                        self._runner.run(job)
                        continue
            except AppError as exc:
                if exc.reason != "maintenance":
                    raise

            self._wake_event.wait(self._poll_seconds)
            self._wake_event.clear()
