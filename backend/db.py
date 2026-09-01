"""Small database primitives shared by the application and migrations."""

from __future__ import annotations

from typing import Any


def row_factory(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    """Return mapping-like rows for sqlite3 and SQLCipher backends."""
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


def schema_version(db: Any) -> int:
    """Read the monotone schema version without depending on application state."""
    try:
        row = db.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    except Exception:
        return 0
    try:
        if not row:
            return 0
        try:
            value = row["version"]
        except (KeyError, TypeError, IndexError):
            value = row[0]
        return int(value or 0)
    except (KeyError, TypeError, IndexError, ValueError):
        return 0
