"""Coordinate ordinary operations with destructive maintenance work."""

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any

from backend.errors import AppError

# Bound for draining running work before a restore or destructive delete; the
# browser gives up after about 25 s, so the athlete sees the real result.
RESTORE_DRAIN_TIMEOUT_SECONDS = 20.0


class MaintenanceGate:
    """Drain operations and invalidate claimed work during maintenance."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.active = 0
        self.restoring = False
        self.generation = 0
        self.local = threading.local()

    @contextmanager
    def operation(self, expected_generation: int | None = None):
        with self.condition:
            depth = getattr(self.local, "depth", 0)
            if (
                expected_generation is not None
                and expected_generation != self.generation
            ):
                raise AppError(
                    409,
                    "Der Auftrag wurde durch eine Datenlöschung verworfen.",
                    reason="operation_invalidated",
                )
            if not depth:
                if self.restoring:
                    raise AppError(
                        503,
                        "Die Anwendung befindet sich gerade im Wartungsmodus. Bitte später erneut versuchen.",
                        reason="maintenance",
                    )
                self.active += 1
            self.local.depth = depth + 1
        try:
            yield
        finally:
            with self.condition:
                self.local.depth -= 1
                if not self.local.depth:
                    self.active -= 1
                self.condition.notify_all()

    @contextmanager
    def restore(
        self,
        before_wait: Callable[[], None] | None = None,
        *,
        timeout: float | None = None,
    ):
        """Block new operations, ask running work to stop, then drain it.

        ``before_wait`` runs outside the gate lock once ordinary operations are
        refused, so it can cancel running Coach turns. The drain is bounded: on
        timeout nothing has changed and the caller gets a retryable 409.
        """
        with self.condition:
            if self.restoring:
                raise AppError(409, "Eine Datenbankwiederherstellung läuft bereits.")
            self.restoring = True
            nested = bool(getattr(self.local, "depth", 0))
            if nested:
                self.active -= 1
        try:
            if before_wait is not None:
                before_wait()
            with self.condition:
                deadline = time.monotonic() + (
                    RESTORE_DRAIN_TIMEOUT_SECONDS if timeout is None else timeout
                )
                while self.active:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AppError(
                            409,
                            "Laufende Aufgaben, etwa eine Coach-Antwort, werden noch "
                            "beendet. Es wurde nichts geändert. Bitte gleich erneut versuchen.",
                            reason="maintenance_drain_timeout",
                        )
                    self.condition.wait(remaining)
                self.generation += 1
        except BaseException:
            self._finish_restore(nested)
            raise
        try:
            yield
        finally:
            self._finish_restore(nested)

    def _finish_restore(self, nested: bool) -> None:
        with self.condition:
            self.restoring = False
            if nested:
                self.active += 1
            self.condition.notify_all()

    def current_generation(self) -> int:
        with self.condition:
            return self.generation

    def state(self) -> dict[str, Any]:
        with self.condition:
            return {"active": self.restoring, "running_operations": self.active}


MAINTENANCE_GATE = MaintenanceGate()


def maintenance_operation(function: Any) -> Any:
    @wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        with MAINTENANCE_GATE.operation():
            return function(*args, **kwargs)

    return guarded


def claimed_maintenance_operation(function: Any) -> Any:
    """Keep claimed payloads and their success/failure writes in one generation."""

    @wraps(function)
    def guarded(job: dict[str, Any]) -> Any:
        try:
            with MAINTENANCE_GATE.operation(job["_maintenance_generation"]):
                return function(job)
        except AppError as exc:
            if exc.reason not in {"operation_invalidated", "maintenance"}:
                raise

    return guarded
