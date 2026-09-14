"""Database operations for provider synchronization cursors."""

from __future__ import annotations

from typing import Any


def read_cursor(db: Any, provider: str, stream: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT provider, stream, cursor, high_water_mark, updated_at "
        "FROM provider_sync_cursors WHERE provider=? AND stream=?",
        (provider, stream),
    ).fetchone()
    return dict(row) if row else {
        "provider": provider, "stream": stream, "cursor": None,
        "high_water_mark": None, "updated_at": None,
    }


def write_cursor(
    db: Any, provider: str, stream: str, cursor: str,
    high_water_mark: str | None, updated_at: str,
) -> None:
    db.execute(
        "INSERT INTO provider_sync_cursors(provider, stream, cursor, high_water_mark, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(provider, stream) DO UPDATE SET "
        "cursor=excluded.cursor, high_water_mark=excluded.high_water_mark, updated_at=excluded.updated_at",
        (str(provider)[:40], str(stream)[:80], str(cursor)[:120], str(high_water_mark or "")[:120], updated_at),
    )
