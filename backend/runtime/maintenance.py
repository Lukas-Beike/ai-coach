"""Coordinate ordinary operations with destructive maintenance work."""

import threading
from contextlib import contextmanager
from functools import wraps
from typing import Any

from backend.errors import AppError


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
            if expected_generation is not None and expected_generation != self.generation:
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
    def restore(self):
        with self.condition:
            if self.restoring:
                raise AppError(409, "Eine Datenbankwiederherstellung läuft bereits.")
            self.restoring = True
            nested = bool(getattr(self.local, "depth", 0))
            if nested:
                self.active -= 1
            while self.active:
                self.condition.wait()
            self.generation += 1
        try:
            yield
        finally:
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
