"""Database unit-of-work access for application key/value state."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository


class KeyValueService:
    """Own key/value reads and writes across database unit-of-work boundaries."""

    def __init__(
        self,
        database: DatabaseManager,
        repository: KeyValueRepository,
        db_lock: Any | None = None,
    ) -> None:
        self._database = database
        self._repository = repository
        self._db_lock = db_lock

    def get(self, key: str) -> str | None:
        lock = self._db_lock if self._db_lock is not None else nullcontext()
        with lock, self._database.unit_of_work() as db:
            return self._repository.get(db, key)

    def set(self, key: str, value: str) -> None:
        lock = self._db_lock if self._db_lock is not None else nullcontext()
        with lock, self._database.unit_of_work() as db:
            self._repository.set(db, key, value)
