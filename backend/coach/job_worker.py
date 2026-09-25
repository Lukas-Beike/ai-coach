"""Own the single process-local durable Coach job worker lifecycle."""

from __future__ import annotations

import threading
from collections.abc import Callable

from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.job_store import CoachJobStore
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class CoachJobWorker:
    """Poll durable claims and execute them without owning persisted job state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.wake_event = threading.Event()
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(
        self,
        jobs: Callable[[], CoachJobStore],
        runner: Callable[[], CoachBackgroundJobRunner],
        maintenance: MaintenanceGate,
    ) -> None:
        """Start at most one daemon after DB initialization and restart recovery."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.stop_event.clear()
            self._thread = threading.Thread(
                target=self.run_forever,
                args=(jobs, runner, maintenance),
                name="coach-job-worker",
                daemon=True,
            )
            self._thread.start()

    def run_forever(
        self,
        jobs: Callable[[], CoachJobStore],
        runner: Callable[[], CoachBackgroundJobRunner],
        maintenance: MaintenanceGate,
    ) -> None:
        """Keep claim and outcome within the outer maintenance operation."""
        while not self.stop_event.is_set():
            try:
                with maintenance.operation():
                    job = jobs().claim()
                    if job:
                        runner().run(job)
                        continue
            except AppError as exc:
                if exc.reason != "maintenance":
                    raise
            self.wake_event.wait(5)
            self.wake_event.clear()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)


COACH_JOB_WORKER = CoachJobWorker()
