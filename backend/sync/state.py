"""Transactional persistence for provider synchronization state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.db.remote_links import RemoteLinkRepository
from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY


class SyncStateRepository:
    """Own the database transactions for synchronization state."""

    def __init__(
        self,
        database_manager: Any,
        key_value_repository: Any,
        now: Callable[[], str],
    ):
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._now = now

    def sync_period(
        self, source: str, defaults: Mapping[str, int], all_days: int
    ) -> int:
        default = defaults[source]
        with self._database_manager.reader() as db:
            stored = self._key_value_repository.get(db, f"{source}_sync_days")
        try:
            value = int(stored or default)
        except TypeError, ValueError:
            value = default
        if value == all_days:
            return all_days
        maximum = DEFAULT_PROVIDER_REGISTRY.max_sync_days(source)
        return max(1, min(value, maximum))

    def set_sync_period(
        self,
        source: str,
        value: Any,
        all_days: int,
    ) -> int:
        try:
            days = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "The synchronization period must be a whole number."
            ) from exc
        if not DEFAULT_PROVIDER_REGISTRY.accepts_sync_days(source, days, all_days):
            maximum = DEFAULT_PROVIDER_REGISTRY.max_sync_days(source)
            raise ValueError(
                f"The period for {source} must be {all_days} or between 1 and {maximum} days."
            )
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, f"{source}_sync_days", str(days))
        return days

    def last_remote_synced_at(self, provider: str) -> str | None:
        """The newest time any local entity was synced to the provider."""
        with self._database_manager.reader() as db:
            return RemoteLinkRepository.last_synced_at(db, provider)

    def cursor(self, provider: str, stream: str) -> dict[str, Any]:
        with self._database_manager.reader() as db:
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
