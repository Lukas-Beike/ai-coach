from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import Mock

from support import dispatch_route

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
        self.diary = Mock()
        self.meal_library = Mock()
        self.get_routes = NutritionGetRoutes(
            diary_service=lambda: self.diary,
            meal_library_service=lambda: self.meal_library,
            local_now=lambda: datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        )
        self.post_routes = NutritionPostRoutes(
            diary_service=lambda: self.diary,
            meal_library_service=lambda: self.meal_library,
        )
        self.put_routes = NutritionPutRoutes(
            meal_library_service=lambda: self.meal_library,
        )

    def test_get_products_supports_local_query_and_barcode_lookup(self):
        self.handler.path = "/api/nutrition/products?q=Whey&barcode="
        self.meal_library.product_catalog.list_products.return_value = [
            {"id": "product-1", "name": "Whey"}
        ]

        self.assertTrue(
            dispatch_route(self.get_routes, self.handler, "/api/nutrition/products")
        )

        self.meal_library.product_catalog.list_products.assert_called_once_with(
            query="Whey", favorites_first=True
        )
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "products": [{"id": "product-1", "name": "Whey"}]},
        )

    def test_get_products_database_source_lists_the_local_mirror(self):
        self.handler.path = "/api/nutrition/products?source=database&q=Knoppers"
        self.meal_library.list_database_foods.return_value = [{"id": "off:1"}]

        self.assertTrue(
            dispatch_route(self.get_routes, self.handler, "/api/nutrition/products")
        )

        self.meal_library.list_database_foods.assert_called_once_with("Knoppers")
        self.meal_library.product_catalog.list_products.assert_not_called()
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "foods": [{"id": "off:1"}]}
        )

    def test_database_entry_removal_and_refresh_require_confirmation(self):
        for action, method in (
            ("delete", self.meal_library.forget_database_food),
            ("refresh", self.meal_library.refresh_database_food),
        ):
            with self.subTest(action=action):
                path = f"/api/nutrition/products/database/{action}"
                self.handler.read_json.return_value = {"id": "off:1"}
                with self.assertRaises(AppError) as raised:
                    dispatch_route(self.post_routes, self.handler, path, method="POST")
                self.assertEqual(raised.exception.reason, "confirmation_required")
                method.assert_not_called()

                self.handler.read_json.return_value = {"id": "off:1", "confirmed": True}
                method.return_value = {"ok": True}
                dispatch_route(self.post_routes, self.handler, path, method="POST")
                method.assert_called_once_with("off:1")

    def test_get_products_barcode_uses_local_first_lookup_contract(self):
        self.handler.path = "/api/nutrition/products?barcode=4006381333931"
        self.meal_library.product_catalog.lookup_product.return_value = {
            "ok": True,
            "source": "local",
            "foods": [{"id": "product-1"}],
        }

        self.assertTrue(
            dispatch_route(self.get_routes, self.handler, "/api/nutrition/products")
        )

        self.meal_library.product_catalog.lookup_product.assert_called_once_with(
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
        self.meal_library.product_catalog.save_product.return_value = {
            "id": "product-1",
            "name": "Whey",
        }

        self.assertTrue(
            dispatch_route(
                self.post_routes, self.handler, "/api/nutrition/products", method="POST"
            )
        )

        self.meal_library.product_catalog.save_product.assert_called_once_with(
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
                    dispatch_route(
                        self.post_routes,
                        self.handler,
                        "/api/nutrition/products",
                        method="POST",
                    )
                self.assertEqual(raised.exception.reason, "confirmation_required")
                self.meal_library.product_catalog.save_product.assert_not_called()

    def test_update_and_archive_target_an_explicit_product_id(self):
        self.handler.read_json.return_value = {
            "id": "product-1",
            "protein_g": 80,
            "confirmed": True,
        }
        self.meal_library.product_catalog.update_product.return_value = {
            "id": "product-1",
            "protein_g": 80,
        }
        self.assertTrue(
            dispatch_route(
                self.put_routes, self.handler, "/api/nutrition/products", method="PUT"
            )
        )
        self.meal_library.product_catalog.update_product.assert_called_once_with(
            "product-1", self.handler.read_json.return_value
        )
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "product": {"id": "product-1", "protein_g": 80}},
        )

        self.handler.reset_mock()
        self.handler.read_json.return_value = {"id": "product-1", "confirmed": True}
        self.meal_library.product_catalog.archive_product.return_value = {
            "id": "product-1",
            "status": "archived",
        }
        self.assertTrue(
            dispatch_route(
                self.post_routes,
                self.handler,
                "/api/nutrition/products/archive",
                method="POST",
            )
        )
        self.meal_library.product_catalog.archive_product.assert_called_once_with(
            "product-1"
        )
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "product": {"id": "product-1", "status": "archived"}},
        )

    def test_favorite_and_add_to_meal_target_explicit_ids(self):
        self.handler.read_json.return_value = {"id": "product-1", "favorite": True}
        self.meal_library.product_catalog.set_favorite.return_value = {
            "id": "product-1",
            "favorite": 1,
        }
        self.assertTrue(
            dispatch_route(
                self.post_routes,
                self.handler,
                "/api/nutrition/products/favorite",
                method="POST",
            )
        )
        self.meal_library.product_catalog.set_favorite.assert_called_once_with(
            "product-1", True
        )
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "product": {"id": "product-1", "favorite": 1}}
        )

        self.handler.reset_mock()
        self.handler.read_json.return_value = {
            "id": "entry-1",
            "product_id": "product-1",
            "amount": 50,
            "unit": "g",
        }
        self.diary.add_product_to_meal.return_value = {"id": "entry-1"}
        self.assertTrue(
            dispatch_route(
                self.post_routes,
                self.handler,
                "/api/nutrition/entry/add-product",
                method="POST",
            )
        )
        self.diary.add_product_to_meal.assert_called_once_with(
            "entry-1", "product-1", 50, "g"
        )
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "entry": {"id": "entry-1"}}
        )


if __name__ == "__main__":
    unittest.main()
