"""Dependency-light provider refresh markers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry

SYNC_INTERVAL_SECONDS = 60 * 60


def _require_daily_source(source: str, registry: ProviderRegistry) -> None:
    if source not in registry.daily_marker_ids():
        raise ValueError(f"unknown daily sync source: {source}")


def daily_marker_key(
    source: str, *, registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY
) -> str:
    """Return the durable last-success key for a known provider."""
    _require_daily_source(source, registry)
    return f"sync_{source}_last_success_at"


def daily_attempt_marker_key(
    source: str, *, registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY
) -> str:
    """Return the durable last-attempt key for a known provider."""
    _require_daily_source(source, registry)
    return f"sync_{source}_last_attempt_at"


def daily_sync_is_due(
    source: str,
    now: datetime,
    *,
    get_value: Callable[[str], str | None],
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
) -> bool:
    """Check whether a provider's last success or attempt was an hour ago."""
    timestamps = []
    for marker in (
        get_value(daily_attempt_marker_key(source, registry=registry)),
        get_value(daily_marker_key(source, registry=registry)),
    ):
        if not marker:
            continue
        try:
            timestamp = datetime.fromisoformat(marker)
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=now.tzinfo)
        timestamps.append(timestamp.timestamp())
    if not timestamps:
        return True
    return now.timestamp() - max(timestamps) >= SYNC_INTERVAL_SECONDS


def mark_daily_sync(
    source: str,
    now: datetime,
    *,
    set_value: Callable[[str, str], None],
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
) -> None:
    """Store the provider's last successful refresh time."""
    set_value(daily_marker_key(source, registry=registry), now.isoformat())


def mark_daily_sync_attempt(
    source: str,
    now: datetime,
    *,
    set_value: Callable[[str, str], None],
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
) -> None:
    """Store when a scheduled provider refresh was queued."""
    set_value(daily_attempt_marker_key(source, registry=registry), now.isoformat())


class DailySyncMarkerService:
    """Persist provider refresh markers within the database unit of work."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        local_now: Callable[[], datetime],
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._local_now = local_now
        self._registry = registry

    def is_due(self, source: str, now: datetime | None = None) -> bool:
        """Check whether the latest provider attempt or success is due."""
        current = now or self._local_now()
        with self._database_manager.unit_of_work() as db:
            return daily_sync_is_due(
                source,
                current,
                get_value=lambda key: self._key_value_repository.get(db, key),
                registry=self._registry,
            )

    def mark(self, source: str, now: datetime | None = None) -> None:
        """Store the provider's last successful refresh time."""
        with self._database_manager.unit_of_work() as db:
            self.mark_in_transaction(db, source, now)

    def mark_in_transaction(
        self, db: Any, source: str, now: datetime | None = None
    ) -> None:
        """Write the success marker into the caller's transaction."""
        current = now or self._local_now()
        mark_daily_sync(
            source,
            current,
            set_value=lambda key, value: self._key_value_repository.set(db, key, value),
            registry=self._registry,
        )

    def mark_attempt(self, source: str, now: datetime | None = None) -> None:
        """Store when a scheduled provider refresh was queued."""
        current = now or self._local_now()
        with self._database_manager.unit_of_work() as db:
            mark_daily_sync_attempt(
                source,
                current,
                set_value=lambda key, value: self._key_value_repository.set(
                    db, key, value
                ),
                registry=self._registry,
            )
