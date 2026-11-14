"""Transactional persistence for provider synchronization state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from backend.canonical.vocabulary import (
    GARMIN_ID,
    INTERVALS_ID,
    WAHOO_ID,
    ProviderId,
    RemoteEntityKind,
)
from backend.db.remote_links import RemoteLinkRepository
from backend.sync.cursors import read_cursor, write_cursor
from backend.sync.intervals_state import INTERVALS_OUTPUT_OK_KEY, latest_stamp
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.provider_table import CALENDAR_ID

# Owner of the stored last-sync, daily-marker and full-resync key names; they
# are persisted, so a name never changes. Competitions are the Intervals.icu area.
_LAST_SYNC_KEYS: Final = MappingProxyType(
    {
        GARMIN_ID: ("last_garmin_sync_at", "last_garmin_error"),
        WAHOO_ID: ("last_wahoo_sync_at", "last_wahoo_sync_error"),
        CALENDAR_ID: (
            "last_external_calendar_sync_at",
            "last_external_calendar_sync_error",
        ),
        INTERVALS_ID: ("last_competition_sync_at", "last_competition_sync_error"),
    }
)
_RESYNC_FIELDS: Final = ("running", "status", "at", "error")
_RESYNC_PROVIDERS: Final = tuple(
    provider for _, provider in DEFAULT_PROVIDER_REGISTRY.full_resync_routes()
)


def last_sync_key(provider: str) -> str:
    """Return the key of a provider's last successful sync time."""
    return _LAST_SYNC_KEYS[provider][0]


def last_error_key(provider: str) -> str:
    """Return the key of a provider's last sync error."""
    return _LAST_SYNC_KEYS[provider][1]


def _require_daily_source(source: str) -> None:
    if source not in DEFAULT_PROVIDER_REGISTRY.daily_marker_ids():
        raise ValueError(f"unknown daily sync source: {source}")


def daily_marker_key(source: str) -> str:
    """Return the durable last-success key for a known provider."""
    _require_daily_source(source)
    return f"sync_{source}_last_success_at"


def daily_attempt_key(source: str) -> str:
    """Return the durable last-attempt key for a known provider."""
    _require_daily_source(source)
    return f"sync_{source}_last_attempt_at"


def resync_key(provider: str, field: str) -> str:
    """Return a full-resync state key: running, status, at or error."""
    if field not in _RESYNC_FIELDS:
        raise ValueError(f"unknown full resync field: {field}")
    if provider not in _RESYNC_PROVIDERS:
        raise ValueError(f"{provider} has no full resync")
    return f"{provider}_full_resync_{field}"


def resync_reset_keys() -> tuple[tuple[str, str], ...]:
    """Return each full-resync provider's (running, status) keys for the startup reset."""
    return tuple(
        (resync_key(provider, "running"), resync_key(provider, "status"))
        for provider in _RESYNC_PROVIDERS
    )


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

    def adopt_intervals_export_time(self) -> None:
        """Stamp the newest Intervals.icu export of a release without stamps, once.

        Plan and competition links synced before the output stamps existed are the
        only record of that export; an existing stamp is never replaced.
        """
        with self._database_manager.unit_of_work() as db:
            if self._key_value_repository.get(db, INTERVALS_OUTPUT_OK_KEY):
                return
            newest = latest_stamp(
                *RemoteLinkRepository().synced_times(
                    db,
                    ProviderId.INTERVALS.value,
                    (RemoteEntityKind.PLANNED_UNIT, RemoteEntityKind.COMPETITION),
                )
            )
            if newest:
                self._key_value_repository.set(db, INTERVALS_OUTPUT_OK_KEY, newest)

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
