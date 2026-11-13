"""Every SQL statement on the equipment keys of the ``kv`` table (#2120).

Items, activity assignments, maintenance entries and sensor links are JSON
records under four key prefixes. Functions take the caller's connection;
transactions stay with the use case. Values are stored as the caller encoded
them.
"""

from __future__ import annotations

from typing import Any

EQUIPMENT_PREFIX = "equipment:"
ASSIGNMENT_PREFIX = "equipment_assignment:"
MAINTENANCE_PREFIX = "equipment_maintenance:"
SENSOR_EQUIPMENT_PREFIX = "sensor_equipment:"
GARMIN_INITIALIZED_KEY = "garmin_equipment_initialized"


def value(db: Any, key: str) -> str | None:
    row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return None if row is None else row["value"]


def values(db: Any, prefix: str, limit: int | None = None) -> list[str]:
    """Values under ``prefix``, newest first; a limit of None reads them all."""
    return [
        row["value"]
        for row in db.execute(
            "SELECT value FROM kv WHERE key LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (prefix + "%", -1 if limit is None else limit),
        ).fetchall()
    ]


def unordered_values(db: Any, prefix: str) -> list[str]:
    """Every value under ``prefix`` in table order, as the Garmin import reads them."""
    return [
        row["value"]
        for row in db.execute(
            "SELECT value FROM kv WHERE key LIKE ?", (prefix + "%",)
        ).fetchall()
    ]


def entries(db: Any, prefix: str) -> list[tuple[str, str]]:
    """(key without prefix, value) of every record under ``prefix``."""
    return [
        (row["key"][len(prefix) :], row["value"])
        for row in db.execute(
            "SELECT key, value FROM kv WHERE key LIKE ?", (prefix + "%",)
        ).fetchall()
    ]


def child_values(db: Any, parent_id: str) -> list[str]:
    return [
        row["value"]
        for row in db.execute(
            "SELECT value FROM kv WHERE key LIKE ? "
            "AND json_extract(value, '$.parent_id')=?",
            (EQUIPMENT_PREFIX + "%", parent_id),
        ).fetchall()
    ]


def is_referenced(db: Any, equipment_id: str) -> bool:
    """Whether an assignment, maintenance entry or sensor link names the item."""
    return (
        db.execute(
            "SELECT 1 FROM kv WHERE (key LIKE ? OR key LIKE ? OR key LIKE ?) "
            "AND json_extract(value, '$.equipment_id')=? LIMIT 1",
            (
                ASSIGNMENT_PREFIX + "%",
                MAINTENANCE_PREFIX + "%",
                SENSOR_EQUIPMENT_PREFIX + "%",
                equipment_id,
            ),
        ).fetchone()
        is not None
    )


def put(db: Any, key: str, text: str, updated_at: str) -> None:
    db.execute(
        "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE "
        "SET value=excluded.value,updated_at=excluded.updated_at",
        (key, text, updated_at),
    )


def insert(db: Any, key: str, text: str, updated_at: str) -> None:
    """Insert a new key; an existing key fails."""
    db.execute(
        "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)", (key, text, updated_at)
    )


def insert_if_absent(db: Any, key: str, text: str, updated_at: str) -> None:
    """Insert a new key; an existing key keeps its value."""
    db.execute(
        "INSERT OR IGNORE INTO kv(key,value,updated_at) VALUES(?,?,?)",
        (key, text, updated_at),
    )


def update(db: Any, key: str, text: str, updated_at: str) -> None:
    db.execute(
        "UPDATE kv SET value=?, updated_at=? WHERE key=?", (text, updated_at, key)
    )


def delete(db: Any, key: str) -> None:
    db.execute("DELETE FROM kv WHERE key=?", (key,))
