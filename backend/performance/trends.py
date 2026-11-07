"""Historical performance averages from the Garmin day history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta


def garmin_history_average(
    key: str,
    days: int,
    end_date: date,
    history: Mapping[str, Mapping[date, float]],
) -> float | None:
    """Average a Garmin metric's canonical day history over ``days``."""
    cutoff = end_date - timedelta(days=days - 1)
    numbers = [
        float(value)
        for day, value in history.get(key, {}).items()
        if cutoff <= day <= end_date
    ]
    return round(sum(numbers) / len(numbers), 2) if numbers else None
