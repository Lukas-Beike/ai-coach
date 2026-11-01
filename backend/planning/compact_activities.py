"""Recent activities for planning, calendar and Coach consumers.

Consumers read the newest provider-neutral activity summaries through
``ActivitySummarySource``. The compact raw-row selection that snapshot storage
writes lives with the ingestion owner, ``backend.sync.intervals_compaction``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from backend.activities.activity_summary import ActivitySummary
from backend.activities.sync_time import activities_synced_at
from backend.runtime.ports import ActivitySummaryReader, ProviderCoverageReader

RECENT_ACTIVITY_LIMIT: Final = 500


@dataclass(frozen=True)
class ActivitySummarySource:
    """Lazy accessors a consumer uses to read the recent activity summaries.

    Both callables are resolved at read time, as the other assemblies do, so the
    composition root can pass ``lambda: ...`` accessors.
    """

    database_manager: Callable[[], Any]
    reader: Callable[[], ActivitySummaryReader]
    # Where the activities' sync time comes from; without it the time is unknown.
    coverage: Callable[[], ProviderCoverageReader] | None = None

    def read(self, db: Any | None = None) -> tuple[list[ActivitySummary], str | None]:
        """Return the recent activity summaries and their sync time from one read."""
        if db is None:
            with self.database_manager().reader() as own:
                return self.read(own)
        coverage = None if self.coverage is None else self.coverage()
        return self.compact(db), activities_synced_at(coverage, db)

    def compact(self, db: Any | None = None) -> list[ActivitySummary]:
        """Return the newest ``RECENT_ACTIVITY_LIMIT`` summaries, newest first.

        Inside the caller's unit of work when ``db`` is given, else in a read of
        its own.
        """
        if db is None:
            with self.database_manager().reader() as own:
                return self.compact(own)
        return list(self.reader().activity_summaries(db, limit=RECENT_ACTIVITY_LIMIT))
