"""Explicit persistence interfaces for application repositories."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class KeyValueRepository:
    """Read and write the application's durable key/value settings."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def get(self, db: Any, key: str) -> str | None:
        row = db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, db: Any, key: str, value: str) -> None:
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, self._now()),
        )


class ChatRepository:
    """Persist and retrieve local chat messages without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def add(self, db: Any, role: str, content: str) -> dict[str, Any]:
        created_at = self._now()
        clean_content = content.strip()
        cursor = db.execute(
            "INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)",
            (role, clean_content, created_at),
        )
        return {"id": cursor.lastrowid, "role": role, "content": clean_content, "created_at": created_at}

    def list(self, db: Any, limit: int = 100) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT id, role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
