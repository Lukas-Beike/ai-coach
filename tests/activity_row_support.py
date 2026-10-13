"""Activity-row test doubles shared by the activity, coach and athlete tests."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.providers.snapshot_projection import intervals_activity_rows


class SnapshotActivityRows:
    """Serve the raw rows of a stored snapshot, like the legacy selector source."""

    def __init__(self, snapshot_reader: Any) -> None:
        self._snapshot_reader = snapshot_reader

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        rows = intervals_activity_rows(self._snapshot_reader.latest_snapshot(db))
        return rows if limit is None else rows[:limit]


class FixedActivityRows:
    """Serve a fixed list of raw rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = tuple(rows or ())

    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return self.rows if limit is None else self.rows[:limit]
