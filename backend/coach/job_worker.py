"""Own the single process-local durable Coach job worker lifecycle."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.job_store import CoachJobStore
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate

_LOGGER = logging.getLogger(__name__)


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
        recover: Callable[[], Any],
    ) -> None:
        """Start at most one daemon after DB initialization and restart recovery."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.stop_event.clear()
            self._thread = threading.Thread(
                target=self.run_forever,
                args=(jobs, runner, maintenance, recover),
                name="coach-job-worker",
                daemon=True,
            )
            self._thread.start()

    def run_forever(
        self,
        jobs: Callable[[], CoachJobStore],
        runner: Callable[[], CoachBackgroundJobRunner],
        maintenance: MaintenanceGate,
        recover: Callable[[], Any],
    ) -> None:
        """Recover claimed work after runner or outcome persistence failures."""
        recovery_pending = False
        while not self.stop_event.is_set():
            if recovery_pending:
                try:
                    with maintenance.operation():
                        recover()
                    recovery_pending = False
                except AppError as exc:
                    if exc.reason != "maintenance":
                        self._log_failure("coach_worker_recovery_failed", exc)
                except Exception as exc:  # noqa: BLE001 - retry interrupted-state recovery
                    self._log_failure("coach_worker_recovery_failed", exc)
                if recovery_pending:
                    self.wake_event.wait(5)
                    self.wake_event.clear()
                    continue

            job = None
            try:
                with maintenance.operation():
                    job = jobs().claim()
                    if job:
                        runner().run(job)
                        continue
            except AppError as exc:
                if job is not None:
                    recovery_pending = True
                if exc.reason != "maintenance":
                    self._log_failure("coach_worker_iteration_failed", exc)
            except Exception as exc:  # noqa: BLE001 - survive transient claim failures
                if job is not None:
                    recovery_pending = True
                self._log_failure("coach_worker_iteration_failed", exc)
            self.wake_event.wait(5)
            self.wake_event.clear()

    @staticmethod
    def _log_failure(event: str, error: Exception) -> None:
        _LOGGER.error(
            "Coach worker iteration failed",
            extra={
                "event": event,
                "error_class": type(error).__name__,
                "reason": getattr(error, "reason", None),
            },
        )

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)


COACH_JOB_WORKER = CoachJobWorker()
