"""Transactional persistence for provider synchronization state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.snapshots import latest_snapshot, save_snapshot


class SyncStateRepository:
    """Own the database transactions for synchronization state."""

    def __init__(
        self,
        database_manager: Any,
        key_value_repository: Any,
        snapshot_repository: Any,
        now: Callable[[], str],
    ):
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._snapshot_repository = snapshot_repository
        self._now = now

    def sync_period(
        self, source: str, defaults: Mapping[str, int], all_days: int
    ) -> int:
        default = defaults[source]
        with self._database_manager.unit_of_work() as db:
            stored = self._key_value_repository.get(db, f"{source}_sync_days")
        try:
            value = int(stored or default)
        except (TypeError, ValueError):
            value = default
        if value == all_days:
            return all_days
        maximum = 365 if source == "intervals" else 90
        return max(1, min(value, maximum))

    def set_sync_period(
        self,
        source: str,
        value: Any,
        defaults: Mapping[str, int],
        all_days: int,
    ) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "The synchronization period must be a whole number."
            ) from exc
        maximum = 365 if source == "intervals" else 90
        if days != all_days and not 1 <= days <= maximum:
            raise ValueError(
                f"The period for {source} must be {all_days} or between 1 and {maximum} days."
            )
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, f"{source}_sync_days", str(days))
        return days

    def cursor(self, provider: str, stream: str) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            return read_cursor(db, provider, stream)

    def update_cursor(
        self,
        provider: str,
        stream: str,
        cursor: str,
        high_water_mark: str | None = None,
    ) -> None:
        with self._database_manager.unit_of_work() as db:
            write_cursor(db, provider, stream, cursor, high_water_mark, self._now())

    def latest_snapshot(self) -> dict[str, Any] | None:
        with self._database_manager.unit_of_work() as db:
            return latest_snapshot(db, self._snapshot_repository)

    def save_snapshot(
        self,
        snapshot: dict[str, Any],
        update_full_sync: bool = True,
        activity_days: int | None = None,
    ) -> None:
        with self._database_manager.unit_of_work() as db:
            save_snapshot(
                db,
                snapshot,
                self._snapshot_repository,
                update_full_sync=update_full_sync,
                activity_days=activity_days,
                set_value=lambda key, value, connection: self._key_value_repository.set(
                    connection, key, value
                ),
            )

    def save_view(self, snapshot: dict[str, Any]) -> None:
        """Persist a local snapshot view without changing sync status markers."""
        with self._database_manager.unit_of_work() as db:
            self._snapshot_repository.save(
                db, snapshot, snapshot.get("synced_at") or self._now()
            )
