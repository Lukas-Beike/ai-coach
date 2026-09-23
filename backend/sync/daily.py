"""Dependency-light provider refresh markers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

SYNC_INTERVAL_SECONDS = 60 * 60


def daily_marker_key(source: str) -> str:
    """Return the durable last-success key for a known provider."""
    if source not in {"intervals", "garmin", "calendar"}:
        raise ValueError(f"unknown daily sync source: {source}")
    return f"sync_{source}_last_success_at"


def daily_sync_is_due(
    source: str,
    now: datetime,
    *,
    get_value: Callable[[str], str | None],
) -> bool:
    """Check whether a provider's last successful refresh was an hour ago."""
    marker = get_value(daily_marker_key(source))
    if not marker:
        return True
    try:
        last_success = datetime.fromisoformat(marker)
    except ValueError:
        return True
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=now.tzinfo)
    return now.timestamp() - last_success.timestamp() >= SYNC_INTERVAL_SECONDS


def mark_daily_sync(
    source: str,
    now: datetime,
    *,
    set_value: Callable[[str, str], None],
) -> None:
    """Store the provider's last successful refresh time."""
    set_value(daily_marker_key(source), now.isoformat())
