"""Small database primitives shared by the application."""

from __future__ import annotations

from typing import Any


def row_factory(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    """Return mapping-like rows for sqlite3 and SQLCipher backends."""
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


from .manager import DatabaseManager


__all__ = [
    "DatabaseManager",
    "row_factory",
]
