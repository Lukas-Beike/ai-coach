"""Seed a stored provider snapshot for tests; production never writes one."""

from __future__ import annotations

import json
from typing import Any


def store_snapshot(
    db: Any,
    snapshot: dict[str, Any],
    created_at: str,
    *,
    keep: int = 12,
    activity_count: int | None = None,
) -> None:
    """Insert one stored snapshot row and keep the newest ``keep`` rows."""
    recent = snapshot.get("recent_activities")
    if activity_count is None:
        activity_count = len(recent) if isinstance(recent, list) else 0
    db.execute(
        "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
        "VALUES (?, ?, ?, ?)",
        (
            json.dumps(snapshot, ensure_ascii=False),
            created_at,
            str(snapshot.get("synced_at") or ""),
            activity_count,
        ),
    )
    db.execute(
        "DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)",
        (keep,),
    )


def latest_payload(db: Any) -> str | None:
    """Return the newest stored snapshot payload text."""
    row = db.execute(
        "SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["payload"] if row else None


def latest_snapshot(manager: Any) -> dict[str, Any] | None:
    """Return the newest stored snapshot, decoded, read through ``manager``."""
    with manager.reader() as db:
        payload = latest_payload(db)
    return json.loads(payload) if payload else None


def save_snapshot(
    repository: Any,
    snapshot: dict[str, Any],
    update_full_sync: bool | None = True,
    activity_days: int | None = None,
    activity_count: int | None = None,
) -> None:
    """Store ``snapshot`` and, like the retired sync, set the sync markers."""
    with repository._database_manager.unit_of_work() as db:
        store_snapshot(
            db, snapshot, snapshot["synced_at"], activity_count=activity_count
        )
        set_value = repository._key_value_repository.set
        if update_full_sync is True:
            set_value(db, "last_sync_at", snapshot["synced_at"])
            set_value(db, "last_sync_error", "")
            if activity_days is not None:
                set_value(db, "last_sync_activity_days", str(activity_days))


def save_view(repository: Any, snapshot: dict[str, Any]) -> None:
    """Store a snapshot view without touching the sync markers."""
    with repository._database_manager.unit_of_work() as db:
        store_snapshot(db, snapshot, snapshot.get("synced_at") or repository._now())
