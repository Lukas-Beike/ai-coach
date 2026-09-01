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


class CheckinRepository:
    """Persist and retrieve athlete check-ins without owning a connection."""

    def __init__(self, now: Callable[[], str]):
        self._now = now

    def list(self, db: Any, limit: int = 30) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT checkin_date, soreness, stress, motivation, session_rpe, day_form, illness, pain, "
            "available_minutes, availability_notes, notes, created_at, updated_at "
            "FROM athlete_checkins ORDER BY checkin_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert(self, db: Any, checkin: dict[str, Any]) -> None:
        now = self._now()
        db.execute(
            "INSERT INTO athlete_checkins(checkin_date, soreness, stress, motivation, session_rpe, day_form, illness, pain, "
            "available_minutes, availability_notes, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(checkin_date) DO UPDATE SET soreness=excluded.soreness, stress=excluded.stress, "
            "motivation=excluded.motivation, session_rpe=excluded.session_rpe, day_form=excluded.day_form, illness=excluded.illness, "
            "pain=excluded.pain, available_minutes=excluded.available_minutes, "
            "availability_notes=excluded.availability_notes, notes=excluded.notes, updated_at=excluded.updated_at",
            (
                checkin["checkin_date"], checkin["soreness"], checkin["stress"], checkin["motivation"],
                checkin["session_rpe"], checkin["day_form"], checkin["illness"], checkin["pain"], checkin["available_minutes"],
                checkin["availability_notes"], checkin["notes"], now, now,
            ),
        )
