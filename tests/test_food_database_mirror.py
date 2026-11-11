"""The local food mirror stores external foods and is read before the network.

Each test uses a temporary SQLite file through the real DatabaseManager and the
current schema. The Open Food Facts client is a small fake; nothing touches the
network, a real data directory or an encryption key.
"""

from __future__ import annotations

import json
import threading
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

from support import temp_database

from backend.db import row_factory
from backend.db.repositories import NutritionProductRepository
from backend.errors import AppError
from backend.nutrition.food_database import FoodDatabaseService
from backend.nutrition.food_mirror import MAX_AGE, FoodDatabaseMirror

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
BARCODE = "4006381333931"


def food(barcode: str = BARCODE, name: str = "Haselnuss Riegel") -> dict:
    return {
        "id": f"off:{barcode}",
        "name": name,
        "brands": "Knoppers",
        "source": "Open Food Facts",
        "basis_amount": 100,
        "basis_unit": "g",
        "per_100": {
            "kcal": 540,
            "carbs_g": 50,
            "protein_g": 8,
            "fat_g": 33,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
    }


class FakeOff:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.offline = False

    def product(self, barcode: str) -> dict:
        self.calls.append(("product", barcode))
        if self.offline:
            raise AppError(502, "offline", reason="food_database_unavailable")
        return food(barcode)

    def search(self, query: str) -> list[dict]:
        self.calls.append(("search", query))
        if self.offline:
            raise AppError(502, "offline", reason="food_database_unavailable")
        return [food()]


class MirrorFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(
            self, "mirror.db", row_factory=row_factory, schema=True
        )
        self.now = START
        self.mirror = FoodDatabaseMirror(
            lambda: self.manager, threading.RLock(), lambda: self.now.isoformat()
        )
        self.off = FakeOff()
        self.service = FoodDatabaseService(cast(Any, self.off), self.mirror)


class FoodMirrorTests(MirrorFixture):
    def test_stored_food_is_found_by_id_and_by_name_or_brand_words(self):
        self.mirror.store(
            [
                food(),
                {**food("4000000000017", "Vanille Pudding"), "brands": "Milsani"},
            ]
        )

        self.assertEqual(self.mirror.get(f"off:{BARCODE}")["name"], "Haselnuss Riegel")
        self.assertEqual(len(self.mirror.search("knoppers")), 1)
        self.assertEqual(len(self.mirror.search("pudding vanille")), 1)
        self.assertEqual(len(self.mirror.search("")), 2)
        self.assertEqual(self.mirror.search("x"), [])
        self.assertEqual(self.mirror.search("schokolade"), [])

    def test_storing_again_refreshes_the_entry_instead_of_duplicating_it(self):
        self.mirror.store([food()])
        self.now += timedelta(days=100)
        self.mirror.store([food(name="Haselnuss Riegel neu")])

        self.assertEqual(len(self.mirror.search("")), 1)
        entry = self.mirror.get(f"off:{BARCODE}")
        self.assertEqual(entry["name"], "Haselnuss Riegel neu")
        self.assertTrue(self.mirror.is_fresh(entry))

    def test_entries_expire_after_ninety_days(self):
        self.mirror.store([food()])
        entry = self.mirror.get(f"off:{BARCODE}")

        self.now = START + MAX_AGE - timedelta(seconds=1)
        self.assertTrue(self.mirror.is_fresh(entry))
        self.now = START + MAX_AGE
        self.assertFalse(self.mirror.is_fresh(entry))

    def test_a_failing_write_never_breaks_the_lookup(self):
        self.mirror.store([{"id": "off:1", "name": None}])
        self.mirror.store([{"name": "ohne id"}])

        self.assertEqual(self.mirror.search(""), [])

    def test_delete_removes_the_entry_and_unknown_ids_are_not_found(self):
        self.mirror.store([food()])
        self.mirror.delete(f"off:{BARCODE}")

        self.assertIsNone(self.mirror.get(f"off:{BARCODE}"))
        with self.assertRaises(AppError) as raised:
            self.mirror.delete(f"off:{BARCODE}")
        self.assertEqual(raised.exception.reason, "food_not_found")

    def test_an_entry_reads_back_as_the_food_it_stored(self):
        stored = {
            **food(),
            "source_url": "https://example.test/product",
            "license": "ODbL",
            "origins": {"kcal": "label"},
        }
        self.mirror.store([stored])

        entry = self.mirror.get(f"off:{BARCODE}")
        self.assertEqual(entry.pop("fetched_at"), START.isoformat())
        self.assertEqual(entry, stored)

    def own_product(self, **values: Any) -> dict[str, Any]:
        product = {
            "id": "prod-own",
            "barcode": BARCODE,
            "name": "Mein Riegel",
            "brand": "",
            "basis_amount": 100,
            "basis_unit": "g",
            "source": "packaging_label",
            "source_url": "",
            "external_id": "",
            "provenance": {"kind": "packaging_label"},
            "status": "active",
            "created_at": START.isoformat(),
            "updated_at": START.isoformat(),
            **values,
        }
        with self.manager.unit_of_work() as db:
            return NutritionProductRepository().save(db, product)

    def filled_fields(self) -> dict[str, Any]:
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT details FROM nutrition_products WHERE id='prod-own'"
            ).fetchone()
        return json.loads(row["details"]).get("filled_fields", {})

    def test_an_own_products_ean_lists_no_entry_and_a_lookup_never_changes_it(self):
        self.own_product(kcal=500)

        self.mirror.store([food()])

        # The food stays stored for lookups by id, but is listed as the product.
        self.assertEqual(self.mirror.get(f"off:{BARCODE}")["per_100"]["carbs_g"], 50)
        self.assertEqual(self.mirror.search(""), [])
        with self.manager.reader() as db:
            product = NutritionProductRepository().get(db, "prod-own")
        self.assertEqual((product["kcal"], product["carbs_g"]), (500, None))
        self.assertEqual(self.filled_fields(), {})

    def test_a_new_own_product_takes_only_empty_fields_from_its_eans_foods(self):
        self.mirror.store([food()])
        self.own_product(kcal=520, fat_g=30, basis_amount=50)

        with self.manager.unit_of_work() as db:
            products = NutritionProductRepository()
            self.assertTrue(
                products.fill_from_database_entries(db, "prod-own", BARCODE)
            )
            saved = products.get(db, "prod-own")
        self.assertEqual(
            [saved[key] for key in ("brand", "kcal", "carbs_g", "protein_g", "fat_g")],
            ["Knoppers", 520, 25, 4, 30],
        )
        self.assertEqual(
            saved["filled_fields"],
            {
                key: {"origin": "open_food_facts", "fetched_at": START.isoformat()}
                for key in ("brand", "carbs_g", "protein_g")
            },
        )
        # Per-100-g values never fill a product counted per portion.
        self.own_product(basis_unit="portion", basis_amount=1, brand="Eigen")
        with self.manager.unit_of_work() as db:
            self.assertFalse(
                NutritionProductRepository().fill_from_database_entries(
                    db, "prod-own", BARCODE
                )
            )


class FoodDatabaseServiceMirrorTests(MirrorFixture):
    def test_legacy_barcode_entry_refreshes_once_and_falls_back_offline(self):
        legacy = food()
        for key in ("sugar_g", "fiber_g", "salt_g"):
            del legacy["per_100"][key]
        self.mirror.store([legacy])
        with patch("backend.nutrition.food_database.time.monotonic") as clock:
            clock.return_value = 10
            self.off.offline = True
            fallback = self.service.lookup({"barcode": BARCODE})["foods"][0]
            self.assertEqual(fallback["data_origin"], "local_database")
            self.assertEqual(fallback["stored_at"], START.isoformat())
            self.service.lookup({"barcode": BARCODE})
            self.assertEqual(len(self.off.calls), 1)
            self.off.offline = False
            clock.return_value += 901
            fresh = self.service.lookup({"barcode": BARCODE})["foods"][0]
            self.assertEqual(fresh["data_origin"], "live")
            self.assertIn("sugar_g", fresh["per_100"])
            self.service.lookup({"barcode": BARCODE})
        self.assertEqual(len(self.off.calls), 2)

    def test_barcode_lookup_stores_the_live_hit_and_then_reads_locally(self):
        first = self.service.lookup({"barcode": BARCODE})["foods"][0]
        second = self.service.lookup({"barcode": BARCODE})["foods"][0]

        self.assertEqual(first["data_origin"], "live")
        self.assertEqual(second["data_origin"], "local_database")
        self.assertEqual(second["stored_at"], START.isoformat())
        self.assertNotIn("fetched_at", second)
        self.assertEqual(self.off.calls, [("product", BARCODE)])

    def test_offline_lookup_falls_back_to_the_stale_entry_with_a_notice(self):
        self.service.lookup({"barcode": BARCODE})
        self.now += MAX_AGE + timedelta(days=1)
        self.off.offline = True

        result = self.service.lookup({"barcode": BARCODE})

        self.assertEqual(result["foods"][0]["data_origin"], "local_database_stale")
        self.assertIn("stored_at", result["foods"][0])
        self.assertIn("gespeicherte Stand", result["notice"])

    def test_expired_entry_is_refreshed_online_when_available(self):
        self.service.lookup({"barcode": BARCODE})
        self.now += MAX_AGE + timedelta(days=1)

        result = self.service.lookup({"barcode": BARCODE})

        self.assertEqual(result["foods"][0]["data_origin"], "live")
        self.assertEqual(len(self.off.calls), 2)
        self.assertTrue(self.mirror.is_fresh(self.mirror.get(f"off:{BARCODE}")))

    def test_unknown_food_offline_still_raises_the_provider_error(self):
        self.off.offline = True

        with self.assertRaises(AppError) as raised:
            self.service.lookup({"barcode": BARCODE})
        self.assertEqual(raised.exception.reason, "food_database_unavailable")

    def test_search_stores_hits_and_is_answered_locally_afterwards(self):
        live = self.service.lookup({"query": "knoppers", "source": "open_food_facts"})
        local = self.service.lookup({"query": "knoppers", "source": "open_food_facts"})

        self.assertEqual(live["foods"][0]["data_origin"], "live")
        self.assertEqual(local["foods"][0]["data_origin"], "local_database")
        self.assertEqual(self.off.calls, [("search", "knoppers")])

    def test_expired_search_hits_are_refreshed_online_when_available(self):
        search = {"query": "knoppers", "source": "open_food_facts"}
        self.service.lookup(search)
        self.now += MAX_AGE + timedelta(days=1)

        result = self.service.lookup(search)

        self.assertEqual(result["foods"][0]["data_origin"], "live")
        self.assertNotIn("gespeicherte Stand", result["notice"])
        self.assertEqual(
            self.off.calls, [("search", "knoppers"), ("search", "knoppers")]
        )
        stored = self.mirror.get(f"off:{BARCODE}")
        self.assertEqual(stored["fetched_at"], self.now.isoformat())

    def test_offline_search_falls_back_to_expired_hits_with_a_notice(self):
        search = {"query": "knoppers", "source": "open_food_facts"}
        self.service.lookup(search)
        self.now += MAX_AGE + timedelta(days=1)
        self.off.offline = True

        result = self.service.lookup(search)

        self.assertEqual(result["foods"][0]["data_origin"], "local_database_stale")
        self.assertEqual(result["foods"][0]["stored_at"], START.isoformat())
        self.assertIn("gespeicherte Stand", result["notice"])

    def test_resolve_uses_the_mirror_without_calling_online(self):
        self.mirror.store([food()])

        resolved = self.service.resolve(f"off:{BARCODE}")

        self.assertEqual(resolved["name"], "Haselnuss Riegel")
        self.assertNotIn("fetched_at", resolved)
        self.assertEqual(self.off.calls, [])

    def test_reference_database_is_unaffected_by_the_mirror(self):
        result = self.service.lookup({"query": "Haferflocken"})

        self.assertTrue(result["foods"])
        self.assertNotIn("data_origin", result["foods"][0])
        self.assertEqual(self.off.calls, [])

    def test_stored_foods_and_forget_back_the_database_section(self):
        self.mirror.store([food()])

        listed = self.service.stored_foods()
        self.assertEqual([item["id"] for item in listed], [f"off:{BARCODE}"])
        self.assertEqual(listed[0]["data_origin"], "local_database")

        self.service.forget(f"off:{BARCODE}")
        self.assertEqual(self.service.stored_foods(), [])

    def test_a_re_check_fills_gaps_and_keeps_known_values(self):
        stored = food()
        stored["per_100"]["fiber_g"] = 3.0
        self.mirror.store([stored])
        self.assertEqual(
            self.service.stored_foods()[0]["missing_fields"], ["sugar_g", "salt_g"]
        )
        fresh = food()
        fresh["per_100"]["salt_g"] = 0.4
        self.off.product = lambda barcode: fresh
        self.now += timedelta(days=1)

        refreshed = self.service.refresh_stored(f"off:{BARCODE}")

        self.assertEqual(
            (refreshed["per_100"]["fiber_g"], refreshed["per_100"]["salt_g"]),
            (3.0, 0.4),
        )
        self.assertEqual(refreshed["missing_fields"], ["sugar_g"])
        self.assertEqual(refreshed["stored_at"], self.now.isoformat())

    def test_a_re_check_never_guesses_a_basis_and_keeps_further_fields(self):
        stored = {**food(), "servings": [{"name": "Riegel", "amount": 40}]}
        stored["per_100"]["salt_g"] = 0.3
        self.mirror.store([stored])
        fresh = food()
        fresh["basis_unit"] = None
        self.off.product = lambda barcode: fresh
        self.now += timedelta(days=100)

        live = self.service.lookup({"barcode": BARCODE})["foods"][0]

        kept = self.mirror.get(f"off:{BARCODE}")
        self.assertIsNone(kept["basis_unit"])
        self.assertIsNone(kept["per_100"]["salt_g"])
        self.assertEqual(kept["servings"], stored["servings"])
        self.assertEqual(live["servings"], stored["servings"])

    def test_a_re_check_whose_write_fails_is_reported(self):
        self.mirror.store([food()])
        self.now += timedelta(days=1)

        with (
            patch.object(self.mirror, "refresh", return_value=[]),
            self.assertRaises(AppError) as raised,
        ):
            self.service.refresh_stored(f"off:{BARCODE}")
        self.assertEqual(raised.exception.reason, "food_database_unavailable")

    def test_a_failed_or_unknown_re_check_changes_nothing(self):
        self.mirror.store([food()])
        before = self.mirror.get(f"off:{BARCODE}")
        self.off.offline = True
        self.now += timedelta(days=1)

        with self.assertRaises(AppError):
            self.service.refresh_stored(f"off:{BARCODE}")
        self.assertEqual(self.mirror.get(f"off:{BARCODE}"), before)
        for food_id in ("off:4000000000017", None):
            with self.subTest(food_id=food_id), self.assertRaises(AppError) as raised:
                self.service.refresh_stored(food_id)
            self.assertEqual(raised.exception.reason, "food_not_found")
        self.assertEqual(self.off.calls, [("product", BARCODE)])

    def test_service_without_a_mirror_keeps_working_online_only(self):
        service = FoodDatabaseService(cast(Any, self.off))

        result = service.lookup({"barcode": BARCODE})

        self.assertEqual(result["foods"][0]["data_origin"], "live")
        self.assertEqual(service.stored_foods(), [])
        with self.assertRaises(AppError):
            service.forget(f"off:{BARCODE}")


if __name__ == "__main__":
    unittest.main()
