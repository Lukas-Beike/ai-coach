"""Diary entries record change history, so a Coach turn can undo them.

Temporary database and synthetic meals only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nutrition_service_support import build_nutrition_services

from backend import change_history
from backend.coach.change_receipts import change_summary
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService

MEAL = {
    "meal_date": "2026-09-24",
    "meal_type": "lunch",
    "description": "Rice bowl",
    "kcal": 600,
    "carbs_g": 80,
}


class NutritionHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temp_dir.name) / "nutrition_history.db",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.diary, _library = build_nutrition_services(
            self.manager,
            threading.Lock(),
            lambda: "2026-09-24T12:00:00+00:00",
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def collected(self, write: Any) -> tuple[Any, list[dict[str, str]]]:
        with change_history.collect_changes() as changes:
            result = write()
        return result, changes

    def undo(self, changes: list[dict[str, str]]) -> None:
        unused: Any = None
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, unused, nutrition_diary=self.diary),
            *(unused,) * 6,
            nutrition_diary=self.diary,
            profile_mutation_coordinator=threading.RLock(),
        )
        with self.manager.unit_of_work() as db:
            undo.apply_many(db, changes)

    def pending_revision(self) -> int:
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT revision FROM nutrition_sync_dates WHERE meal_date=? "
                "AND sync_state='pending'",
                (MEAL["meal_date"],),
            ).fetchone()
        return int(row["revision"]) if row else 0

    def test_undo_of_a_logged_meal_removes_it(self) -> None:
        entry, changes = self.collected(lambda: self.diary.log_meal(MEAL))
        self.assertEqual([change["action"] for change in changes], ["create"])
        self.undo(changes)
        with self.assertRaises(AppError):
            self.diary.get_meal(entry["id"])
        self.assertEqual(self.pending_revision(), 2)

    def test_undo_of_a_correction_restores_the_previous_values(self) -> None:
        entry = self.diary.log_meal(MEAL)
        _, changes = self.collected(
            lambda: self.diary.correct_meal(entry["id"], {"kcal": 450})
        )
        self.undo(changes)
        restored = self.diary.get_meal(entry["id"])
        self.assertEqual(restored["kcal"], 600)
        self.assertEqual(restored["carbs_g"], 80)

    def test_undo_of_a_delete_brings_the_entry_back_after_a_sync(self) -> None:
        entry = self.diary.log_meal(MEAL)
        _, changes = self.collected(lambda: self.diary.delete_meal(entry["id"]))
        self.undo(changes)
        restored = self.diary.get_meal(entry["id"])
        self.assertEqual(restored["description"], "Rice bowl")
        self.assertEqual(restored["nutrition_basis"], entry["nutrition_basis"])
        # A later sync marks the day; undo of the original log still applies.
        self.diary.mark_date_synced(MEAL["meal_date"], self.pending_revision())
        _, created = self.collected(lambda: self.diary.log_meal(MEAL))
        self.diary.mark_date_synced(MEAL["meal_date"], self.pending_revision())
        self.undo(created)
        self.assertEqual(
            self.diary.get_day_summary(MEAL["meal_date"])["entry_count"], 1
        )
        self.assertGreater(self.pending_revision(), 0)

    def test_undo_is_refused_after_a_later_edit(self) -> None:
        entry, changes = self.collected(lambda: self.diary.log_meal(MEAL))
        self.diary.correct_meal(entry["id"], {"kcal": 500})
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.diary.get_meal(entry["id"])["kcal"], 500)

    def test_a_coach_turn_that_logs_meals_is_undoable(self) -> None:
        for tool in (
            "save_nutrition_entry",
            "update_nutrition_entry",
            "delete_nutrition_entry",
            "log_nutrition_template",
        ):
            summary = change_summary(
                [
                    {
                        "tool": tool,
                        "result": {"ok": True},
                        "changes": [{"id": "x", "action": "create"}],
                    }
                ]
            )
            assert summary is not None
            self.assertTrue(summary["undoable"], tool)


if __name__ == "__main__":
    unittest.main()
