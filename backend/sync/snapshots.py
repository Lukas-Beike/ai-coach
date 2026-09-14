"""Connection-taking persistence operations for provider snapshots."""

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
    update_full_sync: bool,
    activity_days: int | None,
    set_value: Callable[[str, str, Any], None],
) -> None:
    repository.save(db, snapshot, snapshot["synced_at"])
    if update_full_sync:
        set_value("last_sync_at", snapshot["synced_at"], db)
        set_value("last_sync_error", "", db)
        if activity_days is not None:
            set_value("last_sync_activity_days", str(activity_days), db)
    else:
        set_value("last_performance_refresh_at", snapshot["synced_at"], db)
