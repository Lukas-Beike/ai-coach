"""Compact canonical activity rows for performance readers."""

from collections.abc import Iterable, Mapping
from typing import Any

from backend.providers.intervals_activity_fields import ACTIVITY_FIELDS, selected


def compact_activity_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the compact activity shape used by the performance context."""
    return [selected(row, ACTIVITY_FIELDS) for row in rows]
