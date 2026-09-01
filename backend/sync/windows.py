"""Bounded date-window construction for provider synchronization."""

from __future__ import annotations

from datetime import date, timedelta


def split_date_windows(
    days: int,
    *,
    end_date: date,
    earliest_date: date,
    chunk_days: int,
    all_days: int,
) -> list[tuple[date, date]]:
    """Split a sync period into inclusive, contiguous bounded windows."""
    if chunk_days < 1:
        raise ValueError("chunk_days must be positive")
    newest = end_date
    oldest = earliest_date if days == all_days else newest - timedelta(days=max(1, days) - 1)
    windows: list[tuple[date, date]] = []
    cursor = oldest
    while cursor <= newest:
        window_end = min(newest, cursor + timedelta(days=chunk_days - 1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows
