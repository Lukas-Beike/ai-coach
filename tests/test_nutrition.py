from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from nutrition_service_support import build_nutrition_services

from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition import (
    meal_type_from_hour,
    normalize_nutrition_entry,
    validate_iso_date,
)


class NutritionModelTests(unittest.TestCase):
    def test_meal_type_from_hour(self) -> None:
        self.assertEqual(meal_type_from_hour(7), "breakfast")
        self.assertEqual(meal_type_from_hour(12), "lunch")
        self.assertEqual(meal_type_from_hour(15), "snack")
        self.assertEqual(meal_type_from_hour(19), "dinner")
        self.assertEqual(meal_type_from_hour(23), "snack")

    def test_validate_iso_date(self) -> None:
        self.assertEqual(validate_iso_date("2026-09-24"), "2026-09-24")
        with self.assertRaises(AppError):
            validate_iso_date("invalid-date")
        with self.assertRaises(AppError):
            validate_iso_date("2026-02-30")

    def test_normalize_valid_entry(self) -> None:
        fixed_dt = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
        payload = {
            "description": "  Haferflocken mit Beeren  ",
            "kcal": 450,
            "carbs_g": 65.5,
            "protein_g": 15.0,
            "fat_g": 8.2,
            "meal_type": "breakfast",
            "meal_date": "2026-09-24",
            "source": "photo",
        }
        entry = normalize_nutrition_entry(payload, local_now_factory=lambda: fixed_dt)
        self.assertEqual(entry["description"], "Haferflocken mit Beeren")
        self.assertEqual(entry["kcal"], 450)
        self.assertEqual(entry["carbs_g"], 65.5)
        self.assertEqual(entry["protein_g"], 15.0)
        self.assertEqual(entry["fat_g"], 8.2)
        self.assertEqual(entry["meal_type"], "breakfast")
        self.assertEqual(entry["meal_date"], "2026-09-24")
        self.assertEqual(entry["source"], "photo")

    def test_meal_time_overrides_service_clock_default(self) -> None:
        entry = normalize_nutrition_entry(
            {
                "meal_date": "2026-09-24",
                "meal_time": "07:15",
                "description": "Oats",
                "kcal": 350,
            },
            local_now_factory=lambda: datetime(2026, 9, 24, 18, 30, tzinfo=UTC),
        )
        self.assertEqual(entry["logged_at"], "2026-09-24T07:15")
        self.assertEqual(entry["meal_type"], "breakfast")

    def test_normalize_defaults_and_clamps(self) -> None:
        fixed_dt = datetime(2026, 9, 24, 13, 15, tzinfo=UTC)
        payload = {
            "description": "x" * 600,
            "kcal": 99999,
            "carbs_g": 5000.0,
            "protein_g": -10,
        }
        entry = normalize_nutrition_entry(
            payload, local_now_factory=lambda: fixed_dt, clamp_out_of_bounds=True
        )
        self.assertEqual(len(entry["description"]), 500)
        self.assertEqual(entry["kcal"], 10000)
        self.assertEqual(entry["carbs_g"], 1000.0)
        self.assertEqual(entry["protein_g"], 0.0)
        self.assertIsNone(entry["fat_g"])
        self.assertEqual(entry["meal_type"], "lunch")
        self.assertEqual(entry["meal_date"], "2026-09-24")

    def test_normalize_invalid_meal_type(self) -> None:
        with self.assertRaises(AppError) as cm:
            normalize_nutrition_entry(
                {"description": "Test", "kcal": 100, "meal_type": "brunch"}
            )
        self.assertEqual(cm.exception.status, 400)

    def test_zero_values_are_preserved_and_client_cannot_claim_sync_state(self) -> None:
        entry = normalize_nutrition_entry(
            {
                "meal_date": "2026-09-24",
                "description": "Plain tea",
                "kcal": 0,
                "carbs_g": 0,
                "protein_g": 0,
                "fat_g": 0,
                "sync_state": "synced",
            }
        )
        self.assertEqual(entry["kcal"], 0)
        self.assertEqual(
            (entry["carbs_g"], entry["protein_g"], entry["fat_g"]), (0, 0, 0)
        )
        self.assertEqual(entry["sync_state"], "local")


class NutritionRepositoryAndServiceTests(unittest.TestCase):
    def test_missing_database_macros_do_not_fall_back_to_supplied_aliases(self):
        calculation = {
            "kcal": 100,
            "carbs_g": None,
            "protein_g": None,
            "fat_g": None,
            "nutrition_basis": {"kind": "database", "ingredients": []},
        }
        payload = {
            "description": "Incomplete product label",
            "name": "Product",
            "food_ingredients": [
                {"food_id": "off:12345678", "amount": 100, "unit": "g"}
            ],
            "carbs": 99,
            "protein": 99,
            "fat": 99,
        }
        with patch.object(
            self.library.food_database, "calculate", return_value=calculation
        ):
            entry = self.service.log_meal(payload)
            template = self.library.save_template(payload)
        for result in (entry, template, self.service.get_meal(entry["id"])):
            self.assertEqual(result["kcal"], 100)
            for nutrient in ("carbs_g", "protein_g", "fat_g"):
                self.assertIsNone(result[nutrient])

    def test_composite_components_resolve_and_freeze_mixed_sources(self):
        product = self.library.save_product(
            {
                "name": "Synthetic whey",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 376,
                "carbs_g": 8,
                "protein_g": 78,
                "fat_g": 5.5,
            }
        )
        components = [
            {
                "kind": "local_product",
                "product_id": product["id"],
                "amount": 25,
                "unit": "g",
            },
            {"kind": "database", "food_id": "bls:C133000", "amount": 10, "unit": "g"},
            {
                "kind": "manual",
                "name": "Creatine",
                "amount": 5,
                "unit": "g",
                "kcal": 0,
                "carbs_g": 0,
                "protein_g": 0,
                "fat_g": 0,
            },
        ]
        result = self.library.calculate_components(components)
        self.assertEqual(result["nutrition_basis"]["kind"], "composite")
        self.assertEqual(
            [item["kind"] for item in result["nutrition_basis"]["components"]],
            ["local_product", "database", "manual"],
        )
        self.assertEqual(result["nutrition_basis"]["components"][2]["kcal"], 0)
        entry = self.service.log_meal(
            {"description": "Whey, honey, creatine", "components": components}
        )
        self.assertEqual(entry["nutrition_basis"], result["nutrition_basis"])
        self.assertEqual(entry["kcal"], result["kcal"])
        self.assertEqual(
            self.service.get_day_summary(entry["meal_date"])["entry_count"], 1
        )
        self.library.update_product(product["id"], {"kcal": 400})
        self.assertEqual(self.service.get_meal(entry["id"])["kcal"], result["kcal"])

    def test_database_component_resolution_happens_before_database_lock(self):
        component = {
            "kind": "database",
            "food_id": "bls:C133000",
            "amount": 10,
            "unit": "g",
        }
        original_resolve = self.library.food_database.resolve
        calls = []

        def resolve_outside_lock(food_id):
            self.assertFalse(self.lock.locked())
            calls.append(food_id)
            return original_resolve(food_id)

        with patch.object(
            self.library.food_database, "resolve", side_effect=resolve_outside_lock
        ):
            self.library.calculate_components([component])

        self.assertEqual(calls, ["bls:C133000"])

    def test_composite_rejects_forged_authoritative_values_and_unknown_macros_propagate(
        self,
    ):
        for component in (
            {
                "kind": "database",
                "food_id": "bls:C133000",
                "amount": 10,
                "unit": "g",
                "kcal": 0,
            },
            {
                "kind": "estimate",
                "name": "Estimate",
                "amount": 1,
                "unit": "portion",
                "kcal": 10,
                "carbs_g": None,
                "protein_g": 1,
                "fat_g": 1,
                "nutrition_basis": {"kind": "database"},
            },
        ):
            with self.subTest(component=component), self.assertRaises(AppError):
                self.library.calculate_components([component])
        estimated = {
            "kind": "estimate",
            "name": "Unknown carbs",
            "amount": 1,
            "unit": "portion",
            "kcal": 50,
            "carbs_g": None,
            "protein_g": 2,
            "fat_g": 1,
        }
        entry = self.service.log_meal(
            {"description": "Snack", "components": [estimated]}
        )
        self.assertIsNone(entry["carbs_g"])
        self.assertIsNone(
            self.service.get_day_summary(entry["meal_date"])["total_carbs_g"]
        )
        self.assertIsNone(
            self.service.get_sync_snapshot(entry["meal_date"])["total_carbs_g"]
        )
        self.assertIsNone(
            self.service.get_range_summary(entry["meal_date"], entry["meal_date"])[0][
                "total_carbs_g"
            ]
        )

    def test_composite_template_expected_calculation_covers_snapshot(self):
        components = [
            {
                "kind": "manual",
                "name": "Gel",
                "amount": 1,
                "unit": "portion",
                "kcal": 90,
                "carbs_g": 22,
                "protein_g": 0,
                "fat_g": 0,
            }
        ]
        calculation = self.library.calculate_components(components)
        template = self.library.save_template(
            {"name": "Gel", "description": "Race gel", "components": components},
            expected_calculation=calculation,
        )
        self.assertEqual(template["nutrition_basis"], calculation["nutrition_basis"])
        stale = {
            **calculation,
            "nutrition_basis": {**calculation["nutrition_basis"], "components": []},
        }
        with self.assertRaises(AppError) as raised:
            self.library.save_template(
                {
                    "name": "Stale gel",
                    "description": "Race gel",
                    "components": components,
                },
                expected_calculation=stale,
            )
        self.assertEqual(raised.exception.reason, "food_calculation_changed")

    def test_component_replacement_metadata_and_template_portion_snapshots(self):
        first = [
            {
                "kind": "manual",
                "name": "Manual",
                "amount": 1,
                "unit": "portion",
                "kcal": 10,
                "carbs_g": 1,
                "protein_g": 0,
                "fat_g": 0,
            }
        ]
        second = [
            {
                "kind": "estimate",
                "name": "Estimate",
                "amount": 1,
                "unit": "portion",
                "kcal": 10,
                "carbs_g": 1,
                "protein_g": 0,
                "fat_g": 0,
            }
        ]
        entry = self.service.log_meal({"description": "Meal", "components": first})
        changed = self.service.correct_meal(entry["id"], {"components": second})
        self.assertEqual(
            changed["nutrition_basis"]["components"][0]["kind"], "estimate"
        )
        template = self.library.save_template(
            {"name": "Meal", "description": "Meal", "components": first}
        )
        replaced = self.library.save_template(
            {"id": template["id"], "name": "Meal", "components": second}
        )
        self.assertEqual(
            replaced["nutrition_basis"]["components"][0]["kind"], "estimate"
        )
        scaled = self.library.save_template(
            {
                "name": "Fraction",
                "description": "Fraction",
                "components": [
                    {
                        "kind": "estimate",
                        "name": "Fraction",
                        "amount": 1,
                        "unit": "portion",
                        "kcal": 1.4,
                        "carbs_g": 0.04,
                        "protein_g": 0,
                        "fat_g": 0,
                    }
                ],
            }
        )
        logged = self.service.log_template(scaled["id"], 2)
        self.assertEqual(logged["kcal"], 3)
        self.assertEqual(logged["carbs_g"], 0.1)
        item = logged["nutrition_basis"]["components"][0]
        self.assertEqual(item["amount"], 2)
        self.assertEqual(item["kcal"], 2.8)

    def test_composite_limits_validate_before_any_write_and_metadata_preserves_archived_snapshot(
        self,
    ):
        invalids = (
            None,
            [],
            [
                {
                    "kind": "manual",
                    "name": "x",
                    "amount": 0,
                    "unit": "g",
                    "kcal": 1,
                    "carbs_g": 0,
                    "protein_g": 0,
                    "fat_g": 0,
                }
            ],
            [
                {
                    "kind": "manual",
                    "name": "x",
                    "amount": 1,
                    "unit": "g",
                    "kcal": 10001,
                    "carbs_g": 0,
                    "protein_g": 0,
                    "fat_g": 0,
                }
            ],
        )
        for components in invalids:
            with self.subTest(components=components), self.assertRaises(AppError):
                self.service.log_meal(
                    {"description": "Invalid", "components": components}
                )
        many = [
            {
                "kind": "manual",
                "name": "x",
                "amount": 1,
                "unit": "g",
                "kcal": 1,
                "carbs_g": 0,
                "protein_g": 0,
                "fat_g": 0,
            }
        ] * 21
        with self.assertRaises(AppError):
            self.library.save_template(
                {"name": "Too many", "description": "Invalid", "components": many}
            )
        self.assertEqual(self.service.get_today_summary()["entry_count"], 0)
        product = self.library.save_product(
            {
                "name": "Archive test",
                "basis_amount": 100,
                "basis_unit": "g",
                "kcal": 100,
                "carbs_g": 10,
                "protein_g": 5,
                "fat_g": 2,
            }
        )
        consumed = self.service.log_meal(
            {
                "description": "Product",
                "components": [
                    {
                        "kind": "local_product",
                        "product_id": product["id"],
                        "amount": 10,
                        "unit": "g",
                    }
                ],
            }
        )
        self.library.archive_product(product["id"])
        renamed = self.service.update_meal(consumed["id"], {"description": "Renamed"})
        self.assertEqual(renamed["nutrition_basis"], consumed["nutrition_basis"])

    def test_database_values_override_model_values_and_provenance_survives_corrections(
        self,
    ):
        payload = {
            "description": "50 g oats",
            "kcal": 999,
            "food_ingredients": [{"food_id": "bls:C133000", "amount": 50, "unit": "g"}],
            "source": "coach",
        }
        entry = self.service.log_meal(payload)
        self.assertEqual(entry["kcal"], 174)
        self.assertEqual(entry["nutrition_basis"]["ingredients"][0]["amount"], 50)
        updated = self.service.update_meal(entry["id"], {"description": "Renamed oats"})
        self.assertEqual(updated["description"], "Renamed oats")
        self.assertEqual(updated["nutrition_basis"], entry["nutrition_basis"])
        self.assertEqual(
            self.service.get_today_summary()["entries"][0]["nutrition_basis"],
            entry["nutrition_basis"],
        )
        changed = self.service.correct_meal(entry["id"], {"meal_time": "09:00"})
        self.assertEqual(changed["nutrition_basis"], entry["nutrition_basis"])
        changed = self.service.correct_meal(entry["id"], {"kcal": 200})
        self.assertEqual(changed["nutrition_basis"]["kind"], "manual_correction")
        changed = self.service.correct_meal(
            entry["id"],
            {
                "food_ingredients": [
                    {"food_id": "bls:C133000", "amount": 100, "unit": "g"}
                ]
            },
        )
        self.assertEqual(changed["kcal"], 348)
        template = self.library.save_template({**payload, "name": "Oats"})
        logged = self.service.log_template(template["id"], 0.5)
        self.assertEqual(logged["kcal"], 87)
        self.assertEqual(logged["nutrition_basis"]["ingredients"][0]["amount"], 25)
        renamed = self.library.save_template(
            {
                "id": template["id"],
                "name": "Oats breakfast",
                "kcal": template["kcal"],
            }
        )
        self.assertEqual(renamed["nutrition_basis"], template["nutrition_basis"])
        packaged = self.library.save_template(
            {
                "id": template["id"],
                "kcal": template["kcal"],
                "packaging_label": True,
            }
        )
        self.assertEqual(packaged["nutrition_basis"]["kind"], "packaging_label")
        corrected = self.library.save_template({"id": template["id"], "kcal": 700})
        self.assertEqual(corrected["nutrition_basis"]["kind"], "estimate")
        self.assertEqual(
            self.service.get_meal(logged["id"])["nutrition_basis"],
            logged["nutrition_basis"],
        )
        calculation = self.library.food_database.calculate(payload["food_ingredients"])
        with self.assertRaises(AppError) as raised:
            self.library.save_template(
                {**payload, "name": "Stale preview"},
                expected_calculation={**calculation, "kcal": 999},
            )
        self.assertEqual(raised.exception.reason, "food_calculation_changed")
        self.assertEqual(len(self.library.list_templates()), 1)

    def test_failed_database_calculation_does_not_save_or_accept_forged_provenance(
        self,
    ):
        with self.assertRaises(AppError):
            self.service.log_meal(
                {
                    "description": "Unknown",
                    "kcal": 100,
                    "food_ingredients": [
                        {"food_id": "bls:missing", "amount": 100, "unit": "g"}
                    ],
                }
            )
        self.assertEqual(self.service.get_today_summary()["entry_count"], 0)
        entry = self.service.log_meal(
            {
                "description": "Estimate",
                "kcal": 100,
                "source": "coach",
                "nutrition_basis": {"kind": "database"},
            }
        )
        self.assertEqual(entry["nutrition_basis"]["kind"], "estimate")
        label_entry = self.service.log_meal(
            {
                "description": "Packaged snack",
                "kcal": 180,
                "source": "voice",
                "packaging_label": True,
            }
        )
        self.assertEqual(label_entry["nutrition_basis"]["kind"], "packaging_label")
        corrected = self.service.correct_meal(
            entry["id"], {"kcal": 110, "packaging_label": True}
        )
        self.assertEqual(corrected["nutrition_basis"]["kind"], "packaging_label")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_nutrition.db"
        self.manager = DatabaseManager(self.db_path, sqlite3, row_factory=sqlite3.Row)
        self.lock = threading.Lock()
        with self.manager.unit_of_work() as db:
            initialize_schema(db)

        self.fixed_now = "2026-09-24T12:00:00+00:00"
        self.service, self.library = build_nutrition_services(
            self.manager,
            self.lock,
            lambda: self.fixed_now,
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_templates_are_not_consumption_and_logs_are_immutable_snapshots(
        self,
    ) -> None:
        template = self.library.save_template(
            {
                "name": "Breakfast",
                "description": "80 g oats",
                "kcal": 400,
                "carbs_g": 60,
                "protein_g": 12,
                "fat_g": 8,
                "source": "coach",
            }
        )
        self.assertEqual(self.service.get_today_summary()["entry_count"], 0)
        self.assertEqual(self.service.list_unsynced_dates(), [])
        entry = self.service.log_template(
            template["id"], 0.5, meal_date="2026-09-23", meal_time="08:15"
        )
        self.assertEqual(entry["kcal"], 200)
        self.assertEqual(entry["carbs_g"], 30)
        self.assertEqual(entry["logged_at"], "2026-09-23T08:15")
        updated = self.library.save_template({"id": template["id"], "kcal": 600})
        self.assertEqual(updated["name"], "Breakfast")
        self.assertEqual(updated["kcal"], 600)
        self.assertEqual(self.service.get_meal(entry["id"])["kcal"], 200)
        self.library.delete_template(template["id"])
        self.assertEqual(self.library.list_templates(), [])
        self.assertEqual(self.service.get_meal(entry["id"])["kcal"], 200)

    def test_logging_saved_meal_on_past_date_defaults_timestamp_to_that_date(
        self,
    ) -> None:
        template = self.library.save_template(
            {"name": "Snack", "description": "Fruit", "kcal": 120}
        )
        entry = self.service.log_template(template["id"], meal_date="2026-09-23")
        self.assertEqual(entry["meal_date"], "2026-09-23")
        self.assertEqual(entry["logged_at"], "2026-09-23T12:00")

    def test_template_meal_type_defaults_from_consumption_time_and_keeps_explicit_type(
        self,
    ) -> None:
        inferred = self.library.save_template(
            {
                "name": "Time inferred",
                "description": "Food",
                "kcal": 100,
                "source": "coach",
            }
        )
        inferred_entry = self.service.log_template(inferred["id"], meal_time="19:10")
        self.assertEqual(inferred_entry["meal_type"], "dinner")
        self.assertEqual(inferred_entry["source"], "coach")

        explicit = self.library.save_template(
            {
                "name": "Explicit breakfast",
                "description": "Food",
                "kcal": 100,
                "meal_type": "breakfast",
                "source": "coach",
            }
        )
        explicit_entry = self.service.log_template(explicit["id"], meal_time="19:10")
        self.assertEqual(explicit_entry["meal_type"], "breakfast")
        self.assertEqual(explicit_entry["source"], "coach")

    def test_template_validation_preserves_state(self) -> None:
        template = self.library.save_template(
            {"name": "Snack", "description": "Synthetic snack", "kcal": 500}
        )
        for amount in [0, -1, 21, float("nan"), float("inf"), "invalid"]:
            with self.subTest(amount=amount), self.assertRaises(AppError):
                self.service.log_template(template["id"], amount)
        with self.assertRaises(AppError):
            self.library.save_template(
                {"name": "snack", "description": "Other", "kcal": 100}
            )
        with self.assertRaises(AppError):
            self.library.save_template(
                {
                    "id": "missing",
                    "name": "Missing",
                    "description": "Other",
                    "kcal": 100,
                }
            )
        self.assertEqual(len(self.library.list_templates()), 1)
        self.assertEqual(self.service.get_today_summary()["entry_count"], 0)

    def test_log_and_get_meal(self) -> None:
        saved = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "lunch",
                "description": "Pasta mit Pesto",
                "kcal": 650,
                "carbs_g": 85,
                "protein_g": 20,
                "fat_g": 25,
                "source": "manual",
            }
        )
        self.assertIsNotNone(saved["id"])
        self.assertEqual(saved["kcal"], 650)
        self.assertEqual(saved["meal_type"], "lunch")

        fetched = self.service.get_meal(saved["id"])
        self.assertEqual(fetched["id"], saved["id"])
        self.assertEqual(fetched["description"], "Pasta mit Pesto")

    def test_approval_manifest_freezes_revision_and_totals_without_mutating_sync_state(
        self,
    ) -> None:
        self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "description": "Oats",
                "kcal": 400,
                "carbs_g": 60,
                "protein_g": 15,
                "fat_g": 8,
            }
        )
        before = self.service.approval_manifest(meal_date="2026-09-24")
        self.assertEqual(before[0]["total_kcal"], 400)
        self.assertEqual(before[0]["entry_count"], 1)
        self.assertEqual(before[0]["revision"], 1)
        self.service.correct_meal(
            self.service.get_day_summary("2026-09-24")["entries"][0]["id"],
            {"kcal": 450},
        )
        after = self.service.approval_manifest(dates=["2026-09-24"])
        self.assertNotEqual(before, after)
        self.assertEqual(after[0]["total_kcal"], 450)

    def test_update_meal(self) -> None:
        saved = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "lunch",
                "description": "Salat",
                "kcal": 200,
            }
        )
        updated = self.service.update_meal(
            saved["id"],
            {
                "meal_date": "2026-09-24",
                "meal_type": "lunch",
                "description": "Großer Salat mit Hähnchen",
                "kcal": 450,
                "protein_g": 35.0,
            },
        )
        self.assertEqual(updated["description"], "Großer Salat mit Hähnchen")
        self.assertEqual(updated["kcal"], 450)
        self.assertEqual(updated["protein_g"], 35.0)

    def test_correct_meal_preserves_omitted_fields_and_marks_old_and_new_days_pending(
        self,
    ) -> None:
        saved = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "logged_at": "2026-09-24T12:15:00",
                "meal_type": "lunch",
                "description": "Bowl",
                "kcal": 500,
                "carbs_g": 60,
                "protein_g": 20,
                "fat_g": 10,
                "source": "photo",
            }
        )
        old_day = self.service.get_sync_snapshot("2026-09-24")
        self.assertTrue(
            self.service.mark_date_synced("2026-09-24", old_day["sync_revision"])
        )

        corrected = self.service.correct_meal(
            saved["id"], {"kcal": 600, "meal_date": "2026-09-25"}
        )

        self.assertEqual(corrected["id"], saved["id"])
        self.assertEqual(corrected["kcal"], 600)
        self.assertEqual(corrected["meal_date"], "2026-09-25")
        self.assertEqual(corrected["logged_at"], "2026-09-24T12:15:00")
        self.assertEqual(corrected["description"], "Bowl")
        self.assertEqual(
            (corrected["carbs_g"], corrected["protein_g"], corrected["fat_g"]),
            (60, 20, 10),
        )
        self.assertEqual(corrected["source"], "photo")
        self.assertEqual(
            self.service.list_unsynced_dates(), ["2026-09-24", "2026-09-25"]
        )

    def test_correct_meal_rejects_empty_invalid_or_missing_target(self) -> None:
        saved = self.service.log_meal({"description": "Tea", "kcal": 5})
        for entry_id, changes in (
            (saved["id"], {}),
            (saved["id"], {"kcal": -1}),
            ("missing", {"kcal": 5}),
        ):
            with (
                self.subTest(entry_id=entry_id, changes=changes),
                self.assertRaises(AppError),
            ):
                self.service.correct_meal(entry_id, changes)

    def test_correct_meal_aliases_override_stored_canonical_fields(self) -> None:
        saved = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "logged_at": "2026-09-24T12:15:00",
                "description": "Lunch",
                "kcal": 500,
                "carbs_g": 60,
            }
        )
        corrected = self.service.correct_meal(
            saved["id"],
            {
                "meal_time": "13:30",
                "calories": 600,
                "carbohydrates": 70,
            },
        )
        self.assertEqual(corrected["logged_at"], "2026-09-24T13:30")
        self.assertEqual(corrected["kcal"], 600)
        self.assertEqual(corrected["carbs_g"], 70)

    def test_delete_meal(self) -> None:
        saved = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "snack",
                "description": "Apfel",
                "kcal": 80,
            }
        )
        result = self.service.delete_meal(saved["id"])
        self.assertEqual(result["status"], "ok")

        with self.assertRaises(AppError) as cm:
            self.service.get_meal(saved["id"])
        self.assertEqual(cm.exception.status, 404)

    def test_deleting_last_synced_entry_keeps_empty_date_pending(self) -> None:
        saved = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "lunch",
                "description": "Lunch",
                "kcal": 500,
            }
        )
        snapshot = self.service.get_sync_snapshot("2026-09-24")
        self.assertTrue(
            self.service.mark_date_synced("2026-09-24", snapshot["sync_revision"])
        )
        self.assertEqual(self.service.list_unsynced_dates(), [])
        self.service.delete_meal(saved["id"])
        self.assertEqual(self.service.list_unsynced_dates(), ["2026-09-24"])
        self.assertEqual(self.service.get_day_summary("2026-09-24")["total_kcal"], 0)

    def test_day_summary(self) -> None:
        self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "breakfast",
                "description": "Müsli",
                "kcal": 400,
                "carbs_g": 60,
                "protein_g": 15,
                "fat_g": 10,
            }
        )
        self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "lunch",
                "description": "Reis mit Tofu",
                "kcal": 600,
                "carbs_g": 80,
                "protein_g": 25,
                "fat_g": 15,
            }
        )
        summary = self.service.get_day_summary("2026-09-24")
        self.assertEqual(summary["date"], "2026-09-24")
        self.assertEqual(summary["total_kcal"], 1000)
        self.assertEqual(summary["total_carbs_g"], 140.0)
        self.assertEqual(summary["total_protein_g"], 40.0)
        self.assertEqual(summary["total_fat_g"], 25.0)
        self.assertEqual(summary["entry_count"], 2)

    def test_range_summary_and_unsynced_dates(self) -> None:
        self.service.log_meal(
            {
                "meal_date": "2026-09-23",
                "meal_type": "dinner",
                "description": "Suppe",
                "kcal": 300,
            }
        )
        self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "lunch",
                "description": "Sandwich",
                "kcal": 500,
            }
        )
        summaries = self.service.get_range_summary("2026-09-22", "2026-09-25")
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["date"], "2026-09-23")
        self.assertEqual(summaries[1]["date"], "2026-09-24")

        unsynced = self.service.list_unsynced_dates()
        self.assertIn("2026-09-23", unsynced)
        self.assertIn("2026-09-24", unsynced)

        sync_snapshot = self.service.get_sync_snapshot("2026-09-23")
        self.service.mark_date_synced("2026-09-23", sync_snapshot["sync_revision"])
        unsynced_after = self.service.list_unsynced_dates()
        self.assertNotIn("2026-09-23", unsynced_after)
        self.assertIn("2026-09-24", unsynced_after)

    def test_context_returns_today_and_recent(self) -> None:
        self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "breakfast",
                "description": "Porridge",
                "kcal": 350,
            }
        )
        ctx = self.service.context()
        self.assertIn("today", ctx)
        self.assertEqual(ctx["today"]["total_kcal"], 350)
        self.assertIn("recent_entries", ctx)


if __name__ == "__main__":
    unittest.main()
