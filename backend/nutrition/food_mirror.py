"""Local, permanent mirror of food records fetched from external databases."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import FoodDatabaseEntryRepository
from backend.errors import AppError

# Nutrition values rarely change; older entries are re-checked online when used.
MAX_AGE = timedelta(days=90)


class FoodDatabaseMirror:
    """Own storing, searching and expiry of mirrored external food records."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        db_lock: AbstractContextManager[Any],
        utc_now: Callable[[], str],
        repository: FoodDatabaseEntryRepository | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._utc_now = utc_now
        self._entries = repository or FoodDatabaseEntryRepository()

    def get(self, food_id: str) -> dict[str, Any] | None:
        with self._database_manager().reader() as db:
            return self._entries.get(db, food_id)

    def by_barcode(self, barcode: str) -> list[dict[str, Any]]:
        with self._database_manager().reader() as db:
            return self._entries.by_barcode(db, barcode)

    def search(
        self, query: str, *, limit: int = 8, offset: int = 0, prefix: str = ""
    ) -> list[dict[str, Any]]:
        with self._database_manager().reader() as db:
            return self._entries.search(
                db, query, limit=limit, offset=offset, prefix=prefix
            )

    def is_fresh(self, entry: dict[str, Any]) -> bool:
        try:
            fetched = datetime.fromisoformat(str(entry["fetched_at"]))
            now = datetime.fromisoformat(self._utc_now())
        except KeyError, ValueError:
            return False
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now - fetched < MAX_AGE

    def store(self, foods: list[dict[str, Any]]) -> None:
        """Keep fetched records; a failed write never breaks the lookup itself."""
        if not foods:
            return
        now = self._utc_now()
        with (
            contextlib.suppress(Exception),
            self._db_lock,
            self._database_manager().unit_of_work() as db,
        ):
            for food in foods:
                self._entries.upsert(db, food, now)

    def delete(self, food_id: str) -> None:
        with self._db_lock, self._database_manager().unit_of_work() as db:
            if not self._entries.delete(db, food_id):
                raise AppError(
                    404, "Datenbankeintrag nicht gefunden.", reason="food_not_found"
                )
