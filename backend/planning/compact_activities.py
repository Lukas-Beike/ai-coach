"""Compact recent-activity rows derived from the canonical activity row port.

The Intervals.icu snapshot used to carry a compact ``recent_activities`` list.
Consumers now read the raw rows through ``ActivityRowReader`` and derive the same
compact shape here with the selection the snapshot read model used
(``planning.context.ACTIVITY_FIELDS``, newest 500 rows), so a reader that is
served from the legacy projection or from the canonical tables gets one shape.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final

from backend.planning.context import ACTIVITY_FIELDS, selected
from backend.runtime.ports import ActivityRowReader

RECENT_ACTIVITY_LIMIT: Final = 500


def compact_activity_rows(
    rows: Iterable[Any], *, limit: int = RECENT_ACTIVITY_LIMIT
) -> list[dict[str, Any]]:
    """Select the compact activity fields of the first ``limit`` raw rows."""
    compact = [selected(row, ACTIVITY_FIELDS) for row in rows if isinstance(row, dict)]
    return compact[:limit]


@dataclass(frozen=True)
class ActivityRowSource:
    """Lazy accessors a consumer uses to read compact recent activities.

    Both callables are resolved at read time, as the other assemblies do, so the
    composition root can pass ``lambda: ...`` accessors.
    """

    database_manager: Callable[[], Any]
    reader: Callable[[], ActivityRowReader]

    def compact(self, db: Any | None = None) -> list[dict[str, Any]]:
        """Return compact recent activities, newest first.

        Inside the caller's unit of work when ``db`` is given, else in a read of
        its own.
        """
        reader = self.reader()
        if db is not None:
            return compact_activity_rows(
                reader.activity_rows(db, limit=RECENT_ACTIVITY_LIMIT)
            )
        with self.database_manager().reader() as own:
            return compact_activity_rows(
                reader.activity_rows(own, limit=RECENT_ACTIVITY_LIMIT)
            )
