"""Season-preparation inputs read through the canonical selector ports.

Activity summaries come from an ``ActivitySummaryReader``. The reader bounds are
athlete-local dates in the reader's own timezone, while the season views bucket
activities in the request timezone. Row reads are therefore padded by a day on
each side and the caller filters with ``summary_local_date``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import ActivitySummary
from backend.runtime.ports import ActivitySummaryReader, ObservationReader

ROW_WINDOW_PAD = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class SeasonSource:
    """Lazy accessors a season consumer uses to read canonical inputs."""

    database_manager: Callable[[], Any]
    observation_reader: Callable[[], ObservationReader]
    activity_summaries: Callable[[], ActivitySummaryReader]


def read_activity_summaries(
    source: SeasonSource, db: Any, start: date, end: date
) -> list[ActivitySummary]:
    """Read the activity summaries of ``start`` .. ``end`` (padded by a day)."""
    return list(
        source.activity_summaries().activity_summaries(
            db, start=start - ROW_WINDOW_PAD, end=end + ROW_WINDOW_PAD
        )
    )
