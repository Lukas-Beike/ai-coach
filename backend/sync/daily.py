"""Dependency-light, timezone-aware daily synchronization markers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime


def daily_marker_key(source: str, legacy_keys: Mapping[str, str]) -> str:
    """Return the durable local-date marker key for a known provider."""
    if source not in legacy_keys:
        raise ValueError(f"unknown daily sync source: {source}")
    return f"daily_sync_{source}_local_date"


def daily_sync_is_due(
    source: str,
    now: datetime,
    *,
    legacy_keys: Mapping[str, str],
    get_value: Callable[[str], str | None],
    set_value: Callable[[str, str], None],
    local_date: Callable[[str], str | None],
) -> bool:
    """Check and lazily migrate a provider's local execution-day marker."""
    marker_key = daily_marker_key(source, legacy_keys)
    current_date = local_date(now.isoformat())
    marker = get_value(marker_key)
    if marker:
        return marker != current_date
    legacy_date = local_date(get_value(legacy_keys[source]) or "")
    if legacy_date:
        set_value(marker_key, legacy_date)
        return legacy_date != current_date
    return True


def mark_daily_sync(
    source: str,
    now: datetime,
    *,
    legacy_keys: Mapping[str, str],
    set_value: Callable[[str, str], None],
    local_date: Callable[[str], str | None],
) -> None:
    """Store the provider's successful local execution date."""
    marker_key = daily_marker_key(source, legacy_keys)
    set_value(marker_key, local_date(now.isoformat()) or "")
