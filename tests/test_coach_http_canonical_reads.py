"""Coach context, HTTP state and diagnostics read activities through the selector.

Each consumer reads nothing before the first completed backfill, reads the
snapshot's activities from the canonical tables afterwards, and does not need the
``recent_activities`` / ``raw_provider_data`` / ``recent_wellness`` snapshot
sections then. All storage is temporary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any, TypeVar
from unittest.mock import Mock

from activity_row_support import summaries_of_rows
from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.vocabulary import ProviderId
from backend.coach.context import CoachPerformanceContextReader
from backend.diagnostics.canonical_counts import activity_count, wellness_day_count
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService
from backend.http_api.state_prelude import CalendarWindowRange, PublicStateLocalPrelude
from backend.planning.compact_activities import (
    RECENT_ACTIVITY_LIMIT,
    ActivitySummarySource,
    compact_activity_rows,
)
from backend.sync.canonical_coverage_store import (
    CanonicalCoverageStore,
    intervals_snapshot_coverage,
)

TODAY = date(2026, 10, 13)
CANONICAL_SECTIONS = ("recent_activities", "recent_wellness", "raw_provider_data")
T = TypeVar("T")


def _by_id(rows: Sequence[Any]) -> list[Any]:
    return sorted(rows, key=lambda row: str(row["id"]))


class _Manager:
    """Hands the fixture's connection to ``reader``/``unit_of_work`` callers."""

    def __init__(self, case: CanonicalReadFixture) -> None:
        self._case = case

    def reader(self) -> Any:
        return self._case.manager.reader()

    def read_snapshot(self) -> Any:
        return self._case.manager.read_snapshot()

    def unit_of_work(self) -> Any:
        return self._case.manager.unit_of_work()


class _RecordingManager(_Manager):
    """Records whether a unit of work is open when callers read."""

    def __init__(self, case: CanonicalReadFixture) -> None:
        super().__init__(case)
        self.open = False

    @contextmanager
    def unit_of_work(self) -> Iterator[Any]:
        with super().unit_of_work() as db:
            self.open = True
            try:
                yield db
            finally:
                self.open = False

    @contextmanager
    def read_snapshot(self) -> Iterator[Any]:
        with super().read_snapshot() as db:
            self.open = True
            try:
                yield db
            finally:
                self.open = False


class CanonicalContextReadCase(CanonicalReadFixture):
    def _source(self, selector: Any) -> ActivitySummarySource:
        return ActivitySummarySource(lambda: _Manager(self), lambda: selector)  # type: ignore[arg-type,return-value]

    def _pending_and_tables(
        self, read: Callable[[Any, dict[str, Any]], T]
    ) -> tuple[T, T]:
        """Run ``read`` before the first backfill, then against the filled tables.

        ``read`` receives the selector and the stored Intervals snapshot.
        """
        pending = read(make_selector(self), self.intervals)
        populate(self)
        return pending, read(make_selector(self), self.intervals)

    def _with_and_without_sections(
        self, read: Callable[[Any, dict[str, Any]], T]
    ) -> tuple[T, T]:
        """Run ``read`` against the tables, then again without the snapshot sections."""
        populate(self)
        selector = make_selector(self)
        full = read(selector, self.intervals)
        self.intervals = {
            key: value
            for key, value in self.intervals.items()
            if key not in CANONICAL_SECTIONS
        }
        return full, read(selector, self.intervals)

    def _snapshot_ids(self) -> list[str]:
        return sorted(str(row["id"]) for row in self.intervals["recent_activities"])


def _intervals_ids(rows: Sequence[Any]) -> list[str]:
    return sorted(
        str(row["record_ids"]["intervals"])
        for row in rows
        if "intervals" in row["record_ids"]
    )


class CompactActivityTests(CanonicalContextReadCase):
    def test_table_rows_compact_to_the_snapshot_recent_activities(self) -> None:
        populate(self)
        compact = self._source(make_selector(self)).compact()

        self.assertTrue(compact)
        by_intervals_id = {
            item["record_ids"]["intervals"]: item
            for item in compact
            if "intervals" in item["record_ids"]
        }
        snapshot_rows = self.intervals["recent_activities"]
        self.assertEqual(
            sorted(by_intervals_id), sorted(str(row["id"]) for row in snapshot_rows)
        )
        # Summaries replace the compact raw rows: each snapshot row keeps its
        # local start and, unless a Garmin record was merged in, its mapped values
        # (the helper maps in UTC, so the aware start is left out).
        mapped_by_id = {
            item["record_ids"]["intervals"]: item
            for item in summaries_of_rows(snapshot_rows)
        }
        for key, mapped in mapped_by_id.items():
            summary = by_intervals_id[key]
            self.assertEqual(summary["started_at_local"], mapped["started_at_local"])
            if summary["source"] == "Intervals.icu":
                self.assertEqual(
                    {
                        k: v
                        for k, v in summary.items()
                        if k not in ("id", "record_ids", "started_at")
                    },
                    {
                        k: v
                        for k, v in mapped.items()
                        if k not in ("id", "record_ids", "started_at")
                    },
                )

    def test_compact_activities_are_empty_until_the_tables_serve(self) -> None:
        pending, tables = self._pending_and_tables(
            lambda sel, _snap: self._source(sel).compact()
        )

        self.assertEqual(pending, [])
        self.assertEqual(_intervals_ids(tables), self._snapshot_ids())

    def test_compaction_is_capped_like_the_snapshot_read_model(self) -> None:
        rows = [{"id": str(index), "name": "x"} for index in range(600)]

        self.assertEqual(len(compact_activity_rows(rows)), RECENT_ACTIVITY_LIMIT)
        self.assertEqual(
            compact_activity_rows(["not a row", {"id": "a"}]), [{"id": "a"}]
        )

    def test_unit_of_work_connection_is_used_when_given(self) -> None:
        populate(self)
        source = self._source(make_selector(self))
        with self.manager.unit_of_work() as db:
            self.assertEqual(source.compact(db), source.compact())


class ActivityRowLimitTests(CanonicalContextReadCase):
    def _limited(self, selector: Any, _snapshot: dict[str, Any]) -> tuple[Any, Any]:
        with self.manager.reader() as db:
            return (
                selector.activity_rows(db),
                selector.activity_rows(db, limit=1),
            )

    def test_limit_keeps_the_leading_rows_of_the_tables(self) -> None:
        pending, (full, limited) = self._pending_and_tables(self._limited)

        self.assertEqual(pending, ((), ()))
        self.assertGreater(len(full), 1)
        self.assertEqual(limited, full[:1])


class CoachActivitiesContextTests(CanonicalContextReadCase):
    def _activities(self, selector: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, self._source(selector)
        )
        return reader.activities([])

    def test_activities_section_is_empty_until_the_tables_serve(self) -> None:
        pending, tables = self._pending_and_tables(self._activities)

        self.assertEqual(pending["recent_activities_by_sport"], {})
        self.assertTrue(tables["recent_activities_by_sport"])

    def test_activities_section_does_not_need_the_snapshot_sections(self) -> None:
        full, stripped = self._with_and_without_sections(self._activities)

        self.assertTrue(stripped["recent_activities_by_sport"])
        self.assertEqual(stripped, full)
        self.assertNotIn("recent_activities", self.intervals)

    def test_activities_freshness_comes_from_the_stored_coverage(self) -> None:
        populate(self)
        # An ingest persists the coverage summary next to the records.
        with self.manager.unit_of_work() as db:
            CanonicalCoverageStore(self.key_values).persist(
                db,
                intervals_snapshot_coverage(self.intervals, zone=self.zone),
                zone=self.zone,
            )
        selector = make_selector(self)
        source = ActivitySummarySource(
            lambda: _Manager(self),  # type: ignore[arg-type,return-value]
            lambda: selector,
            coverage=lambda: selector,
        )
        with self.manager.reader() as db:
            (intervals,) = [
                item
                for item in selector.coverage(db)
                if item.provider is ProviderId.INTERVALS
            ]
        # The snapshot's own sync marker is irrelevant once the coverage is stored.
        self.intervals = {**self.intervals, "synced_at": "2030-01-01T00:00:00Z"}
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, source
        )

        section = reader.activities([])

        expected = intervals.activities_retrieved_at.isoformat()
        self.assertEqual(section["synced_at"], expected)
        self.assertEqual(section["source"]["synced_at"], expected)

    def test_read_sources_reads_activities_inside_the_snapshot_unit_of_work(
        self,
    ) -> None:
        populate(self)
        manager = _RecordingManager(self)
        source = ActivitySummarySource(lambda: manager, lambda: make_selector(self))  # type: ignore[arg-type,return-value]
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, source
        )
        _inputs, recent = reader.read_sources()

        assert recent is not None
        self.assertTrue(recent[0])
        self.assertEqual(reader.activities([], recent), reader.activities([]))

    def test_read_sources_without_a_row_source_leaves_rows_unread(self) -> None:
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, None
        )

        _inputs, rows = reader.read_sources()

        self.assertIsNone(rows)

    def test_without_a_row_source_no_activities_are_projected(self) -> None:
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, None
        )

        section = reader.activities([])

        self.assertEqual(section["recent_activities_by_sport"], {})
        self.assertEqual(section["activity_rollups_by_sport"], {})


class HttpStateReadTests(CanonicalContextReadCase):
    def _prelude_activities(
        self, selector: Any, snapshot: dict[str, Any]
    ) -> list[dict[str, Any]]:
        state = Mock()
        state.latest_snapshot.return_value = snapshot
        feedback = Mock()
        feedback.attach_to_activities.side_effect = lambda rows: rows
        planned = Mock()
        planned.list.return_value = []
        weather = Mock()
        weather.state.return_value = {}
        prelude = PublicStateLocalPrelude(
            state,
            feedback,
            planned,
            weather,
            _Manager(self),  # type: ignore[arg-type]
            lambda: TODAY,
            CalendarWindowRange(35, 35),
            None,
            self._source(selector),
        )
        return prelude.read(True).activities

    def test_state_prelude_activities_come_from_the_tables(self) -> None:
        pending, tables = self._pending_and_tables(self._prelude_activities)

        self.assertEqual(pending, [])
        self.assertEqual(_intervals_ids(tables), self._snapshot_ids())

    def test_state_prelude_does_not_need_the_snapshot_sections(self) -> None:
        full, stripped = self._with_and_without_sections(self._prelude_activities)

        self.assertTrue(stripped)
        self.assertEqual(_by_id(stripped), _by_id(full))

    def _plan_activities(
        self, selector: Any, snapshot: dict[str, Any]
    ) -> list[dict[str, Any]]:
        feedback = Mock()
        feedback.attach_to_activities.side_effect = lambda rows: rows
        sync_state = Mock()
        sync_state.latest_snapshot.return_value = snapshot
        planned = Mock()
        planned.list.return_value = []
        weather = Mock()
        weather.state.return_value = {}
        key_values = Mock()
        key_values.get.return_value = None
        calendar = Mock()
        calendar.list_events.return_value = []
        calendar.list_events_in_window.return_value = []
        calendar.state.return_value = {}
        sync = Mock()
        sync.running.return_value = False
        daily = Mock()
        daily.build.return_value = {}
        checkins = Mock()
        checkins.list.return_value = []
        competitions = Mock()
        competitions.list.return_value = []
        preview = Mock()
        preview.latest_preview.return_value = None
        preview.status.return_value = {}
        quick = Mock()
        quick.state.return_value = {}
        plans = Mock()
        plans.list.return_value = []
        service = PublicPlanStateService(
            PublicPlanDependencies(
                sync_state=sync_state,
                planned_units=planned,
                activity_feedback=feedback,
                weather=weather,
                adaptive_followup=Mock(),
                database_manager_factory=lambda: _Manager(self),  # type: ignore[arg-type,return-value]
                key_values=key_values,
                training_plans=plans,
                external_calendar=calendar,
                external_calendar_sync=sync,
                daily_context=daily,
                checkins=checkins,
                competitions=competitions,
                adaptive_preview=preview,
                coach_quick_actions=quick,
                today=lambda: TODAY,
                external_calendar_configured=False,
                external_calendar_window_days=14,
                default_workout_name="Workout",
                activity_rows=self._source(selector),
            )
        )
        service.read(local_only=True)
        return feedback.attach_to_activities.call_args.args[0]

    def test_plan_activities_come_from_the_tables(self) -> None:
        pending, tables = self._pending_and_tables(self._plan_activities)

        self.assertEqual(pending, [])
        self.assertEqual(_intervals_ids(tables), self._snapshot_ids())

    def test_plan_does_not_need_the_snapshot_sections(self) -> None:
        full, stripped = self._with_and_without_sections(self._plan_activities)

        self.assertTrue(stripped)
        self.assertEqual(_by_id(stripped), _by_id(full))


class DiagnosticCountTests(CanonicalContextReadCase):
    @staticmethod
    def _counts(selector: Any, db: Any) -> tuple[int, int]:
        return activity_count(selector, db), wellness_day_count(selector, db, TODAY)

    def _read_counts(self, selector: Any, _snapshot: dict[str, Any]) -> tuple[int, int]:
        with self.manager.reader() as db:
            return self._counts(selector, db)

    def test_counts_are_zero_until_the_tables_serve(self) -> None:
        pending, tables = self._pending_and_tables(self._read_counts)

        self.assertEqual(pending, (0, 0))
        self.assertEqual(tables, (6, 3))

    def test_counts_do_not_need_the_snapshot_sections(self) -> None:
        full, stripped = self._with_and_without_sections(self._read_counts)

        self.assertEqual(stripped, full)

    def test_unwired_readers_count_zero(self) -> None:
        with self.manager.reader() as db:
            self.assertEqual(activity_count(None, db), 0)
            self.assertEqual(wellness_day_count(None, db, TODAY), 0)
