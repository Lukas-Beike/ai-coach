"""Compact activity rows derived from the raw Intervals.icu activity rows.

The compact shape is the one the sync stores as ``recent_activities``: the
planning activity fields without empty values. The activity read services serve
this shape; the selector keeps returning the raw rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from backend.planning.context import ACTIVITY_FIELDS, selected
from backend.runtime.ports import ActivityRowReader


def compact_activity_rows(rows: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    """Return the compact shape of raw activity rows, in the given order."""
    return tuple(selected(row, ACTIVITY_FIELDS) for row in rows)


class CompactActivityRows(ActivityRowReader):
    """Serve the compact shape of the rows of another activity row reader."""

    def __init__(self, rows: ActivityRowReader) -> None:
        self._rows = rows

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return compact_activity_rows(
            self._rows.activity_rows(db, start=start, end=end, limit=limit)
        )
