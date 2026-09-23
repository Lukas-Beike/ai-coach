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


def daily_attempt_marker_key(source: str) -> str:
    """Return the durable last-attempt key for a known provider."""
    if source not in {"intervals", "garmin", "calendar"}:
        raise ValueError(f"unknown daily sync source: {source}")
    return f"sync_{source}_last_attempt_at"


def daily_sync_is_due(
    source: str,
    now: datetime,
    *,
    get_value: Callable[[str], str | None],
) -> bool:
    """Check whether a provider's last success or attempt was an hour ago."""
    timestamps = []
    for marker in (get_value(daily_attempt_marker_key(source)), get_value(daily_marker_key(source))):
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
) -> None:
    """Store the provider's last successful refresh time."""
    set_value(daily_marker_key(source), now.isoformat())


def mark_daily_sync_attempt(
    source: str,
    now: datetime,
    *,
    set_value: Callable[[str, str], None],
) -> None:
    """Store when a scheduled provider refresh was queued."""
    set_value(daily_attempt_marker_key(source), now.isoformat())
