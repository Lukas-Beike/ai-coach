"""Activity-row test doubles shared by the activity, coach and athlete tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.activity_summary import ActivitySummary, activity_summaries
from backend.canonical.coverage import MetricWindow, ProviderCoverage
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.performance.canonical_inputs import CanonicalPerformanceSource
from backend.providers.intervals_activity_mapping import map_intervals_activities
from backend.providers.snapshot_projection import intervals_activity_rows


def summaries_of_rows(rows: Any) -> tuple[ActivitySummary, ...]:
    """Summaries of raw Intervals.icu rows, one session per row, UTC local time."""
    zone = ZoneInfo("UTC")
    mapped = map_intervals_activities(
        list(rows), zone=zone, retrieved_at=datetime(2026, 10, 12, 8, tzinfo=UTC)
    )
    return activity_summaries(
        ((f"act_{record.activity_id}", [record]) for record in mapped.records), zone
    )


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

    def activity_summaries(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[ActivitySummary, ...]:
        summaries = summaries_of_rows(self.activity_rows(db))
        return summaries if limit is None else summaries[:limit]


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

    def activity_summaries(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[ActivitySummary, ...]:
        """Serve summary dicts as given; raw rows go through the Intervals mapper."""
        if all("started_at_local" in row for row in self.rows):
            summaries: tuple[Any, ...] = self.rows
        else:
            summaries = summaries_of_rows(self.rows)
        return summaries if limit is None else summaries[:limit]


class NoObservations:
    """An observation reader that holds no observations."""

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        return ()


class StoredCoverage:
    """Canonical provider coverage with one Intervals.icu activity fetch time."""

    def __init__(self, fetched_at: str | None) -> None:
        self._fetched_at = (
            None if fetched_at is None else datetime.fromisoformat(fetched_at)
        )

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        return ()

    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]:
        return (
            ProviderCoverage(
                provider=ProviderId.INTERVALS,
                retrieved_at=self._fetched_at,
                activity_count=0,
                observation_count=0,
                issue_counts={},
                first_observed_on=None,
                last_observed_on=None,
                activities_retrieved_at=self._fetched_at,
            ),
        )


def canonical_source(
    rows: Any,
    database_manager: Callable[[], Any],
    *,
    fetched_at: str | None = None,
) -> CanonicalPerformanceSource:
    """A canonical performance source over the given raw activity rows."""
    return CanonicalPerformanceSource(
        database_manager,
        NoObservations,
        activity_summaries=lambda: rows,
        coverage=None if fetched_at is None else lambda: StoredCoverage(fetched_at),
    )


class ReadOnlyManager:
    """A database manager stand-in that only opens reads on an inert connection."""

    @contextmanager
    def reader(self) -> Iterator[object]:
        yield object()

    read_snapshot = reader
