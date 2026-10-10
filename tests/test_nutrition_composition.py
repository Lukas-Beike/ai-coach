from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from nutrition_service_support import build_nutrition_services

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.errors import AppError


class NutritionCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "nutrition.db"
        self.manager = DatabaseManager(self.db_path, sqlite3, row_factory=sqlite3.Row)
        self.lock = threading.Lock()
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.fixed_now = "2026-09-24T12:00:00+00:00"
        self._make_service()

    def _make_service(self) -> None:
        self.service, self.library = build_nutrition_services(
            self.manager,
            self.lock,
            lambda: self.fixed_now,
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

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

    def test_rejects_unhashable_types_and_non_string_references(self) -> None:
        valid = {
            "kind": "manual",
            "name": "Snack",
            "amount": 1,
            "unit": "portion",
            "kcal": 10,
            "carbs_g": 1,
            "protein_g": 0,
            "fat_g": 0,
        }
        for field, value in (("kind", []), ("unit", {})):
            with self.subTest(field=field), self.assertRaises(AppError):
                self.library.calculate_components([{**valid, field: value}])
        with self.assertRaises(AppError):
            self.library.calculate_components(
                [{"kind": "database", "food_id": [], "amount": 1, "unit": "g"}]
            )

    def test_rejects_per_component_limits_and_preserves_unknown_totals_atomically(
        self,
    ) -> None:
        valid = {
            "kind": "manual",
            "name": "Snack",
            "amount": 1,
            "unit": "portion",
            "kcal": 10,
            "carbs_g": 1,
            "protein_g": 0,
            "fat_g": 0,
        }
        mixed = self.library.calculate_components(
            [valid, {**valid, "name": "Unknown", "carbs_g": None}]
        )
        self.assertIsNone(mixed["carbs_g"])
        unknown_carbs = {**valid, "name": "Unknown", "carbs_g": None}
        over_limit_carbs = {**valid, "name": "Excess", "carbs_g": 1001}
        with self.assertRaises(AppError):
            self.service.log_meal(
                {
                    "description": "Invalid",
                    "components": [unknown_carbs, over_limit_carbs],
                }
            )
        self.assertEqual(self.service.get_today_summary()["entry_count"], 0)
        with self.assertRaises(AppError):
            self.library.calculate_components([{**valid, "kcal": 10001}])

    def test_restart_and_database_backup_keep_composite_entries_and_templates(
        self,
    ) -> None:
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
        entry = self.service.log_meal(
            {"description": "Race gel", "components": components}
        )
        template = self.library.save_template(
            {
                "name": "Race gel",
                "description": "Gel",
                "components": components,
            }
        )
        expected_entry_basis = entry["nutrition_basis"]
        expected_template_basis = template["nutrition_basis"]

        backup = DatabaseBackupService(
            self.manager,
            self.lock,
            DatabaseBackupConfig(
                database_path=self.db_path,
                data_dir=Path(self.temp_dir.name),
                maximum_bytes=2_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=10,
                disk_usage=lambda _path: SimpleNamespace(free=2_000_000),
            ),
            Mock(),
        ).read_bytes()
        backup_path = Path(self.temp_dir.name) / "backup.db"
        backup_path.write_bytes(backup)
        snapshot = sqlite3.connect(backup_path)
        try:
            stored_entry = snapshot.execute(
                "SELECT nutrition_basis FROM nutrition_logs WHERE id = ?",
                (entry["id"],),
            ).fetchone()[0]
            stored_template = snapshot.execute(
                "SELECT payload FROM nutrition_templates WHERE id = ?",
                (template["id"],),
            ).fetchone()[0]
        finally:
            snapshot.close()
        self.assertEqual(json.loads(stored_entry), expected_entry_basis)
        self.assertEqual(
            json.loads(stored_template)["nutrition_basis"], expected_template_basis
        )

        self.manager.close()
        self.manager = DatabaseManager(self.db_path, sqlite3, row_factory=sqlite3.Row)
        self._make_service()
        self.assertEqual(
            self.service.get_meal(entry["id"])["nutrition_basis"], expected_entry_basis
        )
        self.assertEqual(
            self.library.list_templates()[0]["nutrition_basis"], expected_template_basis
        )

    def test_composite_unknown_nutrients_flow_through_day_range_and_sync(self) -> None:
        known = {
            "kind": "manual",
            "name": "Known",
            "amount": 1,
            "unit": "portion",
            "kcal": 40,
            "carbs_g": 5,
            "protein_g": 2,
            "fat_g": 1,
        }
        unknown = {
            "kind": "estimate",
            "name": "Unknown",
            "amount": 1,
            "unit": "portion",
            "kcal": 20,
            "carbs_g": None,
            "protein_g": 1,
            "fat_g": 0,
        }
        first = self.service.log_meal({"description": "Known", "components": [known]})
        self.service.log_meal({"description": "Unknown", "components": [unknown]})
        for summary in (
            self.service.get_day_summary(first["meal_date"]),
            self.service.get_range_summary(first["meal_date"], first["meal_date"])[0],
            self.service.get_sync_snapshot(first["meal_date"]),
        ):
            self.assertEqual(summary["entry_count"], 2)
            self.assertEqual(summary["total_kcal"], 60)
            self.assertIsNone(summary["total_carbs_g"])

    def test_update_meal_replaces_composite_components_even_when_totals_match(
        self,
    ) -> None:
        original = {
            "kind": "manual",
            "name": "A",
            "amount": 1,
            "unit": "portion",
            "kcal": 10,
            "carbs_g": 2,
            "protein_g": 1,
            "fat_g": 0,
        }
        replacement = {**original, "name": "B", "kind": "estimate"}
        entry = self.service.log_meal({"description": "Meal", "components": [original]})
        updated = self.service.update_meal(
            entry["id"],
            {
                "description": "Meal",
                "components": [replacement],
            },
        )
        self.assertEqual(
            (updated["kcal"], updated["carbs_g"]), (entry["kcal"], entry["carbs_g"])
        )
        self.assertEqual(updated["nutrition_basis"]["components"][0]["name"], "B")

    def test_local_product_requires_calories_and_rejects_archived_products(
        self,
    ) -> None:
        product = self.library.save_product(
            {
                "name": "Incomplete",
                "basis_amount": 100,
                "basis_unit": "g",
                "carbs_g": 1,
                "protein_g": 1,
                "fat_g": 1,
            }
        )
        component = {
            "kind": "local_product",
            "product_id": product["id"],
            "amount": 10,
            "unit": "g",
        }
        with self.assertRaises(AppError):
            self.library.calculate_components([component])
        complete = self.library.update_product(product["id"], {"kcal": 10})
        self.assertEqual(complete["kcal"], 10)
        self.library.archive_product(product["id"])
        with self.assertRaises(AppError):
            self.library.calculate_components([component])
