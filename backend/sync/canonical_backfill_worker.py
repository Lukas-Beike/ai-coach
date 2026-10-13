"""Background thread that runs the canonical backfill one writer transaction at a time.

Every batch runs inside the maintenance gate, outermost, and then the writer unit of
work, so a restore never overlaps a batch. The stop event is checked between
batches. A failed batch rolls back, and the failure is recorded as ``failed`` in its
own transaction; the next startup resumes from the last committed cursor.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Final

from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill import BatchReport, CanonicalBackfill

_LOGGER = logging.getLogger(__name__)
DEFAULT_POLL_SECONDS: Final = 5.0


class CanonicalBackfillWorker:
    def __init__(
        self,
        *,
        backfill: CanonicalBackfill,
        database: Callable[[], Any],
        maintenance_gate: MaintenanceGate,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ) -> None:
        self._backfill = backfill
        self._database = database
        self._maintenance_gate = maintenance_gate
        self._poll_seconds = poll_seconds
        self._thread_factory = thread_factory or threading.Thread
        self._stop_event = threading.Event()
        self._start_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the worker thread unless it is already alive."""
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = self._thread_factory(
                target=self.run_loop,
                name="canonical-backfill",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def run_loop(self) -> None:
        """Run batches until the backfill is complete, a batch fails, or stop is requested."""
        while not self._stop_event.is_set():
            try:
                report = self._run_batch()
            except AppError as exc:
                if exc.reason != "maintenance":
                    self._fail(exc)
                    return
                self._stop_event.wait(self._poll_seconds)
                continue
            except Exception as exc:  # noqa: BLE001 - a failed run is recorded, not raised
                self._fail(exc)
                return
            if report.done:
                return

    def _run_batch(self) -> BatchReport:
        with self._maintenance_gate.operation(), self._database().unit_of_work() as db:
            return self._backfill.run_batch(db)

    def _fail(self, exc: BaseException) -> None:
        _LOGGER.error(
            "Canonical backfill batch failed",
            extra={
                "event": "canonical_backfill_failed",
                "error_class": type(exc).__name__,
            },
        )
        try:
            with (
                self._maintenance_gate.operation(),
                self._database().unit_of_work() as db,
            ):
                self._backfill.mark_failed(db)
        except Exception as status_exc:  # noqa: BLE001 - logging only, no content
            _LOGGER.error(
                "Canonical backfill failure could not be recorded",
                extra={
                    "event": "canonical_backfill_status_failed",
                    "error_class": type(status_exc).__name__,
                },
            )
