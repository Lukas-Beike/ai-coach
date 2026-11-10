"""Saved food products record change history, so a Coach turn can undo them.

Temporary database and synthetic products only.
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

PRODUCT: dict[str, Any] = {
    "name": "Skyr",
    "brand": "Arla",
    "barcode": "5711953068011",
    "basis_amount": 100,
    "basis_unit": "g",
    "kcal": 63,
    "carbs_g": 4,
    "protein_g": 11,
    "fat_g": 0.2,
    "source": "manual",
}


class NutritionProductHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temp_dir.name) / "product_history.db",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.diary, self.library = build_nutrition_services(
            self.manager,
            threading.Lock(),
            lambda: "2026-09-24T12:00:00+00:00",
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )
        self.catalog = self.library.product_catalog

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def collected(self, write: Any) -> tuple[Any, list[dict[str, str]]]:
        with change_history.collect_changes() as changes:
            result = write()
        return result, changes

    def undo(self, changes: list[dict[str, str]]) -> None:
        unused: Any = None
        services = {"nutrition_product": self.catalog}
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, unused, record_services=services),
            *(unused,) * 6,
            record_services=services,
            profile_mutation_coordinator=threading.RLock(),
        )
        with self.manager.unit_of_work() as db:
            undo.apply_many(db, changes)

    def history_actions(self) -> list[str]:
        with self.manager.reader() as db:
            return [
                row["action"]
                for row in db.execute(
                    "SELECT action FROM change_history WHERE entity_type="
                    "'nutrition_product' ORDER BY created_at, rowid"
                ).fetchall()
            ]

    def test_create_update_and_archive_each_record_one_change(self) -> None:
        saved = self.library.save_product(PRODUCT)
        self.library.update_product(saved["id"], {"kcal": 70})
        self.library.update_product(saved["id"], {"kcal": 70})
        self.library.set_product_favorite(saved["id"], True)
        self.library.archive_product(saved["id"])
        self.assertEqual(self.history_actions(), ["create", "update", "update"])

    def test_undo_of_a_created_product_removes_it(self) -> None:
        saved, changes = self.collected(lambda: self.library.save_product(PRODUCT))
        self.undo(changes)
        with self.assertRaises(AppError):
            self.library.get_product(saved["id"])

    def test_undo_of_an_edit_restores_the_previous_values(self) -> None:
        saved = self.library.save_product(PRODUCT)
        _, changes = self.collected(
            lambda: self.library.update_product(
                saved["id"], {"name": "Quark", "kcal": 80, "sugar_g": 3}
            )
        )
        self.undo(changes)
        restored = self.library.get_product(saved["id"])
        for key in ("name", "brand", "barcode", "kcal", "carbs_g", "sugar_g"):
            self.assertEqual(restored[key], saved[key], key)

    def test_undo_of_an_archive_brings_the_product_back(self) -> None:
        saved = self.library.save_product(PRODUCT)
        archived, changes = self.collected(
            lambda: self.library.archive_product(saved["id"])
        )
        self.assertEqual(archived["status"], "archived")
        self.undo(changes)
        self.assertEqual(self.library.get_product(saved["id"])["status"], "active")
        self.assertEqual(
            self.library.calculate_product(saved["id"], 200, "g")["kcal"], 126
        )

    def test_undo_of_a_delete_restores_unset_fields_and_stays_usable(self) -> None:
        saved = self.library.save_product(
            {key: value for key, value in PRODUCT.items() if key != "barcode"}
        )
        self.assertIsNone(saved["sugar_g"])
        self.assertIsNone(saved["barcode"])
        with self.manager.unit_of_work() as db:
            self.catalog._products.delete(db, saved["id"])
            record = change_history.record_change(
                db, "nutrition_product", saved["id"], "delete", saved, None
            )
        assert record is not None
        self.undo([{key: record[key] for key in change_history.UNDO_REFERENCE_FIELDS}])
        restored = self.library.get_product(saved["id"])
        self.assertIsNone(restored["sugar_g"])
        self.assertIsNone(restored["barcode"])
        self.assertEqual(restored["kcal"], 63)
        calculated = self.library.calculate_product(saved["id"], 50, "g")
        self.assertEqual(calculated["kcal"], 31.5)

    def test_undo_keeps_diary_entries_that_used_the_product(self) -> None:
        saved = self.library.save_product(PRODUCT)
        _, changes = self.collected(lambda: self.library.archive_product(saved["id"]))
        meal = self.diary.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "snack",
                "description": "Skyr",
                "kcal": 63,
            }
        )
        self.undo(changes)
        self.assertEqual(self.diary.get_meal(meal["id"])["description"], "Skyr")

    def test_undo_is_refused_when_the_barcode_was_taken(self) -> None:
        saved = self.library.save_product(PRODUCT)
        _, changes = self.collected(
            lambda: self.library.update_product(saved["id"], {"barcode": None})
        )
        self.library.save_product({**PRODUCT, "name": "Other"})
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)

    def test_undo_is_refused_after_a_later_edit(self) -> None:
        saved, changes = self.collected(lambda: self.library.save_product(PRODUCT))
        self.library.update_product(saved["id"], {"kcal": 64})
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.library.get_product(saved["id"])["kcal"], 64)

    def test_a_coach_turn_that_saves_a_product_is_undoable(self) -> None:
        summary = change_summary(
            [
                {
                    "tool": "save_nutrition_product",
                    "result": {"ok": True},
                    "changes": [{"id": "x", "action": "create"}],
                }
            ]
        )
        assert summary is not None
        self.assertTrue(summary["undoable"])


if __name__ == "__main__":
    unittest.main()
