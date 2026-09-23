"""Tests for the local and external calendar conflict use case."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.db.manager import DatabaseManager
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
        self, local_id: str, *, archived: bool = False, local_deleted: bool = False
    ) -> None:
        payload = {
            "source": "coach",
            "name": local_id,
            "date": "2026-10-04",
            "archived": archived,
            "local_deleted": local_deleted,
        }
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units (local_id, payload) VALUES (?, ?)",
                (local_id, json.dumps(payload)),
            )

    def test_conflicts_keep_source_order_and_exclude_archived_or_deleted_units(
        self,
    ) -> None:
        self._add_planned_unit("active")
        self._add_planned_unit("archived", archived=True)
        self._add_planned_unit("deleted", local_deleted=True)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions "
                "(id, name, event_date, start_date_local, moving_time) "
                "VALUES (?, ?, ?, ?, ?)",
                ("race-1", "Local race", "2026-10-04", None, None),
            )

        conflicts = self.service.conflicts({"date": "2026-10-04"})

        self.assertEqual(
            conflicts,
            [
                {
                    "id": "active",
                    "name": "active",
                    "date": "2026-10-04",
                    "source": "local_library",
                    "match": "date",
                    "start_local": None,
                    "end_local": None,
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
        self._add_planned_unit("excluded")
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions "
                "(id, name, event_date, start_date_local, moving_time) "
                "VALUES (?, ?, ?, ?, ?)",
                ("race-1", "Local race", "2026-10-04", None, None),
            )

        conflicts = self.service.conflicts({"date": "2026-10-04"}, {"excluded"})

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


if __name__ == "__main__":
    unittest.main()
