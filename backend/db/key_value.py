"""Database unit-of-work access for application key/value state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository


class KeyValueService:
    """Own key/value reads and writes across database unit-of-work boundaries."""

    def __init__(
        self,
        database: DatabaseManager | Callable[[], DatabaseManager],
        repository: KeyValueRepository,
    ) -> None:
        self._database = database
        self._repository = repository

    def get(self, key: str) -> str | None:
        # A single-row read does not need the writer. It
        # joins an active unit of work or read snapshot, so callers inside one
        # still observe that transaction; otherwise it sees committed state.
        with self._manager().reader() as db:
            return self.get_in_transaction(db, key)

    def get_in_transaction(self, db: Any, key: str) -> str | None:
        return self._repository.get(db, key)

    def set(self, key: str, value: str) -> None:
        with self._manager().unit_of_work() as db:
            self._repository.set(db, key, value)

    def _manager(self) -> Any:
        return self._database() if callable(self._database) else self._database
