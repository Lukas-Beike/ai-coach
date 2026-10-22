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
        meal_library.list_products.return_value = []
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
        self.assertNotIn("local_products", result)

    def test_explicit_text_source_still_returns_matching_saved_products(self) -> None:
        meal_library = Mock()
        meal_library.food_database.lookup.return_value = {
            "ok": True,
            "foods": [{"id": "bls:123"}],
            "source": "bls",
        }
        saved = [{"id": f"local-oats-{index}"} for index in range(12)]
        meal_library.list_products.return_value = saved
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
        # Same saved matches as a lookup without an explicit source.
        self.assertEqual(result["local_products"], saved)
        meal_library.list_products.assert_called_once_with(query="Haferflocken")

    def test_explicit_source_outage_still_returns_saved_products(self) -> None:
        meal_library = Mock()
        meal_library.food_database.lookup.side_effect = AppError(
            429, "Lebensmitteldatenbank ist vorübergehend ausgelastet."
        )
        meal_library.list_products.return_value = [{"id": "local-oats"}]
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
            "lookup_food", {"query": " Skyr ", "source": " Open_Food_Facts "}
        )

        assert isinstance(result, dict)
        self.assertEqual(result["foods"], [])
        self.assertEqual(result["local_products"], [{"id": "local-oats"}])
        meal_library.lookup_product.assert_not_called()
        meal_library.food_database.lookup.assert_called_once_with(
            {"query": "Skyr", "source": "open_food_facts"}
        )
        for status in (400, 404, 502):
            meal_library.food_database.lookup.side_effect = AppError(status, "Fehler.")
            with self.subTest(status=status):
                fallback = service.execute(
                    "lookup_food", {"query": "Skyr", "source": "bls"}
                )
                assert isinstance(fallback, dict)
                self.assertEqual(fallback["local_products"], [{"id": "local-oats"}])
                self.assertIn("Fehler.", fallback["notice"])

        meal_library.list_products.return_value = []
        with self.assertRaises(AppError):
            service.execute("lookup_food", {"query": "Haferflocken", "source": "bls"})

    def test_batched_queries_return_each_term_and_isolate_failures(self) -> None:
        meal_library = Mock()

        def lookup(arguments):
            if arguments["query"] == "Pfeffersoße":
                raise AppError(
                    429,
                    "Lebensmitteldatenbank ist vorübergehend ausgelastet.",
                    reason="food_database_rate_limited",
                )
            return {"ok": True, "foods": [{"id": f"local-{arguments['query']}"}]}

        meal_library.lookup_product.side_effect = lookup
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
            "lookup_food",
            {"query": "Reis", "queries": [" Zucchini ", "reis", "Pfeffersoße"]},
        )

        assert isinstance(result, dict)
        self.assertTrue(result["ok"])
        self.assertEqual(
            [item["query"] for item in result["results"]],
            ["Reis", "Zucchini", "Pfeffersoße"],
        )
        self.assertEqual(result["results"][1]["foods"], [{"id": "local-Zucchini"}])
        self.assertEqual(
            result["results"][2],
            {
                "query": "Pfeffersoße",
                "ok": False,
                "error": "Lebensmitteldatenbank ist vorübergehend ausgelastet.",
                "reason": "food_database_rate_limited",
            },
        )
        # Without a source each term keeps the local-first product lookup.
        meal_library.lookup_product.assert_any_call({"query": "Zucchini"})
        meal_library.food_database.lookup.assert_not_called()

        meal_library.lookup_product.side_effect = AppError(429, "Ausgelastet.")
        with self.assertRaises(AppError):
            service.execute("lookup_food", {"queries": ["Reis", "Zucchini"]})
        for arguments in (
            {"queries": "Reis"},
            {"queries": ["Reis"], "barcode": "4001234567890"},
            {"queries": [" "]},
            {"queries": [f"Zutat {index}" for index in range(21)]},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(AppError):
                service.execute("lookup_food", arguments)

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

    def test_omitted_text_source_uses_bls_and_never_queries_open_food_facts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = DatabaseManager(
                Path(temporary) / "nutrition.db", sqlite3, row_factory=sqlite3.Row
            )
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                _diary, meal_library = build_nutrition_services(
                    manager,
                    threading.Lock(),
                    lambda: "2026-10-05T12:00:00+00:00",
                    lambda: datetime(2026, 10, 5, tzinfo=UTC),
                )
                off_client = Mock()
                off_client.search.return_value = [{"id": "off:1"}]
                off_client.product.return_value = {"id": "off:1"}
                meal_library.food_database._off = off_client
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

                result = service.execute("lookup_food", {"query": "Haferflocken"})
            finally:
                manager.close()

        assert isinstance(result, dict)
        self.assertFalse(result["local"])
        self.assertTrue(result["foods"])
        self.assertTrue(all(food["id"].startswith("bls:") for food in result["foods"]))
        off_client.search.assert_not_called()
        off_client.product.assert_not_called()

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
