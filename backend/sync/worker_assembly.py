"""Composition for the single persistent sync worker."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.runtime.maintenance import MaintenanceGate
from backend.sync import worker


class SyncJobWorkerAssembly:
    """Create the worker from the queue and executor owners on demand."""

    def __init__(
        self,
        *,
        store: Callable[[], Any],
        executor: Callable[[], Any],
        maintenance_gate: MaintenanceGate,
        poll_seconds: float,
        wake_event: Callable[[], Any],
    ) -> None:
        self._store = store
        self._executor = executor
        self._maintenance_gate = maintenance_gate
        self._poll_seconds = poll_seconds
        self._wake_event = wake_event

    def create(self) -> worker.SyncJobWorker:
        """Create an unstarted worker using the shared queue wake event."""
        return worker.SyncJobWorker(
            self._store(),
            self._executor(),
            self._maintenance_gate,
            self._poll_seconds,
            wake_event=self._wake_event(),
        )
