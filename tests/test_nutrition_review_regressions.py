from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

from nutrition_service_support import build_nutrition_services

from backend.coach.read_tools import CoachReadToolService
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.errors import AppError


class NutritionReviewRegressionTests(unittest.TestCase):
    def test_explicit_text_source_bypasses_local_products(self) -> None:
        meal_library = Mock()
        meal_library.food_database.lookup.return_value = {
            "ok": True,
            "foods": [{"id": "bls:123"}],
            "source": "bls",
        }
        service = CoachReadToolService(
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            training_change_limit=366,
            nutrition_meal_library=Mock(return_value=meal_library),
        )

        result = service.execute(
            "lookup_food", {"query": "Haferflocken", "source": "bls"}
        )

        assert isinstance(result, dict)
        self.assertEqual(result["source"], "bls")
        meal_library.food_database.lookup.assert_called_once_with(
            {"query": "Haferflocken", "source": "bls"}
        )
        meal_library.lookup_product.assert_not_called()

    def test_barcode_source_keeps_local_first_lookup(self) -> None:
        meal_library = Mock()
        meal_library.lookup_product.return_value = {
            "ok": True,
            "product": {"id": "local-product"},
            "source": "local",
        }
        service = CoachReadToolService(
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            training_change_limit=366,
            nutrition_meal_library=Mock(return_value=meal_library),
        )

        result = service.execute(
            "lookup_food", {"barcode": "4006381333931", "source": "off"}
        )

        assert isinstance(result, dict)
        self.assertEqual(result["source"], "local")
        meal_library.lookup_product.assert_called_once_with(
            {"barcode": "4006381333931", "source": "off"}
        )
        meal_library.food_database.lookup.assert_not_called()

    def test_archived_products_cannot_be_calculated_or_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = DatabaseManager(
                Path(temporary) / "nutrition.db", sqlite3, row_factory=sqlite3.Row
            )
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                diary, meal_library = build_nutrition_services(
                    manager,
                    threading.Lock(),
                    lambda: "2026-10-05T12:00:00+00:00",
                    lambda: datetime(2026, 10, 5, tzinfo=UTC),
                )
                product = meal_library.save_product(
                    {
                        "name": "Synthetic whey",
                        "brand": "Synthetic",
                        "barcode": "4006381333931",
                        "basis_amount": 100,
                        "basis_unit": "g",
                        "kcal": 376,
                        "protein_g": 78,
                        "carbs_g": 8,
                        "fat_g": 5.5,
                        "source": "packaging_label",
                    }
                )
                meal_library.archive_product(product["id"])

                for operation in (
                    lambda: meal_library.calculate_product(product["id"], 50, "g"),
                    lambda: diary.log_product(product["id"], 50, "g"),
                ):
                    with (
                        self.subTest(operation=operation),
                        self.assertRaises(AppError) as caught,
                    ):
                        operation()
                    self.assertEqual(
                        caught.exception.reason, "nutrition_product_archived"
                    )
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
