from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.nutrition import (
    NutritionGetRoutes,
    NutritionPostRoutes,
    NutritionPutRoutes,
)


class NutritionProductHttpContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.handler.headers = {"Content-Length": "100"}
        self.auth = Mock()
        self.diary = Mock()
        self.meal_library = Mock()
        self.queue = Mock()
        self.get_routes = NutritionGetRoutes(
            session_auth_service=lambda: self.auth,
            diary_service=lambda: self.diary,
            meal_library_service=lambda: self.meal_library,
            local_now=lambda: datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        )
        self.post_routes = NutritionPostRoutes(
            diary_service=lambda: self.diary,
            meal_library_service=lambda: self.meal_library,
            sync_job_queue=lambda: self.queue,
        )
        self.put_routes = NutritionPutRoutes(
            diary_service=lambda: self.diary,
            meal_library_service=lambda: self.meal_library,
        )

    def test_get_products_supports_local_query_and_barcode_lookup(self):
        self.handler.path = "/api/nutrition/products?q=Whey&barcode="
        self.meal_library.list_products.return_value = [
            {"id": "product-1", "name": "Whey"}
        ]

        self.assertTrue(self.get_routes.handle(self.handler, "/api/nutrition/products"))

        self.auth.require_auth.assert_called_once_with(self.handler)
        self.meal_library.list_products.assert_called_once_with(query="Whey")
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "products": [{"id": "product-1", "name": "Whey"}]},
        )

    def test_get_products_barcode_uses_local_first_lookup_contract(self):
        self.handler.path = "/api/nutrition/products?barcode=4006381333931"
        self.meal_library.lookup_product.return_value = {
            "ok": True,
            "source": "local",
            "foods": [{"id": "product-1"}],
        }

        self.assertTrue(self.get_routes.handle(self.handler, "/api/nutrition/products"))

        self.meal_library.lookup_product.assert_called_once_with(
            {"barcode": "4006381333931"}
        )
        self.handler.send_json.assert_called_once_with(
            200,
            {
                "ok": True,
                "source": "local",
                "foods": [{"id": "product-1"}],
            },
        )

    def test_save_product_is_explicit_and_does_not_accept_image_payload(self):
        payload = {
            "name": "Whey",
            "basis_amount": 100,
            "basis_unit": "g",
            "kcal": 376,
            "source": "packaging_label",
            "image": "must-not-persist",
            "confirmed": True,
        }
        self.handler.read_json.return_value = payload
        self.meal_library.save_product.return_value = {
            "id": "product-1",
            "name": "Whey",
        }

        self.assertTrue(
            self.post_routes.handle(self.handler, "/api/nutrition/products")
        )

        self.meal_library.save_product.assert_called_once_with(
            {key: value for key, value in payload.items() if key != "confirmed"}
        )
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "product": {"id": "product-1", "name": "Whey"}},
        )

    def test_unconfirmed_product_save_is_rejected_before_persistence(self):
        for confirmation_field in ({"confirmed": False}, {}):
            with self.subTest(confirmation_field=confirmation_field):
                self.handler.read_json.return_value = {
                    "name": "Whey",
                    "basis_amount": 100,
                    "basis_unit": "g",
                    "kcal": 376,
                    **confirmation_field,
                }
                with self.assertRaises(AppError) as raised:
                    self.post_routes.handle(self.handler, "/api/nutrition/products")
                self.assertEqual(raised.exception.reason, "confirmation_required")
                self.meal_library.save_product.assert_not_called()

    def test_update_and_archive_target_an_explicit_product_id(self):
        self.handler.read_json.return_value = {
            "id": "product-1",
            "protein_g": 80,
            "confirmed": True,
        }
        self.meal_library.update_product.return_value = {
            "id": "product-1",
            "protein_g": 80,
        }
        self.assertTrue(self.put_routes.handle(self.handler, "/api/nutrition/products"))
        self.meal_library.update_product.assert_called_once_with(
            "product-1", self.handler.read_json.return_value
        )
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "product": {"id": "product-1", "protein_g": 80}},
        )

        self.handler.reset_mock()
        self.handler.read_json.return_value = {"id": "product-1", "confirmed": True}
        self.meal_library.archive_product.return_value = {
            "id": "product-1",
            "status": "archived",
        }
        self.assertTrue(
            self.post_routes.handle(self.handler, "/api/nutrition/products/archive")
        )
        self.meal_library.archive_product.assert_called_once_with("product-1")
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "product": {"id": "product-1", "status": "archived"}},
        )


if __name__ == "__main__":
    unittest.main()
