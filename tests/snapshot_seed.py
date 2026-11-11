"""Seed a stored provider snapshot for tests; production never writes one."""

from __future__ import annotations

from typing import Any


def save_snapshot(
    repository: Any,
    snapshot: dict[str, Any],
    update_full_sync: bool | None = True,
    activity_days: int | None = None,
    activity_count: int | None = None,
) -> None:
    """Store ``snapshot`` and, like the retired sync, set the sync markers."""
    with repository._database_manager.unit_of_work() as db:
        if activity_count is None:
            repository._snapshot_repository.save(db, snapshot, snapshot["synced_at"])
        else:
            repository._snapshot_repository.save(
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
        repository._snapshot_repository.save(
            db, snapshot, snapshot.get("synced_at") or repository._now()
        )
