"""Stateless recovery aggregation."""

from collections.abc import Sequence

AVERAGE_DAYS = 7


def rounded_average(values: Sequence[float]) -> float | None:
    """Average to two decimals, or None for no values."""
    return round(sum(values) / len(values), 2) if values else None
