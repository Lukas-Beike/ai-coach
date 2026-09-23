"""Optimistic-concurrency revision state for local planning."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from backend.errors import AppError


class PlanningRevisionService:
    """Own revision increments and the explicit post-privacy reset state."""

    def __init__(self, repository: Any, now: Callable[[], str]):
        self._repository = repository
        self._now = now
        self._reset_lock = threading.Lock()
        self._reset_pending = False

    def mark_reset_pending(self) -> None:
        with self._reset_lock:
            self._reset_pending = True

    def bump(self, db: Any, amount: int = 1) -> None:
        if amount <= 0:
            return
        if self._repository.bump(db, int(amount), self._now()):
            return
        with self._reset_lock:
            if self._repository.bump(db, int(amount), self._now()):
                return
            if not self._reset_pending:
                raise AppError(
                    500,
                    "Die lokale Planrevision fehlt; die Datenbank muss repariert werden.",
                    reason="database_corrupt",
                )
            self._repository.initialize(db, self._now())
            self._reset_pending = False
            if not self._repository.bump(db, int(amount), self._now()):
                raise AppError(
                    500,
                    "Die lokale Planrevision fehlt; die Datenbank muss repariert werden.",
                    reason="database_corrupt",
                )

    def read(self, db: Any) -> int:
        return self._repository.read(db)
