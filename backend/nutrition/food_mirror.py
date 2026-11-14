"""Local, permanent mirror of food records fetched from external databases."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from backend import change_history
from backend.db.manager import DatabaseManager
from backend.db.repositories import (
    MANUAL_ORIGIN,
    NUTRIENT_COLUMNS,
    FoodDatabaseEntryRepository,
    database_origin,
    fill_empty_nutrients,
)
from backend.errors import AppError

# Nutrition values rarely change; older entries are re-checked online when used.
MAX_AGE = timedelta(days=90)
FOOD_ENTITY_TYPE = "food_database_entry"


def food_history_value(entry: dict[str, Any]) -> dict[str, Any]:
    """The nutrient values of a stored food as change history records them."""
    return {
        "id": entry["id"],
        "basis_amount": entry["basis_amount"],
        "basis_unit": entry["basis_unit"],
        **{key: entry["per_100"].get(key) for key in NUTRIENT_COLUMNS},
        "filled_fields": entry.get("filled_fields", {}),
    }


class FoodDatabaseMirror:
    """Own storing, searching and expiry of mirrored external food records."""

    def __init__(
        self,
        database_manager: Callable[[], DatabaseManager],
        utc_now: Callable[[], str],
        repository: FoodDatabaseEntryRepository | None = None,
    ) -> None:
        self._database_manager = database_manager
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
        re-check fills gaps and never empties a known field. A value the
        athlete edited stays even when the fresh record has one.
        """
        if not foods:
            return []
        now = self._utc_now()
        with self._database_manager().unit_of_work() as db:
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
        with self._database_manager().unit_of_work() as db:
            entry = self._entries.get(db, food_id)
            if entry is None or not _same_basis(entry, source):
                return entry
            values = source["per_100"]
            fill_empty_nutrients(
                db,
                food_id,
                {
                    key: values[key]
                    for key in NUTRIENT_COLUMNS
                    if values.get(key) is not None
                },
                origin=database_origin(str(source["id"])),
                fetched_at=self._utc_now(),
            )
            return self._entries.get(db, food_id)

    def current(
        self, db: Any, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The stored food of one recorded change, for change history."""
        entry = self._entries.get(db, entity_id)
        value = None if entry is None else food_history_value(entry)
        return value, change_history.audit_projection(FOOD_ENTITY_TYPE, value)

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Empty the nutrient fields a gap fill wrote; other values stay as they are."""
        entry = self._entries.get(db, entity_id)
        if current is None or target is None or entry is None:
            raise AppError(409, "Der Datenbankeintrag ist nicht mehr verfügbar.")
        # Only the fields the undone change wrote: others keep value and origin.
        self._entries.restore_nutrients(
            db,
            entity_id,
            {
                key: value
                for key, value in target.items()
                if key in NUTRIENT_COLUMNS and current.get(key) != value
            },
            target.get("filled_fields"),
        )
        restored = self._entries.get(db, entity_id)
        return food_history_value(restored) if restored else {}

    def delete(self, food_id: str) -> None:
        with self._database_manager().unit_of_work() as db:
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
    # The athlete's edits win over the database while the basis is the same.
    edited = {
        key
        for key, origin in stored.get("filled_fields", {}).items()
        if same_basis and origin.get("origin") == MANUAL_ORIGIN
    }
    # A filled value stays filled only while it is carried over unchanged; a
    # fresh value or another basis ends its origin.
    if "filled_fields" in filled:
        filled["filled_fields"] = {
            key: origin
            for key, origin in {
                **filled["filled_fields"],
                **{key: stored["filled_fields"][key] for key in edited},
            }.items()
            if same_basis and (fresh.get(key) is None or key in edited)
        }
    filled["per_100"] = {
        **fresh,
        **{
            key: value
            for key, value in (stored["per_100"].items() if same_basis else ())
            if value is not None and (fresh.get(key) is None or key in edited)
        },
    }
    return filled


def _same_basis(food: dict[str, Any], other: dict[str, Any]) -> bool:
    """Whether both records count their values on the same known basis."""
    return food.get("basis_unit") is not None and (
        food.get("basis_unit"),
        food.get("basis_amount"),
    ) == (other.get("basis_unit"), other.get("basis_amount"))
