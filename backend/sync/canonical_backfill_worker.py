"""Background thread that runs the canonical backfill one writer transaction at a time.

Every batch runs inside the maintenance gate, outermost, and then the writer unit of
work, so a restore never overlaps a batch. The stop event is checked between
batches. A failed batch rolls back, and the failure is recorded as ``failed`` in its
own transaction; the next startup resumes from the last committed cursor.
Batches run as background writers, so a waiting foreground request (a login,
for example) is served between two batches instead of queuing behind the loop.

Follow-up stages run one after another once the canonical backfill is complete. Each
keeps its own state, so a failed follow-up is recorded on its own and leaves the
canonical backfill complete.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any, Final, Protocol

from backend.db.manager import background_writer
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.sync.canonical_backfill import BatchReport, CanonicalBackfill

_LOGGER = logging.getLogger(__name__)
DEFAULT_POLL_SECONDS: Final = 5.0


class BatchStage(Protocol):
    """A resumable stage that writes one batch per transaction."""

    def run_batch(self, db: Any) -> BatchReport: ...

    def mark_failed(self, db: Any) -> None: ...


class BackfillStage(BatchStage, Protocol):
    """A follow-up stage, named for the logs, that runs after the canonical backfill."""

    @property
    def stage(self) -> str: ...


class CanonicalBackfillWorker:
    def __init__(
        self,
        *,
        backfill: CanonicalBackfill,
        database: Callable[[], Any],
        maintenance_gate: MaintenanceGate,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        thread_factory: Callable[..., threading.Thread] | None = None,
        followups: Sequence[BackfillStage] = (),
    ) -> None:
        self._backfill = backfill
        self._database = database
        self._maintenance_gate = maintenance_gate
        self._poll_seconds = poll_seconds
        self._thread_factory = thread_factory or threading.Thread
        self._followups = tuple(followups)
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
        with background_writer():
            self._run_batches()

    def _run_batches(self) -> None:
        """Run the canonical backfill to completion, then each follow-up in order."""
        if not self._run_stage(self._backfill, "canonical"):
            return
        for followup in self._followups:
            if not self._run_stage(followup, followup.stage):
                return

    def _run_stage(self, stage: BatchStage, name: str) -> bool:
        """Run one stage's batches; return True once it is complete."""
        while not self._stop_event.is_set():
            try:
                report = self._run_batch(stage)
            except AppError as exc:
                if exc.reason != "maintenance":
                    self._fail(stage, name, exc)
                    return False
                self._stop_event.wait(self._poll_seconds)
                continue
            except Exception as exc:  # noqa: BLE001 - a failed run is recorded, not raised
                self._fail(stage, name, exc)
                return False
            if report.done:
                return True
        return False

    def _run_batch(self, stage: BatchStage) -> BatchReport:
        with self._maintenance_gate.operation(), self._database().unit_of_work() as db:
            return stage.run_batch(db)

    def _fail(self, stage: BatchStage, name: str, exc: BaseException) -> None:
        _LOGGER.error(
            "Canonical backfill batch failed",
            extra={
                "event": "canonical_backfill_failed",
                "stage": name,
                "error_class": type(exc).__name__,
            },
        )
        try:
            with (
                self._maintenance_gate.operation(),
                self._database().unit_of_work() as db,
            ):
                stage.mark_failed(db)
        except Exception as status_exc:  # noqa: BLE001 - logging only, no content
            _LOGGER.error(
                "Canonical backfill failure could not be recorded",
                extra={
                    "event": "canonical_backfill_status_failed",
                    "stage": name,
                    "error_class": type(status_exc).__name__,
                },
            )
