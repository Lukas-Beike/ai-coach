from __future__ import annotations

import base64
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from nutrition_service_support import build_nutrition_services
from support import temp_database

from backend import change_history
from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db.repositories import FoodDatabaseEntryRepository
from backend.errors import AppError
from backend.nutrition.photo import (
    NutritionPhotoExtractionService,
    validate_packaging_extraction,
)


class NutritionProductContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = temp_database(
            self,
            path=Path(self.temporary.name) / "nutrition-products.db",
            row_factory=sqlite3.Row,
            schema=True,
        )
        self.lock = threading.Lock()
        self.off = Mock()
        self.food_database = Mock()
        self.food_database.lookup.return_value = {
            "ok": True,
            "foods": [
                {
                    "id": "off:4006381333999",
                    "name": "Synthetic cocoa powder",
                    "basis_unit": "g",
                    "per_100": {
                        "kcal": 250,
                        "protein_g": 20,
                        "fat_g": 5,
                        "carbs_g": 30,
                    },
                    "origins": {},
                }
            ],
            "source": "open_food_facts",
        }
        self.service = self.build_service()

    def build_service(self, photo_extractor=None):
        self.diary, self.library = build_nutrition_services(
            self.manager,
            self.lock,
            lambda: "2026-10-05T12:00:00+00:00",
            lambda: datetime(2026, 10, 5, 14, 0, tzinfo=UTC),
            food_database=self.food_database,
            photo_extractor=photo_extractor,
        )
        return self.library

    @staticmethod
    def product_payload(**changes):
        return {
            "barcode": "4006381333931",
            "name": "RheinNatur Bio Whey Protein Cocoa",
            "brand": "RheinNatur",
            "basis_amount": 100,
            "basis_unit": "g",
            "kcal": 376,
            "carbs_g": 8.0,
            "protein_g": 78.0,
            "fat_g": 5.5,
            "sugar_g": 4.0,
            "fiber_g": 2.0,
            "salt_g": 0.4,
            "source": "packaging_label",
            "source_url": "",
            "external_id": "",
            **changes,
        }

    def test_a_new_product_fills_its_gaps_from_stored_foods_of_its_ean(self):
        stored = {
            "id": "off:4006381333931",
            "name": "Synthetic whey",
            "brands": "",
            "basis_amount": 100,
            "basis_unit": "g",
            "per_100": {"kcal": 380, "salt_g": 0.5},
        }
        with self.manager.unit_of_work() as db:
            FoodDatabaseEntryRepository().upsert(db, stored, "2026-10-01")

        saved = self.library.product_catalog.save_product(
            self.product_payload(id="off:4006381333931", salt_g=None)
        )

        # A new product never takes a stored food's id, and only its gaps fill.
        self.assertNotEqual(saved["id"], "off:4006381333931")
        self.assertEqual((saved["kcal"], saved["salt_g"]), (376, 0.5))
        self.assertEqual(
            saved["filled_fields"],
            {"salt_g": {"origin": "open_food_facts", "fetched_at": "2026-10-01"}},
        )
        reread = self.library.product_catalog.get_product(saved["id"])
        self.assertEqual(reread["salt_g"], 0.5)
        # An edit that empties a filled field keeps it empty and drops its origin.
        cleared = self.library.product_catalog.update_product(
            saved["id"], {"salt_g": None}
        )
        self.assertEqual((cleared["salt_g"], cleared["filled_fields"]), (None, {}))

    def test_incomplete_products_are_listed_and_only_their_empty_fields_filled(self):
        catalog = self.library.product_catalog
        own = catalog.save_product(
            self.product_payload(barcode="4006381333931", fat_g=None, salt_g=None)
        )
        complete = catalog.save_product(
            self.product_payload(barcode="4006381333948", name="Complete")
        )
        stored = {
            "id": "yazio:0a1b2c3d-0000-4000-8000-000000000001",
            "name": "Synthetic oat drink",
            "brands": "Synthetic",
            "basis_amount": 100,
            "basis_unit": "ml",
            "per_100": {"kcal": 45, "carbs_g": 6.5, "protein_g": 1, "fat_g": 1.5},
        }
        twin = {**stored, "id": "off:4006381333931", "name": "Twin of the own EAN"}
        with self.manager.unit_of_work() as db:
            FoodDatabaseEntryRepository().upsert(db, stored, "2026-10-01")
            FoodDatabaseEntryRepository().upsert(db, twin, "2026-10-01")

        listed = catalog.list_incomplete_products()
        by_id = {item["id"]: item for item in listed}
        # The complete product and the food of the own product's EAN are absent.
        self.assertEqual(set(by_id), {own["id"], stored["id"]})
        self.assertEqual(by_id[own["id"]]["origin"], "own")
        self.assertEqual(by_id[own["id"]]["missing_fields"], ["fat_g", "salt_g"])
        self.assertEqual(by_id[own["id"]]["barcode"], "4006381333931")
        self.assertEqual(by_id[stored["id"]]["origin"], "yazio")
        self.assertEqual(
            by_id[stored["id"]]["missing_fields"], ["sugar_g", "fiber_g", "salt_g"]
        )
        self.assertEqual(by_id[stored["id"]]["basis_unit"], "ml")

        result = catalog.fill_product_gaps(
            [
                {
                    "id": own["id"],
                    # Known protein stays; fat and salt are empty.
                    "values": {"fat_g": 5.5, "salt_g": 0.4, "protein_g": 1},
                    "origin": "web",
                    "source_url": "https://example.test/whey",
                },
                {"id": stored["id"], "values": {"salt_g": 0.1}, "origin": "bls"},
                {"id": complete["id"], "values": {"kcal": 1}, "origin": "yazio"},
            ]
        )

        self.assertEqual(
            [item["id"] for item in result["changes"]], [own["id"], stored["id"]]
        )
        page = {"origin": "web", "source_url": "https://example.test/whey"}
        self.assertEqual(
            result["changes"][0]["written"],
            [
                {"field": "fat_g", "value": 5.5, **page},
                {"field": "salt_g", "value": 0.4, **page},
            ],
        )
        self.assertEqual(result["changes"][0]["skipped"], ["protein_g"])
        self.assertEqual(result["unchanged"][0]["skipped"], ["kcal"])
        filled = catalog.get_product(own["id"])
        self.assertEqual((filled["fat_g"], filled["protein_g"]), (5.5, 78.0))
        self.assertEqual(
            filled["filled_fields"]["salt_g"],
            {**page, "fetched_at": "2026-10-05T12:00:00+00:00"},
        )
        with self.manager.reader() as db:
            food = FoodDatabaseEntryRepository().get(db, stored["id"])
        self.assertEqual(food["per_100"]["salt_g"], 0.1)
        self.assertEqual(food["filled_fields"]["salt_g"]["origin"], "bls")
        self.assertEqual(food["fetched_at"], "2026-10-01")
        self.assertEqual(
            [item["id"] for item in catalog.list_incomplete_products()], [stored["id"]]
        )
        # A second call finds nothing left to write.
        again = catalog.fill_product_gaps(
            [{"id": own["id"], "values": {"salt_g": 9}, "origin": "bls"}]
        )
        self.assertEqual(
            (again["ok"], again["status"], again["changes"]),
            (False, "unchanged", []),
        )
        self.assertEqual(again["unchanged"][0]["skipped"], ["salt_g"])
        self.assertEqual(catalog.get_product(own["id"])["salt_g"], 0.4)
        # Values from different web pages each name their own page.
        stored_fill = catalog.fill_product_gaps(
            [
                {
                    "id": stored["id"],
                    "values": {"sugar_g": 4, "fiber_g": 0.8},
                    "origin": "web",
                    "source_url": "https://example.test/a",
                    "source_urls": {"fiber_g": "https://example.test/b"},
                }
            ]
        )
        self.assertEqual(
            {
                item["field"]: item["source_url"]
                for item in stored_fill["changes"][0]["written"]
            },
            {"sugar_g": "https://example.test/a", "fiber_g": "https://example.test/b"},
        )

    def store_foods(self, *foods):
        with self.manager.unit_of_work() as db:
            for food in foods:
                FoodDatabaseEntryRepository().upsert(db, food, "2026-10-01")

    @staticmethod
    def stored_food(food_id, name, brands="", **per_100):
        return {
            "id": food_id,
            "name": name,
            "brands": brands,
            "basis_amount": 100,
            "basis_unit": "g",
            "per_100": {"kcal": 50, "carbs_g": 10, **per_100},
        }

    def test_the_merged_list_holds_own_products_and_stored_foods_by_name(self):
        catalog = self.library.product_catalog
        own = catalog.save_product(
            self.product_payload(name="Zebra Riegel", brand="Streifen")
        )
        archived = catalog.save_product(
            self.product_payload(name="Archiv", barcode="4006381333948")
        )
        catalog.archive_product(archived["id"])
        self.store_foods(
            self.stored_food("off:4000000000017", "apfelmus", "Hersteller"),
            {
                **self.stored_food(
                    "yazio:0a1b2c3d-0000-4000-8000-000000000001", "Banane"
                ),
                "barcode": "4000000000024",
            },
            # The food of the own product's EAN is listed as that product only.
            self.stored_food(f"off:{own['barcode']}", "Aaa Zwilling"),
            # An umlaut sorts with its vowel, not after Z.
            self.stored_food("off:4000000000031", "Äpfel getrocknet"),
        )

        listed = catalog.list_all_products()

        self.assertEqual(
            [item["name"] for item in listed],
            ["Äpfel getrocknet", "apfelmus", "Banane", "Zebra Riegel"],
        )
        by_name = {item["name"]: item for item in listed}
        self.assertEqual(
            [(item["origin"], item["favorite"]) for item in listed],
            [("open_food_facts", 0), ("open_food_facts", 0), ("yazio", 0), ("own", 0)],
        )
        self.assertEqual(by_name["apfelmus"]["fetched_at"], "2026-10-01")
        self.assertIsNone(by_name["Zebra Riegel"]["fetched_at"])
        self.assertEqual(
            by_name["apfelmus"]["missing_fields"],
            ["protein_g", "fat_g", "sugar_g", "fiber_g", "salt_g"],
        )
        self.assertEqual(by_name["Zebra Riegel"]["missing_fields"], [])
        self.assertEqual(by_name["apfelmus"]["filled_fields"], {})
        for query, expected in (
            ("riegel", ["Zebra Riegel"]),
            ("streifen", ["Zebra Riegel"]),
            ("HERSTELLER apfel", ["apfelmus"]),
            ("4000000000024", ["Banane"]),
            (own["barcode"], ["Zebra Riegel"]),
            ("Bananen", ["Banane"]),
            ("Archiv", []),
            ("  ", []),
            ("nichts", []),
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    [item["name"] for item in catalog.list_all_products(query)],
                    expected,
                )
        # The default own-product list is unchanged: no stored food, no EAN search.
        self.assertEqual([p["name"] for p in catalog.list_products()], ["Zebra Riegel"])
        self.assertEqual(catalog.list_products(query=own["barcode"]), [])

    def test_editing_a_stored_database_food_marks_its_values_as_the_athletes_own(self):
        catalog = self.library.product_catalog
        food_id = "off:4000000000017"
        self.store_foods(self.stored_food(food_id, "Apfelmus", "Hersteller"))
        edit = {
            "kcal": 52,
            "salt_g": 0.1,
            "carbs_g": 10,
            "name": "Anders",
            "barcode": "1",
        }

        with change_history.collect_changes() as changes:
            edited = catalog.update_product(food_id, edit)

        # It stays the database entry; only the nutrient values change.
        self.assertEqual(
            [edited[key] for key in ("origin", "name", "barcode", "kcal", "salt_g")],
            ["open_food_facts", "Apfelmus", "4000000000017", 52, 0.1],
        )
        manual = {"origin": "manual", "fetched_at": "2026-10-05T12:00:00+00:00"}
        self.assertEqual(edited["filled_fields"], {"kcal": manual, "salt_g": manual})
        self.assertEqual(edited["fetched_at"], "2026-10-01")
        self.assertEqual(
            [(c["action"], c["entity_type"]) for c in changes],
            [("update", "food_database_entry")],
        )
        # An unchanged payload records nothing; an emptied value loses its mark.
        with change_history.collect_changes() as again:
            catalog.update_product(food_id, edit)
        self.assertEqual(again, [])
        cleared = catalog.update_product(food_id, {"salt_g": None})
        self.assertEqual(
            (cleared["salt_g"], list(cleared["filled_fields"])), (None, ["kcal"])
        )

    def test_invalid_edits_of_a_stored_database_food_change_nothing(self):
        catalog = self.library.product_catalog
        food_id = "off:4000000000017"
        self.store_foods(self.stored_food(food_id, "Apfelmus"))
        before = catalog.get_product(food_id)
        for label, payload in (
            ("negative", {"kcal": -1}),
            ("text", {"kcal": "1"}),
            ("too large", {"salt_g": 1000.5}),
            ("boolean", {"fat_g": True}),
            ("one bad value rejects all", {"kcal": 60, "salt_g": -2}),
        ):
            with self.subTest(label), self.assertRaises(AppError) as raised:
                catalog.update_product(food_id, payload)
            self.assertEqual(raised.exception.status, 400)
        self.assertEqual(catalog.get_product(food_id), before)

    def test_invalid_gap_fills_are_rejected_without_a_write(self):
        catalog = self.library.product_catalog
        own = catalog.save_product(self.product_payload(fat_g=None, salt_g=None))
        base = {"id": own["id"], "values": {"fat_g": 5}, "origin": "bls"}
        for label, item, reason in (
            ("unknown id", {**base, "id": "missing"}, "Produkt nicht gefunden."),
            ("non-core field", {**base, "values": {"name": 5}}, "name"),
            ("negative", {**base, "values": {"fat_g": -1}}, "fat_g"),
            ("too large", {**base, "values": {"fat_g": 1000.5}}, "fat_g"),
            ("energy", {**base, "values": {"kcal": 9001}}, "kcal"),
            ("not finite", {**base, "values": {"fat_g": float("nan")}}, "fat_g"),
            ("text", {**base, "values": {"fat_g": "5"}}, "fat_g"),
            ("boolean", {**base, "values": {"fat_g": True}}, "fat_g"),
            ("empty", {**base, "values": {}}, "values"),
            ("origin", {**base, "origin": "guess"}, "origin"),
            ("web without page", {**base, "origin": "web"}, "source_url"),
            (
                "web with other scheme",
                {**base, "origin": "web", "source_url": "file:///x"},
                "source_url",
            ),
            (
                "one bad field rejects the item",
                {**base, "values": {"fat_g": 5, "salt_g": -2}},
                "salt_g",
            ),
            ("not an object", "fat_g", "Objekt"),
        ):
            with self.subTest(label):
                result = catalog.fill_product_gaps([item])
                self.assertEqual(result["changes"], [])
                self.assertIn(reason, result["unchanged"][0]["rejected"])
        stored = catalog.get_product(own["id"])
        self.assertEqual((stored["fat_g"], stored["salt_g"]), (None, None))
        for items in ([], "x", [base] * 26):
            with self.subTest(items=items), self.assertRaises(AppError):
                catalog.fill_product_gaps(items)
        # An archived product is no longer the athlete's, so it is not filled.
        catalog.archive_product(own["id"])
        self.assertEqual(
            catalog.fill_product_gaps([base])["unchanged"][0]["rejected"],
            "Produkt nicht gefunden.",
        )

    def test_confirmed_product_is_persistent_and_can_be_archived(self):
        saved = self.library.product_catalog.save_product(self.product_payload())

        self.assertTrue(saved["id"])
        self.assertEqual(saved["barcode"], "4006381333931")
        self.assertEqual(saved["source"], "packaging_label")
        self.assertEqual(saved["status"], "active")
        self.assertEqual(
            self.library.product_catalog.get_product(saved["id"])["name"], saved["name"]
        )
        self.assertEqual(
            self.library.product_catalog.list_products(barcode="4006381333931")[0][
                "id"
            ],
            saved["id"],
        )

        updated = self.library.product_catalog.update_product(
            saved["id"], {"protein_g": 80.0}
        )
        self.assertEqual(updated["protein_g"], 80.0)
        self.assertEqual(
            self.library.product_catalog.get_product(saved["id"])["protein_g"], 80.0
        )

        archived = self.library.product_catalog.archive_product(saved["id"])
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(
            self.library.product_catalog.list_products(barcode="4006381333931"), []
        )
        self.assertEqual(
            self.library.product_catalog.list_products(
                barcode="4006381333931", include_archived=True
            )[0]["status"],
            "archived",
        )

    def test_product_edit_keeps_extraction_confidence(self):
        saved = self.library.product_catalog.save_product(
            self.product_payload(confidence=0.8)
        )
        self.assertEqual(saved["extraction_confidence"], 0.8)

        updated = self.library.product_catalog.update_product(
            saved["id"], {"protein_g": 80.0}
        )

        self.assertEqual(updated["extraction_confidence"], 0.8)
        self.assertEqual(
            self.library.product_catalog.get_product(saved["id"])[
                "extraction_confidence"
            ],
            0.8,
        )

    def test_product_amount_accepts_a_comma_decimal(self):
        saved = self.library.product_catalog.save_product(self.product_payload())

        result = self.library.product_catalog.calculate_product(
            saved["id"], "12,5", "g"
        )

        self.assertEqual(result["amount"], 12.5)
        with self.assertRaises(AppError):
            self.library.product_catalog.calculate_product(saved["id"], "1,200", "g")

    def test_product_for_a_past_day_has_no_invented_time(self):
        saved = self.library.product_catalog.save_product(self.product_payload())

        entry = self.diary.log_product(saved["id"], 50, "g", meal_date="2026-10-01")

        self.assertIs(entry["logged_time_known"], False)
        self.assertEqual(entry["meal_type"], "snack")
        self.assertEqual(entry["logged_at"], "2026-10-01T12:00:00")

    def test_barcode_lookup_prefers_local_product_and_never_calls_remote(self):
        saved = self.library.product_catalog.save_product(self.product_payload())

        result = self.library.product_catalog.lookup_product(
            {"barcode": "4006381333931"}
        )

        self.assertEqual(result["source"], "local")
        self.assertEqual(result["foods"][0]["id"], saved["id"])
        self.food_database.lookup.assert_not_called()

    def test_precise_label_values_survive_save_and_consumption_snapshot(self):
        saved = self.library.product_catalog.save_product(
            self.product_payload(sugar_g=4.1234, fiber_g=0.05, salt_g=0.03)
        )
        reloaded = self.library.product_catalog.get_product(saved["id"])
        self.assertEqual(reloaded["sugar_g"], 4.1234)
        self.assertEqual(reloaded["fiber_g"], 0.05)
        self.assertEqual(reloaded["salt_g"], 0.03)
        entry = self.diary.log_product(saved["id"], 100, "g")
        self.assertEqual(entry["nutrition_basis"]["product"]["salt_g"], 0.03)

    def test_text_lookup_matches_saved_product_by_words_in_any_order(self):
        saved = self.library.product_catalog.save_product(self.product_payload())

        result = self.library.product_catalog.lookup_product(
            {"query": "rheinnatur cocoa whey"}
        )

        self.assertEqual(result["source"], "local")
        self.assertEqual(result["foods"][0]["id"], saved["id"])
        self.assertEqual(
            self.library.product_catalog.list_products(query="Whey Vanilla"), []
        )
        self.food_database.lookup.assert_not_called()

    def test_text_search_treats_wildcards_literally_and_blank_queries_match_nothing(
        self,
    ):
        self.library.product_catalog.save_product(self.product_payload())

        for query in ("   ", "%", "_", "whey %"):
            with self.subTest(query=query):
                self.assertEqual(
                    self.library.product_catalog.list_products(query=query), []
                )

    def test_short_search_words_must_start_a_word(self):
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Reisnudeln mit Brokkoli")
        )
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Bio Eier")
        )
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Hof-Eier")
        )

        names = {
            p["name"] for p in self.library.product_catalog.list_products(query="Ei")
        }

        self.assertEqual(names, {"Bio Eier", "Hof-Eier"})
        self.assertEqual(
            self.library.product_catalog.list_products(query="Ei Brokkoli"), []
        )
        self.assertEqual(
            len(self.library.product_catalog.list_products(query="nudeln brokkoli")), 1
        )

    def test_search_tolerates_plurals_umlauts_and_typos_but_needs_every_word(self):
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Champignon braun", brand=None)
        )
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Hüttenkäse", brand="Milsani")
        )
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Zucchini", brand=None)
        )

        for query, name in (
            ("Champignons braun", "Champignon braun"),
            ("HÜTTENKÄSE", "Hüttenkäse"),
            ("Huettenkase milsani", "Hüttenkäse"),
            ("zuccini", "Zucchini"),
        ):
            with self.subTest(query=query):
                result = self.library.product_catalog.lookup_product({"query": query})
                self.assertEqual(result["source"], "local")
                self.assertEqual([p["name"] for p in result["foods"]], [name])
        self.food_database.lookup.assert_not_called()
        # A word the product lacks leaves the search to the food database.
        self.assertEqual(
            self.library.product_catalog.list_products(query="Champignons roh"), []
        )
        # Letters across a word boundary are no word: "Glutenfrei Salzstangen"
        # and "Erdbeer" by "Eisberg" do not contain "Reis".
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Glutenfrei Salzstangen")
        )
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Erdbeer", brand="Eisberg")
        )
        self.assertEqual(self.library.product_catalog.list_products(query="Reis"), [])

    def test_search_ignores_separators_around_words(self):
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Haferflocken Banane", brand=None)
        )
        self.library.product_catalog.save_product(
            self.product_payload(barcode=None, name="Müsli", brand="Bio")
        )

        for query, name in (
            ("Haferflocken, Banane", "Haferflocken Banane"),
            ("Müsli (Bio)", "Müsli"),
            ("Banane!", "Haferflocken Banane"),
        ):
            with self.subTest(query=query):
                names = [
                    p["name"]
                    for p in self.library.product_catalog.list_products(query=query)
                ]
                self.assertEqual(names, [name])
        self.assertEqual(self.library.product_catalog.list_products(query="( - )"), [])

    def test_unknown_barcode_falls_back_to_food_database_and_labels_source(self):
        result = self.library.product_catalog.lookup_product(
            {"barcode": "4006381333999"}
        )

        self.assertEqual(result["source"], "open_food_facts")
        self.assertEqual(result["foods"][0]["id"], "off:4006381333999")
        self.food_database.lookup.assert_called_once_with({"barcode": "4006381333999"})

    def test_packaging_extraction_returns_candidate_only_until_confirmation(self):
        candidate = validate_packaging_extraction(
            {
                "name": "RheinNatur Whey",
                "brand": "RheinNatur",
                "barcode": "4006381333931",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 376,
                "carbs_g": 8,
                "protein_g": 78,
                "fat_g": 5.5,
                "confidence": 0.96,
                "image": "must-not-be-accepted-or-persisted",
            }
        )

        self.assertTrue(candidate["ok"])
        self.assertTrue(candidate["requires_confirmation"])
        self.assertEqual(candidate["provenance"], "packaging_label")
        self.assertNotIn("image", candidate["candidate"])
        self.assertEqual(self.library.product_catalog.list_products(), [])

    def test_packaging_extraction_rejects_invalid_or_estimated_values(self):
        for payload in (
            {"name": "", "basis_amount": 100, "basis_unit": "g", "kcal": 100},
            {"name": "Product", "basis_amount": 0, "basis_unit": "g", "kcal": 100},
            {
                "name": "Product",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": "not-a-number",
            },
        ):
            with self.subTest(payload=payload), self.assertRaises(AppError):
                validate_packaging_extraction(payload)
        with self.assertRaises(AppError):
            self.library.product_catalog.save_product(
                self.product_payload(source="coach")
            )

    def test_product_nutrients_are_snapshotted_when_consumed(self):
        saved = self.library.product_catalog.save_product(self.product_payload())
        entry = self.diary.log_product(saved["id"], 50, "g")
        self.assertEqual(entry["kcal"], 188)
        self.assertEqual(entry["protein_g"], 39)
        self.assertEqual(entry["nutrition_basis"]["kind"], "local_product")

        self.library.product_catalog.update_product(
            saved["id"], {"kcal": 400, "protein_g": 82}
        )

        fetched = self.diary.get_meal(entry["id"])
        self.assertEqual(fetched["kcal"], 188)
        self.assertEqual(fetched["protein_g"], 39)
        self.assertEqual(fetched["nutrition_basis"]["product"]["kcal"], 376)

    def test_product_calculation_preserves_unknown_nutrients_and_does_not_convert_units(
        self,
    ):
        saved = self.library.product_catalog.save_product(
            self.product_payload(basis_unit="ml", carbs_g=None, protein_g=None)
        )

        result = self.library.product_catalog.calculate_product(saved["id"], 250, "ml")

        self.assertEqual(result["kcal"], 940)
        self.assertIsNone(result["carbs_g"])
        self.assertIsNone(result["protein_g"])
        with self.assertRaises(AppError):
            self.library.product_catalog.calculate_product(saved["id"], 250, "g")

    def test_photo_candidate_is_not_saved_until_explicit_save(self):
        response = {
            "output_text": '{"name":"Synthetic cocoa mix","basis_amount":100,"basis_unit":"g","kcal":376,"protein_g":78}'
        }
        extractor = NutritionPhotoExtractionService(
            selected_model=lambda: "gpt-6-luna",
            openai_request=lambda _path, _payload: response,
        )
        self.service = self.build_service(photo_extractor=extractor)
        data_url = "data:image/jpeg;base64," + base64.b64encode(
            b"\xff\xd8\xffsynthetic-image"
        ).decode("ascii")

        candidate = self.library.extract_packaging_photo({"image_data_url": data_url})

        self.assertTrue(candidate["requires_confirmation"])
        self.assertEqual(candidate["provenance"], "packaging_label")
        self.assertNotIn("image_data_url", candidate)
        self.assertEqual(self.library.product_catalog.list_products(), [])
        self.assertTrue(
            self.library.product_catalog.save_product(
                {**candidate["candidate"], "confirmed": True}
            )["id"]
        )

    def test_database_backup_contains_confirmed_products(self):
        self.library.product_catalog.save_product(self.product_payload())
        config = DatabaseBackupConfig(
            database_path=self.manager.path,
            data_dir=Path(self.temporary.name),
            maximum_bytes=1_000_000,
            minimum_free_bytes=1,
            time_limit_seconds=10,
            monotonic=lambda: 0.0,
            disk_usage=lambda _path: SimpleNamespace(free=2_000_000),
        )

        backup = DatabaseBackupService(
            self.manager, self.lock, config, Mock()
        ).read_bytes()
        backup_path = Path(self.temporary.name) / "nutrition-products-backup.db"
        backup_path.write_bytes(backup)
        try:
            snapshot = sqlite3.connect(backup_path)
            try:
                row = snapshot.execute(
                    "SELECT barcode, name, source FROM nutrition_products"
                ).fetchone()
                self.assertEqual(
                    row,
                    (
                        "4006381333931",
                        "RheinNatur Bio Whey Protein Cocoa",
                        "packaging_label",
                    ),
                )
            finally:
                snapshot.close()
        finally:
            backup_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
