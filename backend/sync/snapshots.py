"""Stored provider snapshot reads and the write kept for the legacy read model."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


def latest_snapshot(db: Any, repository: Any) -> dict[str, Any] | None:
    payload = repository.latest_payload(db)
    return json.loads(payload) if payload else None


def save_snapshot(
    db: Any,
    snapshot: dict[str, Any],
    repository: Any,
    *,
    update_full_sync: bool | None,
    activity_days: int | None,
    set_value: Callable[[str, str, Any], None],
    activity_count: int | None = None,
) -> None:
    if activity_count is None:
        repository.save(db, snapshot, snapshot["synced_at"])
    else:
        repository.save(
            db, snapshot, snapshot["synced_at"], activity_count=activity_count
        )
    if update_full_sync is True:
        set_value("last_sync_at", snapshot["synced_at"], db)
        set_value("last_sync_error", "", db)
        if activity_days is not None:
            set_value("last_sync_activity_days", str(activity_days), db)
    elif update_full_sync is False:
        set_value("last_performance_refresh_at", snapshot["synced_at"], db)
