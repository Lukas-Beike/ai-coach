"""Season-preparation inputs read through the canonical selector ports.

Activity summaries come from an ``ActivitySummaryReader`` and the CTL/ATL basis from an
``ObservationReader``. Both are read inside one caller-owned unit of work, so a
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
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.canonical_inputs import resolve_reader
from backend.performance.planning_recovery import first_intervals_by_day
from backend.providers.source_labels import (
    SourceView,
    observation_source_label,
    provider_label,
)
from backend.runtime.ports import ActivitySummaryReader, ObservationReader

ROW_WINDOW_PAD = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class SeasonSource:
    """Lazy accessors a season consumer uses to read canonical inputs."""

    database_manager: Callable[[], Any]
    observation_reader: Callable[[], ObservationReader]
    activity_summaries: Callable[[], ActivitySummaryReader]


@dataclass(frozen=True, slots=True)
class SeasonLoadInputs:
    """The load basis of yesterday and the activities completed today."""

    basis_day: date
    ctl: Observation | None
    atl: Observation | None
    completed_today: tuple[ActivitySummary, ...]

    def source_label(self) -> str:
        """Label of the basis values, from the observation that supplied them."""
        observation = self.atl or self.ctl
        if observation is None:
            return provider_label(ProviderId.INTERVALS, SourceView.SEASON_PREPARATION)
        return observation_source_label(observation, SourceView.SEASON_PREPARATION)


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
    """Read yesterday's CTL and ATL and the activities completed on ``today``."""
    basis_day = today - timedelta(days=1)
    reader = resolve_reader(source.observation_reader(), db)
    loads = {
        kind: first_intervals_by_day(
            reader.observations(db, kind, start=basis_day, end=basis_day)
        ).get(basis_day)
        for kind in (MetricKind.CTL, MetricKind.ATL)
    }
    completed = tuple(
        summary
        for summary in read_activity_summaries(source, db, today, today)
        if summary_local_date(summary, timezone) == today.isoformat()
    )
    return SeasonLoadInputs(
        basis_day=basis_day,
        ctl=loads[MetricKind.CTL],
        atl=loads[MetricKind.ATL],
        completed_today=completed,
    )
