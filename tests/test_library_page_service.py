"""Read-only workout-library page service tests."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.http_api import pagination
from backend.http_api.library_page import LibraryPageService


class LibraryPageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "library.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.service = LibraryPageService(self.database_manager)

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def _insert(self, row_id: str, payload: str) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (row_id, row_id, payload, "2026-09-23T00:00:00+00:00"),
            )

    def _insert_workout(self, row_id: str, *, sport: str, name: str, **extra) -> None:
        self._insert(row_id, json.dumps({"type": sport, "name": name, **extra}))

    def test_pages_in_keyset_order_and_returns_cursor_triplet_as_strings(self) -> None:
        self._insert_workout("10", sport="Cycling", name="O'Brien — 100%")
        self._insert_workout("2", sport="cycling", name="O'Brien — 100%")
        self._insert_workout("3", sport="Run", name="Easy")

        first = self.service.page(limit=2)
        second = self.service.page(first["next_cursor"], limit=2)

        self.assertEqual(
            [item["name"] for item in first["workouts"]],
            ["O'Brien — 100%"] * 2,
        )
        self.assertEqual(first["limit"], 2)
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual(
            pagination.decode_page_cursor(first["next_cursor"]),
            ["cycling", "o'brien — 100%", "2"],
        )
        self.assertEqual(
            second,
            {
                "workouts": [{"type": "Run", "name": "Easy"}],
                "next_cursor": None,
                "limit": 2,
            },
        )

    def test_invalid_cursor_starts_from_first_page(self) -> None:
        self._insert_workout("1", sport="Run", name="First")
        self._insert_workout("2", sport="Run", name="Second")

        result = self.service.page("not-a-cursor", limit=1)

        self.assertEqual(result["workouts"][0]["name"], "First")
        self.assertIsNotNone(result["next_cursor"])

    def test_limit_is_clamped_to_service_maximum(self) -> None:
        for index in range(4):
            self._insert_workout(str(index), sport="Run", name=f"Run {index}")
        service = LibraryPageService(self.database_manager, maximum=3)

        result = service.page(limit=90)

        self.assertEqual(len(result["workouts"]), 3)
        self.assertEqual(result["limit"], 3)
        self.assertIsNotNone(result["next_cursor"])
        self.assertEqual(self.service.page(limit=0)["limit"], 1)

    def test_filters_to_valid_active_undated_json_objects(self) -> None:
        self._insert_workout("1", sport="Run", name="Keep", archived=False)
        self._insert_workout("2", sport="Run", name="Dated", date="2026-09-23")
        self._insert_workout("3", sport="Run", name="Archived", archived=True)
        self._insert("4", "{")
        self._insert("5", "[]")
        self._insert("6", '"text"')

        result = self.service.page()

        self.assertEqual(
            result["workouts"],
            [{"type": "Run", "name": "Keep", "archived": False}],
        )
        self.assertIsNone(result["next_cursor"])


if __name__ == "__main__":
    unittest.main()
