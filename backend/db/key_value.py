"""Database unit-of-work access for application key/value state."""

from __future__ import annotations

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository


class KeyValueService:
    """Own key/value reads and writes across database unit-of-work boundaries."""

    def __init__(self, database: DatabaseManager, repository: KeyValueRepository) -> None:
        self._database = database
        self._repository = repository

    def get(self, key: str) -> str | None:
        with self._database.unit_of_work() as db:
            return self._repository.get(db, key)

    def set(self, key: str, value: str) -> None:
        with self._database.unit_of_work() as db:
            self._repository.set(db, key, value)
