"""Dependency-light, timezone-aware daily synchronization markers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime


def daily_marker_key(source: str) -> str:
    """Return the durable local-date marker key for a known provider."""
    if source not in {"intervals", "garmin", "calendar"}:
        raise ValueError(f"unknown daily sync source: {source}")
    return f"daily_sync_{source}_local_date"


def daily_sync_is_due(
    source: str,
    now: datetime,
    *,
    get_value: Callable[[str], str | None],
) -> bool:
    """Check whether a provider has completed its daily sync."""
    return get_value(daily_marker_key(source)) != now.date().isoformat()


def mark_daily_sync(
    source: str,
    now: datetime,
    *,
    set_value: Callable[[str, str], None],
) -> None:
    """Store the provider's successful local execution date."""
    set_value(daily_marker_key(source), now.date().isoformat())
