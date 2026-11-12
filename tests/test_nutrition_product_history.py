"""Saved food products record change history, so a Coach turn can undo them.

Temporary database and synthetic products only.
"""

from __future__ import annotations

import sqlite3
import threading
import unittest
from datetime import UTC, datetime
from typing import Any

from nutrition_service_support import build_nutrition_services
from support import temp_database

from backend import change_history
from backend.coach.change_receipts import change_summary
from backend.db.repositories import FoodDatabaseEntryRepository
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.nutrition.food_mirror import FoodDatabaseMirror

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
        self.manager = temp_database(
            self, "product_history.db", row_factory=sqlite3.Row, schema=True
        )
        self.diary, self.library = build_nutrition_services(
            self.manager,
            threading.Lock(),
            lambda: "2026-09-24T12:00:00+00:00",
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )
        self.catalog = self.library.product_catalog
        self.mirror = FoodDatabaseMirror(
            lambda: self.manager, threading.Lock(), lambda: "2026-09-24T12:00:00+00:00"
        )

    def collected(self, write: Any) -> tuple[Any, list[dict[str, str]]]:
        with change_history.collect_changes() as changes:
            result = write()
        return result, changes

    def undo(self, changes: list[dict[str, str]]) -> None:
        unused: Any = None
        services = {
            "nutrition_product": self.catalog,
            "food_database_entry": self.mirror,
        }
        undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, unused, record_services=services),
            *(unused,) * 6,
            record_services=services,
            profile_mutation_coordinator=threading.RLock(),
        )
        with self.manager.unit_of_work() as db:
            undo.apply_many(db, changes)

    def stored_food(self, food_id: str) -> dict[str, Any]:
        entry = self.mirror.get(food_id)
        assert entry is not None
        return entry

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
        saved = self.library.product_catalog.save_product(PRODUCT)
        self.library.product_catalog.update_product(saved["id"], {"kcal": 70})
        self.library.product_catalog.update_product(saved["id"], {"kcal": 70})
        self.library.product_catalog.set_favorite(saved["id"], True)
        self.library.product_catalog.archive_product(saved["id"])
        self.assertEqual(self.history_actions(), ["create", "update", "update"])

    def test_undo_of_a_created_product_removes_it(self) -> None:
        saved, changes = self.collected(
            lambda: self.library.product_catalog.save_product(PRODUCT)
        )
        self.undo(changes)
        with self.assertRaises(AppError):
            self.library.product_catalog.get_product(saved["id"])

    def test_undo_of_an_edit_restores_the_previous_values(self) -> None:
        saved = self.library.product_catalog.save_product(PRODUCT)
        _, changes = self.collected(
            lambda: self.library.product_catalog.update_product(
                saved["id"], {"name": "Quark", "kcal": 80, "sugar_g": 3}
            )
        )
        self.undo(changes)
        restored = self.library.product_catalog.get_product(saved["id"])
        for key in ("name", "brand", "barcode", "kcal", "carbs_g", "sugar_g"):
            self.assertEqual(restored[key], saved[key], key)

    def test_undo_of_an_archive_brings_the_product_back(self) -> None:
        saved = self.library.product_catalog.save_product(PRODUCT)
        archived, changes = self.collected(
            lambda: self.library.product_catalog.archive_product(saved["id"])
        )
        self.assertEqual(archived["status"], "archived")
        self.undo(changes)
        self.assertEqual(
            self.library.product_catalog.get_product(saved["id"])["status"], "active"
        )
        self.assertEqual(
            self.library.product_catalog.calculate_product(saved["id"], 200, "g")[
                "kcal"
            ],
            126,
        )

    def test_undo_of_a_delete_restores_unset_fields_and_stays_usable(self) -> None:
        saved = self.library.product_catalog.save_product(
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
        restored = self.library.product_catalog.get_product(saved["id"])
        self.assertIsNone(restored["sugar_g"])
        self.assertIsNone(restored["barcode"])
        self.assertEqual(restored["kcal"], 63)
        calculated = self.library.product_catalog.calculate_product(
            saved["id"], 50, "g"
        )
        self.assertEqual(calculated["kcal"], 31.5)

    def test_undo_keeps_diary_entries_that_used_the_product(self) -> None:
        saved = self.library.product_catalog.save_product(PRODUCT)
        _, changes = self.collected(
            lambda: self.library.product_catalog.archive_product(saved["id"])
        )
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
        saved = self.library.product_catalog.save_product(PRODUCT)
        _, changes = self.collected(
            lambda: self.library.product_catalog.update_product(
                saved["id"], {"barcode": None}
            )
        )
        self.library.product_catalog.save_product({**PRODUCT, "name": "Other"})
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)

    def test_undo_is_refused_after_a_later_edit(self) -> None:
        saved, changes = self.collected(
            lambda: self.library.product_catalog.save_product(PRODUCT)
        )
        self.library.product_catalog.update_product(saved["id"], {"kcal": 64})
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(
            self.library.product_catalog.get_product(saved["id"])["kcal"], 64
        )

    def test_undo_of_a_gap_fill_empties_exactly_the_filled_fields(self) -> None:
        own = self.catalog.save_product({**PRODUCT, "fat_g": None, "salt_g": None})
        food: dict[str, Any] = {
            "id": "off:4006381333931",
            "name": "Synthetic bar",
            "basis_amount": 100,
            "basis_unit": "g",
            "per_100": {"kcal": 500, "salt_g": None},
        }
        with self.manager.unit_of_work() as db:
            FoodDatabaseEntryRepository().upsert(db, food, "2026-09-01")
        fill = [
            {"id": own["id"], "values": {"fat_g": 1.5, "salt_g": 0.2}, "origin": "bls"},
            {"id": food["id"], "values": {"salt_g": 0.7, "kcal": 1}, "origin": "yazio"},
        ]
        result, changes = self.collected(lambda: self.catalog.fill_product_gaps(fill))

        self.assertEqual(
            [item["id"] for item in result["changes"]], [own["id"], food["id"]]
        )
        self.assertEqual(
            [(change["action"], change["entity_type"]) for change in changes],
            [("update", "nutrition_product"), ("update", "food_database_entry")],
        )
        self.assertEqual(self.stored_food(food["id"])["per_100"]["salt_g"], 0.7)
        self.assertEqual(self.stored_food(food["id"])["per_100"]["kcal"], 500)

        self.undo(changes)

        restored = self.catalog.get_product(own["id"])
        self.assertEqual((restored["fat_g"], restored["salt_g"]), (None, None))
        self.assertEqual((restored["kcal"], restored["filled_fields"]), (63, {}))
        entry = self.stored_food(food["id"])
        self.assertEqual(
            (entry["per_100"]["salt_g"], entry["per_100"]["kcal"]), (None, 500)
        )
        self.assertEqual(entry["filled_fields"], {})

    def test_undo_of_a_gap_fill_is_refused_after_the_food_changed(self) -> None:
        food: dict[str, Any] = {
            "id": "yazio:0a1b2c3d-0000-4000-8000-000000000001",
            "name": "Synthetic oat drink",
            "basis_amount": 100,
            "basis_unit": "ml",
            "per_100": {"kcal": 45},
        }
        with self.manager.unit_of_work() as db:
            FoodDatabaseEntryRepository().upsert(db, food, "2026-09-01")
        _, changes = self.collected(
            lambda: self.catalog.fill_product_gaps(
                [{"id": food["id"], "values": {"fat_g": 1}, "origin": "bls"}]
            )
        )
        with self.manager.unit_of_work() as db:
            FoodDatabaseEntryRepository().upsert(
                db, {**food, "per_100": {"kcal": 45, "fat_g": 2}}, "2026-09-02"
            )
        with self.assertRaises(AppError) as raised:
            self.undo(changes)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.stored_food(food["id"])["per_100"]["fat_g"], 2)

    def test_a_coach_turn_that_saves_a_product_is_undoable(self) -> None:
        summary = change_summary(
            [
                {
                    "tool": tool,
                    "result": {"ok": True},
                    "changes": [{"id": "x", "action": "create"}],
                }
                for tool in ("save_nutrition_product", "fill_nutrition_product_gaps")
            ]
        )
        assert summary is not None
        self.assertTrue(summary["undoable"])


if __name__ == "__main__":
    unittest.main()
