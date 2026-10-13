"""Coach context, HTTP state and diagnostics read activities through the selector.

Each consumer must give the same output while the selector serves the legacy
projection and while it serves the canonical tables, and must not need the
``recent_activities`` / ``raw_provider_data`` / ``recent_wellness`` snapshot
sections once the backfill is complete. All storage is temporary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from datetime import date
from typing import Any, TypeVar
from unittest.mock import Mock

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.coach.context import CoachPerformanceContextReader
from backend.diagnostics.canonical_counts import activity_count, wellness_day_count
from backend.http_api.public_plan import PublicPlanDependencies, PublicPlanStateService
from backend.http_api.state_prelude import CalendarWindowRange, PublicStateLocalPrelude
from backend.planning.compact_activities import (
    RECENT_ACTIVITY_LIMIT,
    ActivityRowSource,
    compact_activity_rows,
)

TODAY = date(2026, 10, 13)
CANONICAL_SECTIONS = ("recent_activities", "recent_wellness", "raw_provider_data")
T = TypeVar("T")


def _by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row["id"]))


class _Manager:
    """Hands the fixture's connection to ``reader``/``unit_of_work`` callers."""

    def __init__(self, case: CanonicalReadFixture) -> None:
        self._case = case

    def reader(self) -> Any:
        return self._case.manager.reader()

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


class CanonicalContextReadCase(CanonicalReadFixture):
    def _source(self, selector: Any) -> ActivityRowSource:
        return ActivityRowSource(lambda: _Manager(self), lambda: selector)  # type: ignore[arg-type,return-value]

    def _both(
        self, read: Callable[[Any, dict[str, Any]], T], *, strip: bool = False
    ) -> tuple[T, T]:
        """Run ``read`` against the legacy projection, then against the tables.

        ``read`` receives the selector and the stored Intervals snapshot. With
        ``strip`` the canonical sections are removed from that snapshot before the
        table read, proving the read no longer needs them.
        """
        legacy = read(make_selector(self), self.intervals)
        populate(self)
        snapshot = self.intervals
        if strip:
            snapshot = {
                key: value
                for key, value in self.intervals.items()
                if key not in CANONICAL_SECTIONS
            }
            self.intervals = snapshot
        return legacy, read(make_selector(self), snapshot)


class CompactActivityTests(CanonicalContextReadCase):
    def test_legacy_rows_compact_to_the_snapshot_recent_activities(self) -> None:
        compact = self._source(make_selector(self)).compact()

        self.assertTrue(compact)
        self.assertEqual(_by_id(compact), _by_id(self.intervals["recent_activities"]))

    def test_tables_serve_the_same_compact_activities_as_legacy(self) -> None:
        legacy, tables = self._both(lambda sel, _snap: self._source(sel).compact())

        self.assertTrue(legacy)
        self.assertEqual(_by_id(tables), _by_id(legacy))

    def test_compaction_is_capped_like_the_snapshot_read_model(self) -> None:
        rows = [{"id": str(index), "name": "x"} for index in range(600)]

        self.assertEqual(len(compact_activity_rows(rows)), RECENT_ACTIVITY_LIMIT)
        self.assertEqual(
            compact_activity_rows(["not a row", {"id": "a"}]), [{"id": "a"}]
        )

    def test_unit_of_work_connection_is_used_when_given(self) -> None:
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

    def test_limit_keeps_the_leading_rows_of_legacy_and_tables(self) -> None:
        legacy, tables = self._both(self._limited)

        for full, limited in (legacy, tables):
            self.assertGreater(len(full), 1)
            self.assertEqual(limited, full[:1])


class CoachActivitiesContextTests(CanonicalContextReadCase):
    def _activities(self, selector: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, self._source(selector)
        )
        return reader.activities(snapshot, [])

    def test_activities_section_is_equal_from_legacy_and_from_tables(self) -> None:
        legacy, tables = self._both(self._activities)

        self.assertTrue(tables["recent_activities_by_sport"])
        self.assertEqual(tables, legacy)

    def test_activities_section_does_not_need_the_snapshot_sections(self) -> None:
        legacy, tables = self._both(self._activities, strip=True)

        self.assertTrue(tables["recent_activities_by_sport"])
        self.assertEqual(tables, legacy)
        self.assertNotIn("recent_activities", self.intervals)

    def test_read_sources_reads_activities_inside_the_snapshot_unit_of_work(
        self,
    ) -> None:
        populate(self)
        manager = _RecordingManager(self)
        source = ActivityRowSource(lambda: manager, lambda: make_selector(self))  # type: ignore[arg-type,return-value]
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, source
        )
        seen: list[bool] = []

        def read_snapshot() -> dict[str, Any]:
            seen.append(manager.open)
            return self.intervals

        snapshot, _inputs, rows = reader.read_sources(read_snapshot)

        self.assertEqual(seen, [True])
        self.assertIs(snapshot, self.intervals)
        self.assertTrue(rows)
        self.assertEqual(
            reader.activities(snapshot, [], rows), reader.activities(snapshot, [])
        )

    def test_read_sources_without_a_row_source_leaves_rows_unread(self) -> None:
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, None
        )

        snapshot, _inputs, rows = reader.read_sources(lambda: self.intervals)

        self.assertIs(snapshot, self.intervals)
        self.assertIsNone(rows)

    def test_without_a_row_source_no_activities_are_projected(self) -> None:
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), Mock(), lambda: TODAY, None, None
        )

        section = reader.activities(self.intervals, [])

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
            nullcontext(),
            lambda: TODAY,
            CalendarWindowRange(35, 35),
            None,
            self._source(selector),
        )
        return _by_id(prelude.read(True).activities)

    def test_state_prelude_activities_are_equal_from_legacy_and_tables(self) -> None:
        legacy, tables = self._both(self._prelude_activities)

        self.assertTrue(legacy)
        self.assertEqual(tables, legacy)

    def test_state_prelude_does_not_need_the_snapshot_sections(self) -> None:
        legacy, tables = self._both(self._prelude_activities, strip=True)

        self.assertTrue(tables)
        self.assertEqual(tables, legacy)

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
                db_lock=nullcontext(),
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
        return _by_id(feedback.attach_to_activities.call_args.args[0])

    def test_plan_activities_are_equal_from_legacy_and_tables(self) -> None:
        legacy, tables = self._both(self._plan_activities)

        self.assertTrue(legacy)
        self.assertEqual(tables, legacy)

    def test_plan_does_not_need_the_snapshot_sections(self) -> None:
        legacy, tables = self._both(self._plan_activities, strip=True)

        self.assertTrue(tables)
        self.assertEqual(tables, legacy)


class DiagnosticCountTests(CanonicalContextReadCase):
    @staticmethod
    def _counts(selector: Any, db: Any) -> tuple[int, int]:
        return activity_count(selector, db), wellness_day_count(selector, db, TODAY)

    def _read_counts(self, selector: Any, _snapshot: dict[str, Any]) -> tuple[int, int]:
        with self.manager.reader() as db:
            return self._counts(selector, db)

    def test_counts_are_equal_from_legacy_and_tables(self) -> None:
        legacy, tables = self._both(self._read_counts)

        self.assertGreater(tables[0], 0)
        self.assertGreater(tables[1], 0)
        self.assertEqual(tables, legacy)

    def test_counts_do_not_need_the_snapshot_sections(self) -> None:
        legacy, tables = self._both(self._read_counts, strip=True)

        self.assertEqual(tables, legacy)

    def test_unwired_readers_count_zero(self) -> None:
        with self.manager.reader() as db:
            self.assertEqual(activity_count(None, db), 0)
            self.assertEqual(wellness_day_count(None, db, TODAY), 0)
