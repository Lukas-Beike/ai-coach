from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from backend.errors import AppError
from backend.nutrition.food_database import FoodDatabaseService, _bls_foods
from backend.providers.open_food_facts import OpenFoodFactsClient, project_product


def product(**changes):
    return {
        "code": "1234567890123",
        "product_name_de": "Synthetic food",
        "nutrition_data_per": "100g",
        "nutriments": {"energy-kcal_100g": 200, "proteins_100g": 10, "fat_100g": 5},
        **changes,
    }


def response(payload):
    result = io.BytesIO(json.dumps(payload).encode())
    result.status = 200
    return result


class FoodDatabaseTests(unittest.TestCase):
    def test_current_off_schema_uses_label_values_and_excludes_provider_estimates(self):
        raw = product(
            nutrition={
                "aggregated_set": {
                    "per": "100ml",
                    "preparation": "as_sold",
                    "nutrients": {
                        "energy-kcal": {
                            "value": 50,
                            "unit": "kcal",
                            "source": "manufacturer",
                        },
                        "carbohydrates": {
                            "value": 10,
                            "unit": "g",
                            "source": "estimate",
                        },
                        "proteins": {"value": 2, "unit": "g", "source": "packaging"},
                        "fat": {
                            "value": 4,
                            "unit": "g",
                            "source": "packaging",
                            "modifier": "<",
                        },
                    },
                }
            }
        )
        projected = project_product(raw)
        self.assertEqual(projected["per_100"]["kcal"], 50)
        self.assertEqual(projected["basis_unit"], "ml")
        self.assertEqual(projected["per_100"]["protein_g"], 2)
        self.assertIsNone(projected["per_100"]["carbs_g"])
        self.assertIsNone(projected["per_100"]["fat_g"])
        self.assertEqual(projected["origins"]["energy-kcal"], "manufacturer")

    def test_bls_is_complete_offline_and_calculates_edible_grams(self):
        off = Mock()
        service = FoodDatabaseService(off)
        self.assertEqual(len(_bls_foods()), 7140)
        found = service.lookup({"query": "Haferflocken"})
        self.assertIn("bls:C133000", [food["id"] for food in found["foods"]])
        result = service.calculate(
            [{"food_id": "bls:C133000", "amount": 50, "unit": "g"}]
        )
        self.assertEqual(result["kcal"], 174)
        self.assertEqual(result["carbs_g"], 26.6)
        self.assertEqual(
            result["nutrition_basis"]["ingredients"][0]["license"], "CC BY 4.0"
        )
        off.product.assert_not_called()
        off.search.assert_not_called()

    def test_unknown_macros_are_not_zero_and_units_are_not_guessed(self):
        off = Mock()
        off.product.return_value = project_product(product())
        service = FoodDatabaseService(off)
        ingredients = [{"food_id": "off:1234567890123", "amount": 150, "unit": "g"}]
        result = service.calculate(ingredients)
        self.assertEqual(result["kcal"], 300)
        self.assertIsNone(result["carbs_g"])
        ingredients[0]["unit"] = "ml"
        with self.assertRaises(AppError):
            service.calculate(ingredients)
        off.product.return_value = project_product(
            product(nutrition_data_per="serving")
        )
        ingredients[0]["unit"] = "g"
        with self.assertRaises(AppError):
            service.calculate(ingredients)

    def test_untrusted_numbers_and_ingredient_bounds(self):
        invalid = product(
            nutriments={
                "energy-kcal_100g": "nan",
                "energy-kj_100g": 418.4,
                "proteins_100g": -1,
            }
        )
        projected = project_product(invalid)
        self.assertEqual(projected["per_100"]["kcal"], 100)
        self.assertIsNone(projected["per_100"]["protein_g"])
        service = FoodDatabaseService(Mock())
        for amount in (True, -1, 0, 5001, "nan", "inf"):
            with self.subTest(amount=amount), self.assertRaises(AppError):
                service.calculate(
                    [{"food_id": "bls:C133000", "amount": amount, "unit": "g"}]
                )
        with self.assertRaises(AppError):
            service.calculate([])
        with self.assertRaises(AppError):
            service.resolve("off:https://localhost")


class OpenFoodFactsTests(unittest.TestCase):
    def test_cache_limits_and_privacy_safe_bounded_transport(self):
        opener = Mock(
            side_effect=lambda request, timeout: response({"product": product()})
        )
        clock = Mock(return_value=0)
        client = OpenFoodFactsClient(opener=opener, clock=clock)
        client.product("1234567890123")
        client.product("1234567890123")
        self.assertEqual(opener.call_count, 1)
        req = opener.call_args.args[0]
        self.assertTrue(
            req.full_url.startswith("https://world.openfoodfacts.org/api/v3.6/product/")
        )
        self.assertIn("IntervalsCoach", req.get_header("User-agent"))
        self.assertIsNone(req.get_header("Authorization"))
        self.assertEqual(opener.call_args.kwargs["timeout"], 10)
        for index in range(13):
            client.product(str(1234567891000 + index))
        with self.assertRaises(AppError) as raised:
            client.product("1234567892000")
        self.assertEqual(raised.exception.status, 429)
        clock.return_value = 61
        client.product("1234567892000")

    def test_search_filters_germany_and_has_independent_limit(self):
        opener = Mock(
            side_effect=lambda request, timeout: response({"products": [product()]})
        )
        client = OpenFoodFactsClient(opener=opener)
        for index in range(9):
            self.assertEqual(len(client.search("Synthetic " + str(index))), 1)
        self.assertIn("tag_0=germany", opener.call_args.args[0].full_url)
        with self.assertRaises(AppError):
            client.search("Synthetic tenth")

    def test_provider_backoff_and_errors_do_not_expose_query_or_response(self):
        clock = Mock(return_value=0)
        opener = Mock(
            side_effect=HTTPError(
                "https://world.openfoodfacts.org/", 429, "Synthetic secret", {}, None
            )
        )
        client = OpenFoodFactsClient(opener=opener, clock=clock)
        for _ in range(2):
            with self.assertRaises(AppError) as raised:
                client.search("Synthetic food")
            self.assertEqual(raised.exception.reason, "food_database_rate_limited")
            self.assertNotIn("Synthetic", str(raised.exception))
        self.assertEqual(opener.call_count, 1)
        clock.return_value = 61
        opener.side_effect = lambda request, timeout: response({"products": []})
        self.assertEqual(client.search("Synthetic food"), [])
