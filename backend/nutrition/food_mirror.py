"""Local, permanent mirror of food records fetched from external databases."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import FoodDatabaseEntryRepository, database_origin
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
        with contextlib.suppress(Exception):
            self.refresh(foods)

    def refresh(self, foods: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Store fetched records with their gaps filled; return what is stored.

        A fresh record takes every value it has. A value it lacks is kept
        from the stored record when both count on the same basis unit, so a
        re-check fills gaps and never empties a known field.
        """
        if not foods:
            return []
        now = self._utc_now()
        with self._db_lock, self._database_manager().unit_of_work() as db:
            stored = []
            for food in foods:
                self._entries.upsert(
                    db, _filled(food, self._entries.get(db, str(food["id"]))), now
                )
                stored.append(self._entries.get(db, str(food["id"])))
        return [entry for entry in stored if entry is not None]

    def fill_gaps(self, food_id: str, source: dict[str, Any]) -> dict[str, Any] | None:
        """Fill a stored food's empty core values from another database's food.

        Only values on the same basis fill; known values stay. Each filled
        value names its origin and fetch time under ``filled_fields``.
        """
        with self._db_lock, self._database_manager().unit_of_work() as db:
            entry = self._entries.get(db, food_id)
            if entry is None or not _same_basis(entry, source):
                return entry
            values = source["per_100"]
            gaps = {
                key: values[key]
                for key, value in entry["per_100"].items()
                if value is None and values.get(key) is not None
            }
            if gaps:
                origin = database_origin(str(source["id"]))
                fetched_at = entry.pop("fetched_at")
                entry["per_100"].update(gaps)
                entry["filled_fields"] = {
                    **entry.get("filled_fields", {}),
                    **{
                        key: {"origin": origin, "fetched_at": self._utc_now()}
                        for key in gaps
                    },
                }
                self._entries.upsert(db, entry, fetched_at)
            return self._entries.get(db, food_id)

    def delete(self, food_id: str) -> None:
        with self._db_lock, self._database_manager().unit_of_work() as db:
            if not self._entries.delete(db, food_id):
                raise AppError(
                    404, "Datenbankeintrag nicht gefunden.", reason="food_not_found"
                )


def _filled(food: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
    """The fresh record, with stored values where it has none on the same basis."""
    if stored is None:
        return food
    filled = {
        **{
            key: value
            for key, value in stored.items()
            if key not in ("fetched_at", "per_100")
        },
        **{key: value for key, value in food.items() if value not in (None, "")},
    }
    # The basis is the fresh record's own; an unknown unit is never guessed.
    for key in ("basis_amount", "basis_unit"):
        filled[key] = food.get(key)
    per_100 = food.get("per_100")
    fresh: dict[str, Any] = per_100 if isinstance(per_100, dict) else {}
    same_basis = _same_basis(food, stored)
    # A filled value stays filled only while it is carried over unchanged; a
    # fresh value or another basis ends its origin.
    if "filled_fields" in filled:
        filled["filled_fields"] = {
            key: origin
            for key, origin in filled["filled_fields"].items()
            if same_basis and fresh.get(key) is None
        }
    filled["per_100"] = {
        **fresh,
        **{
            key: value
            for key, value in (stored["per_100"].items() if same_basis else ())
            if value is not None and fresh.get(key) is None
        },
    }
    return filled


def _same_basis(food: dict[str, Any], other: dict[str, Any]) -> bool:
    """Whether both records count their values on the same known basis."""
    return food.get("basis_unit") is not None and (
        food.get("basis_unit"),
        food.get("basis_amount"),
    ) == (other.get("basis_unit"), other.get("basis_amount"))
