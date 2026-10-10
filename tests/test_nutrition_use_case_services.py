from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.db.manager import DatabaseManager
from backend.db.repositories import NutritionProductRepository, NutritionRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition.catalog import ProductCatalogService
from backend.nutrition.components import MealComponentCalculator
from backend.nutrition.food_database import FoodDatabaseService
from backend.nutrition.photo_service import PhotoExtractionService
from backend.nutrition.sync_status import NutritionSyncStatusService


class NutritionUseCaseServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary.name) / "nutrition.db",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.lock = threading.Lock()
        self.now = "2026-09-24T12:00:00Z"
        self.repository = NutritionRepository(now=lambda: self.now)
        product_repository = NutritionProductRepository()
        food_database = FoodDatabaseService()
        self.products = ProductCatalogService(
            self.manager,
            self.lock,
            product_repository,
            lambda: self.now,
            food_database,
            MealComponentCalculator(product_repository, food_database),
        )
        self.sync_status = NutritionSyncStatusService(
            self.manager,
            self.lock,
            self.repository,
            lambda: self.now,
            lambda: datetime(2026, 9, 24, 12, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary.cleanup()

    def test_catalog_persists_and_calculates_confirmed_product(self) -> None:
        product = self.products.save_product(
            {
                "name": "Synthetic oats",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 350,
                "carbs_g": 60,
                "protein_g": 12,
                "fat_g": 7,
            }
        )
        calculation = self.products.calculate_product(product["id"], 50, "g")
        self.assertEqual(calculation["kcal"], 175)
        self.assertEqual(calculation["nutrition_basis"]["kind"], "local_product")

    def test_component_calculator_combines_local_manual_and_database_foods(
        self,
    ) -> None:
        product = self.products.save_product(
            {
                "name": "Synthetic oats",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 350,
                "carbs_g": 60,
                "protein_g": 12,
                "fat_g": 7,
            }
        )
        components = [
            {
                "kind": "local_product",
                "product_id": product["id"],
                "amount": 50,
                "unit": "g",
            },
            {
                "kind": "manual",
                "name": "Synthetic honey",
                "amount": 10,
                "unit": "g",
                "kcal": 30,
                "carbs_g": 8,
                "protein_g": 0,
                "fat_g": 0,
            },
            {
                "kind": "database",
                "food_id": "bls:C133000",
                "amount": 50,
                "unit": "g",
            },
        ]
        calculator = MealComponentCalculator(
            NutritionProductRepository(), FoodDatabaseService()
        )
        resolved = calculator.prepare_resolutions(components)
        with self.manager.unit_of_work() as db:
            result = calculator.calculate(db, components, resolved)
        snapshots = result["nutrition_basis"]["components"]
        self.assertEqual(
            [item["kind"] for item in snapshots],
            ["local_product", "manual", "database"],
        )
        self.assertEqual(
            snapshots[0]["nutrition_basis"]["product"]["id"], product["id"]
        )
        self.assertEqual(snapshots[1]["nutrition_basis"], {"kind": "manual"})
        self.assertEqual(snapshots[2]["nutrition_basis"]["food"]["id"], "bls:C133000")
        self.assertEqual(result["kcal"], round(sum(item["kcal"] for item in snapshots)))
        for nutrient in ("carbs_g", "protein_g", "fat_g"):
            self.assertEqual(
                result[nutrient], round(sum(item[nutrient] for item in snapshots), 1)
            )

    def test_component_calculator_rejects_local_product_unit_mismatch(self) -> None:
        product = self.products.save_product(
            {
                "name": "Synthetic oats",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 350,
            }
        )
        calculator = MealComponentCalculator(
            NutritionProductRepository(), FoodDatabaseService()
        )
        components = [
            {
                "kind": "local_product",
                "product_id": product["id"],
                "amount": 50,
                "unit": "ml",
            }
        ]
        with (
            self.assertRaises(AppError) as raised,
            self.manager.unit_of_work() as db,
        ):
            calculator.calculate(db, components, {})
        self.assertEqual(raised.exception.reason, "food_unit_mismatch")

    def test_photo_wrapper_validates_local_candidate_without_provider(self) -> None:
        result = PhotoExtractionService(None).extract_packaging_photo(
            {
                "name": "Synthetic snack",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 200,
            }
        )
        self.assertTrue(result["requires_confirmation"])
        self.assertIn("extraction", result)
        with self.assertRaises(AppError):
            PhotoExtractionService(None).extract_packaging_photo(
                {"image_data_url": "data:image/jpeg;base64,YQ=="}
            )

    def test_sync_status_reads_empty_manifest_and_pending_dates(self) -> None:
        manifest = self.sync_status.approval_manifest(meal_date="2026-09-24")
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["date"], "2026-09-24")
        self.assertEqual(manifest[0]["entry_count"], 0)
        self.assertEqual(self.sync_status.list_unsynced_dates(), [])
        with self.assertRaises(AppError):
            self.sync_status.approval_manifest()


if __name__ == "__main__":
    unittest.main()
