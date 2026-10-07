"""Tests for the local and external calendar conflict use case."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.planning.calendar_service import CalendarConflictService


class _ExternalCalendarReader:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.calls: list[tuple[int, bool]] = []

    def list_events(
        self, limit: int, *, training_relevant_only: bool
    ) -> list[dict[str, Any]]:
        self.calls.append((limit, training_relevant_only))
        return self.events


class CalendarConflictServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self._temporary_directory.name) / "calendar.sqlite"
        self.database_manager = DatabaseManager(
            database_path, sqlite3, row_factory=sqlite3.Row
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, payload TEXT)"
            )
            db.execute(
                "CREATE TABLE competitions ("
                "id TEXT PRIMARY KEY, name TEXT, event_date TEXT, "
                "start_date_local TEXT, moving_time INTEGER)"
            )
        self.external_reader = _ExternalCalendarReader(
            [
                {
                    "id": "external-1",
                    "name": "External event",
                    "event_date": "2026-10-04",
                }
            ]
        )
        self.service = CalendarConflictService(
            self.database_manager, self.external_reader
        )

    def tearDown(self) -> None:
        self.database_manager.close()
        self._temporary_directory.cleanup()

    def _add_planned_unit(
        self,
        local_id: str,
        *,
        archived: bool = False,
        local_deleted: bool = False,
        start_date_local: str | None = None,
        duration_minutes: int | None = None,
    ) -> None:
        payload = {
            "source": "coach",
            "name": local_id,
            "date": "2026-10-04",
            "archived": archived,
            "local_deleted": local_deleted,
        }
        if start_date_local is not None:
            payload["start_date_local"] = start_date_local
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units (local_id, payload) VALUES (?, ?)",
                (local_id, json.dumps(payload)),
            )

    def test_conflicts_keep_source_order_and_exclude_archived_or_deleted_units(
        self,
    ) -> None:
        self._add_planned_unit(
            "active",
            start_date_local="2026-10-04T08:00:00",
            duration_minutes=60,
        )
        self._add_planned_unit("archived", archived=True)
        self._add_planned_unit("deleted", local_deleted=True)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions "
                "(id, name, event_date, start_date_local, moving_time) "
                "VALUES (?, ?, ?, ?, ?)",
                ("race-1", "Local race", "2026-10-04", None, None),
            )

        conflicts = self.service.conflicts(
            {
                "date": "2026-10-04",
                "start_date_local": "2026-10-04T08:30:00",
                "duration_minutes": 30,
            }
        )

        self.assertEqual(
            conflicts,
            [
                {
                    "id": "active",
                    "name": "active",
                    "date": "2026-10-04",
                    "source": "local_library",
                    "match": "time_window",
                    "start_local": "2026-10-04T08:00",
                    "end_local": "2026-10-04T09:00",
                },
                {
                    "id": "race-1",
                    "name": "Local race",
                    "date": "2026-10-04",
                    "source": "local_competition",
                    "match": "date",
                    "start_local": None,
                    "end_local": None,
                },
                {
                    "id": "external-1",
                    "name": "External event",
                    "date": "2026-10-04",
                    "source": "external_calendar",
                    "match": "date",
                    "start_local": None,
                    "end_local": None,
                },
            ],
        )
        self.assertEqual(self.external_reader.calls, [(1000, True)])

    def test_exclude_ids_only_remove_local_library_conflicts(self) -> None:
        self._add_planned_unit(
            "excluded",
            start_date_local="2026-10-04T08:00:00",
            duration_minutes=60,
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions "
                "(id, name, event_date, start_date_local, moving_time) "
                "VALUES (?, ?, ?, ?, ?)",
                ("race-1", "Local race", "2026-10-04", None, None),
            )

        conflicts = self.service.conflicts(
            {
                "date": "2026-10-04",
                "start_date_local": "2026-10-04T08:30:00",
                "duration_minutes": 30,
            },
            {"excluded"},
        )

        self.assertEqual(
            [item["source"] for item in conflicts],
            ["local_competition", "external_calendar"],
        )

    def test_empty_sources_return_no_conflicts(self) -> None:
        self.external_reader.events = []

        self.assertEqual(self.service.conflicts({"date": "2026-10-04"}), [])
        self.assertEqual(self.external_reader.calls, [(1000, True)])

    def test_external_reader_exceptions_propagate(self) -> None:
        class FailingReader:
            def list_events(self, *_args: Any, **_kwargs: Any) -> list[Any]:
                raise RuntimeError("calendar read failed")

        service = CalendarConflictService(self.database_manager, FailingReader())

        with self.assertRaisesRegex(RuntimeError, "calendar read failed"):
            service.conflicts({"date": "2026-10-04"})

    def test_untimed_local_units_do_not_conflict_on_same_date(self) -> None:
        self._add_planned_unit("untimed")
        conflicts = self.service.conflicts({"date": "2026-10-04"})
        self.assertEqual(
            [item["id"] for item in conflicts],
            ["external-1"],
        )

    def test_no_intensity_rejects_unknown_effort_but_allows_explicit_easy(self) -> None:
        self.external_reader.events = [
            {
                "id": "easy-only",
                "name": "Family event",
                "event_date": "2026-10-04",
                "no_intensity": True,
            }
        ]
        conflicts = self.service.conflicts(
            {"date": "2026-10-04", "name": "Intervals", "description": "4x5m"}
        )
        self.assertEqual(conflicts[0]["constraint"], "[NO_INTENSITY]")
        self.assertEqual(
            self.service.conflicts(
                {"date": "2026-10-04", "name": "Easy recovery", "description": "Z1"}
            ),
            [],
        )

    def test_short_only_rejects_long_workouts_but_allows_short_ones(self) -> None:
        self.external_reader.events = [
            {
                "id": "short",
                "name": "[SHORT_ONLY] Dinner",
                "event_date": "2026-10-04",
                "short_only": True,
            }
        ]
        long_conflicts = self.service.conflicts(
            {"date": "2026-10-04", "name": "Endurance", "duration_minutes": 90}
        )
        self.assertEqual(long_conflicts[0]["constraint"], "[SHORT_ONLY]")
        for workout in (
            {"date": "2026-10-04", "name": "Endurance", "duration_minutes": 45},
            {"date": "2026-10-04", "name": "Unknown length"},
        ):
            self.assertEqual(self.service.constraints(workout), [])

    def test_no_training_dominates_and_preserves_source_freshness_evidence(
        self,
    ) -> None:
        self.external_reader.events = [
            {
                "id": "blocked",
                "name": "Travel",
                "event_date": "2026-10-04",
                "no_training": True,
                "updated_at": "sync-1",
            }
        ]
        conflicts = self.service.conflicts(
            {"date": "2026-10-04", "name": "Easy recovery", "description": "Z1"}
        )
        self.assertEqual(conflicts[0]["constraint"], "[NO_TRAINING]")
        self.assertEqual(conflicts[0]["updated_at"], "sync-1")

    def test_no_intensity_rejects_hard_workout_even_with_easy_warmup(self) -> None:
        self.external_reader.events = [
            {
                "id": "hard",
                "name": "Family event",
                "event_date": "2026-10-04",
                "no_intensity": True,
            }
        ]
        conflicts = self.service.conflicts(
            {
                "date": "2026-10-04",
                "name": "Easy warmup + intervals",
                "description": "- 10m easy\n- 4x5m threshold",
            }
        )
        self.assertEqual(conflicts[0]["constraint"], "[NO_INTENSITY]")

    def test_no_intensity_rejects_hard_structured_steps_with_easy_name(self) -> None:
        self.external_reader.events = [
            {
                "id": "hard",
                "name": "Family event",
                "event_date": "2026-10-04",
                "no_intensity": True,
            }
        ]
        conflicts = self.service.conflicts(
            {
                "date": "2026-10-04",
                "name": "Easy recovery",
                "description": "Z1",
                "steps": [{"type": "threshold intervals", "duration": 900}],
            }
        )
        self.assertEqual(conflicts[0]["constraint"], "[NO_INTENSITY]")

    def test_no_intensity_uses_local_day_scope_for_timed_events(self) -> None:
        self.external_reader.events = [
            {
                "id": "short",
                "name": "Family event",
                "start_local": "2026-10-04T08:00:00",
                "end_local": "2026-10-04T09:00:00",
                "no_intensity": True,
            }
        ]
        conflicts = self.service.conflicts(
            {
                "date": "2026-10-04",
                "start_date_local": "2026-10-04T17:00:00",
                "duration_minutes": 30,
                "name": "Hard intervals",
            }
        )
        self.assertEqual(conflicts[0]["constraint"], "[NO_INTENSITY]")

    def test_structured_zone_target_overrides_easy_name(self) -> None:
        self.external_reader.events = [
            {
                "id": "hard",
                "name": "Family event",
                "event_date": "2026-10-04",
                "no_intensity": True,
            }
        ]
        conflicts = self.service.conflicts(
            {
                "date": "2026-10-04",
                "name": "Easy warmup",
                "description": "Z1",
                "steps": [{"target": {"zone": "Z4"}, "duration": 900}],
            }
        )
        self.assertEqual(conflicts[0]["constraint"], "[NO_INTENSITY]")

    def test_no_training_rejects_zero_duration_rest_conversion_with_training_steps(
        self,
    ) -> None:
        self.external_reader.events = [
            {
                "id": "blocked",
                "name": "Travel",
                "event_date": "2026-10-04",
                "no_training": True,
            }
        ]
        conflicts = self.service.conflicts(
            {
                "date": "2026-10-04",
                "name": "Rest",
                "description": "Recovery day",
                "duration_minutes": 0,
                "steps": [{"duration": 300, "target": "power"}],
            }
        )
        self.assertEqual(conflicts[0]["constraint"], "[NO_TRAINING]")

    def test_ambiguous_legacy_constraints_require_refresh_until_success(self):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
            db.execute(
                "INSERT INTO kv VALUES ('external_calendar_constraints_refresh_required', '1', 'before')"
            )
        with self.assertRaises(AppError) as raised:
            self.service.constraints({"date": "2026-10-04"})
        self.assertEqual(raised.exception.reason, "calendar_refresh_required")
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE kv SET value='' WHERE key='external_calendar_constraints_refresh_required'"
            )
        self.assertEqual(self.service.constraints({"date": "2026-10-04"}), [])

    def test_short_only_is_not_an_ordinary_conflict_when_duration_is_allowed(self):
        self.external_reader.events = [
            {
                "id": "short-only",
                "name": "Travel [SHORT_ONLY]",
                "event_date": "2026-10-04",
                "short_only": True,
            }
        ]
        self.assertEqual(
            self.service.conflicts(
                {
                    "date": "2026-10-04",
                    "name": "Easy recovery",
                    "description": "Z1",
                    "duration_minutes": 30,
                }
            ),
            [],
        )

    def test_multi_day_no_training_event_blocks_each_overlapped_day(self) -> None:
        self.external_reader.events = [
            {
                "id": "trip",
                "name": "Travel",
                "event_date": "2026-10-04",
                "start_local": "2026-10-04T00:00:00",
                "end_local": "2026-10-06T00:00:00",
                "all_day": True,
                "no_training": True,
            }
        ]
        for day in ("2026-10-04", "2026-10-05"):
            with self.subTest(day=day):
                conflicts = self.service.conflicts(
                    {"date": day, "name": "Easy recovery", "description": "Z1"}
                )
                self.assertEqual(conflicts[0]["constraint"], "[NO_TRAINING]")
        self.assertEqual(
            self.service.conflicts(
                {"date": "2026-10-06", "name": "Easy recovery", "description": "Z1"}
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
