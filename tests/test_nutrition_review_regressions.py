from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from backend.coach.read_tools import CoachReadToolService
from backend.db.manager import DatabaseManager
from backend.db.repositories import NutritionRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition.service import NutritionService


class NutritionReviewRegressionTests(unittest.TestCase):
    def test_explicit_text_source_bypasses_local_products(self) -> None:
        nutrition = Mock()
        nutrition.food_database.lookup.return_value = {
            "ok": True,
            "foods": [{"id": "bls:123"}],
            "source": "bls",
        }
        service = CoachReadToolService(
            *[Mock() for _ in range(8)],
            training_change_limit=366,
            nutrition_service=Mock(return_value=nutrition),
        )

        result = service.execute(
            "lookup_food", {"query": "Haferflocken", "source": "bls"}
        )

        self.assertEqual(result["source"], "bls")
        nutrition.food_database.lookup.assert_called_once_with(
            {"query": "Haferflocken", "source": "bls"}
        )
        nutrition.lookup_product.assert_not_called()

    def test_barcode_source_keeps_local_first_lookup(self) -> None:
        nutrition = Mock()
        nutrition.lookup_product.return_value = {
            "ok": True,
            "product": {"id": "local-product"},
            "source": "local",
        }
        service = CoachReadToolService(
            *[Mock() for _ in range(8)],
            training_change_limit=366,
            nutrition_service=Mock(return_value=nutrition),
        )

        result = service.execute(
            "lookup_food", {"barcode": "4006381333931", "source": "off"}
        )

        self.assertEqual(result["source"], "local")
        nutrition.lookup_product.assert_called_once_with(
            {"barcode": "4006381333931", "source": "off"}
        )
        nutrition.food_database.lookup.assert_not_called()

    def test_archived_products_cannot_be_calculated_or_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = DatabaseManager(
                Path(temporary) / "nutrition.db", sqlite3, row_factory=sqlite3.Row
            )
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                service = NutritionService(
                    database_manager=manager,
                    db_lock=threading.Lock(),
                    nutrition_repository=NutritionRepository(
                        now=lambda: "2026-10-05T12:00:00+00:00"
                    ),
                    utc_now=lambda: "2026-10-05T12:00:00+00:00",
                    local_now=lambda: datetime(2026, 10, 5, tzinfo=timezone.utc),
                )
                product = service.save_product(
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
                service.archive_product(product["id"])

                for operation in (
                    lambda: service.calculate_product(product["id"], 50, "g"),
                    lambda: service.log_product(product["id"], 50, "g"),
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
