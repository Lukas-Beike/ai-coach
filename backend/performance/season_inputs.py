"""Season-preparation inputs read through the canonical selector ports.

Activity summaries come from an ``ActivitySummaryReader``. The CTL/ATL basis is
the local fitness and fatigue (card M7) of yesterday, computed from the stored
local load the same reader serves (``LocalLoadDayReader``); Intervals.icu CTL
and ATL never seed it. Both are read inside one caller-owned unit of work, so a
concurrent sync cannot mix revisions. Nothing here reads the canonicalised sections
of the stored snapshot, which a later change stops writing.

The reader bounds are athlete-local dates in the reader's own timezone, while the
season views bucket activities in the request timezone. Row reads are therefore
padded by a day on each side and the caller filters with ``summary_local_date``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from backend.activities.activity_summary import ActivitySummary, summary_local_date
from backend.performance.fitness_fatigue import SOURCE_LABEL
from backend.performance.load_context import read_local_fitness
from backend.runtime.ports import ActivitySummaryReader, ObservationReader

ROW_WINDOW_PAD = timedelta(days=1)
LOCAL_BASIS_SOURCE = SOURCE_LABEL


@dataclass(frozen=True, slots=True)
class SeasonSource:
    """Lazy accessors a season consumer uses to read canonical inputs."""

    database_manager: Callable[[], Any]
    observation_reader: Callable[[], ObservationReader]
    activity_summaries: Callable[[], ActivitySummaryReader]


@dataclass(frozen=True, slots=True)
class SeasonLoadInputs:
    """The local load basis of yesterday and the activities completed today."""

    basis_day: date
    ctl: float | None
    atl: float | None
    completed_today: tuple[ActivitySummary, ...]

    def source_label(self) -> str:
        """Label of the basis values: always the local curve."""
        return LOCAL_BASIS_SOURCE


def read_activity_summaries(
    source: SeasonSource, db: Any, start: date, end: date
) -> list[ActivitySummary]:
    """Read the activity summaries of ``start`` .. ``end`` (padded by a day)."""
    return list(
        source.activity_summaries().activity_summaries(
            db, start=start - ROW_WINDOW_PAD, end=end + ROW_WINDOW_PAD
        )
    )


def read_season_load_inputs(
    source: SeasonSource, db: Any, *, today: date, timezone: str
) -> SeasonLoadInputs:
    """Read yesterday's local fitness and fatigue and today's completed activities.

    Yesterday is open, so unknown, while the activities were last synced before it.
    """
    basis_day = today - timedelta(days=1)
    latest = read_local_fitness(
        source.activity_summaries(),
        db,
        start=basis_day,
        end=basis_day,
        today=today,
        timezone=timezone,
    )["days"][-1]
    completed = tuple(
        summary
        for summary in read_activity_summaries(source, db, today, today)
        if summary_local_date(summary, timezone) == today.isoformat()
    )
    return SeasonLoadInputs(
        basis_day=basis_day,
        ctl=latest["fitness"],
        atl=latest["fatigue"],
        completed_today=completed,
    )
