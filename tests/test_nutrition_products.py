from __future__ import annotations

import base64
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.db.manager import DatabaseManager
from backend.db.repositories import NutritionRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition.photo import (
    NutritionPhotoExtractionService,
    validate_packaging_extraction,
)
from backend.nutrition.service import NutritionService


class NutritionProductContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = DatabaseManager(
            Path(self.temporary.name) / "nutrition-products.db",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
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
        self.service = NutritionService(
            database_manager=self.manager,
            db_lock=self.lock,
            nutrition_repository=NutritionRepository(
                now=lambda: "2026-10-05T12:00:00+00:00"
            ),
            utc_now=lambda: "2026-10-05T12:00:00+00:00",
            local_now=lambda: datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc),
            food_database=self.food_database,
        )

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

    def test_confirmed_product_is_persistent_and_can_be_archived(self):
        saved = self.service.save_product(self.product_payload())

        self.assertTrue(saved["id"])
        self.assertEqual(saved["barcode"], "4006381333931")
        self.assertEqual(saved["source"], "packaging_label")
        self.assertEqual(saved["status"], "active")
        self.assertEqual(self.service.get_product(saved["id"])["name"], saved["name"])
        self.assertEqual(
            self.service.list_products(barcode="4006381333931")[0]["id"], saved["id"]
        )

        updated = self.service.update_product(saved["id"], {"protein_g": 80.0})
        self.assertEqual(updated["protein_g"], 80.0)
        self.assertEqual(self.service.get_product(saved["id"])["protein_g"], 80.0)

        archived = self.service.archive_product(saved["id"])
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self.service.list_products(barcode="4006381333931"), [])
        self.assertEqual(
            self.service.list_products(barcode="4006381333931", include_archived=True)[
                0
            ]["status"],
            "archived",
        )

    def test_barcode_lookup_prefers_local_product_and_never_calls_remote(self):
        saved = self.service.save_product(self.product_payload())

        result = self.service.lookup_product({"barcode": "4006381333931"})

        self.assertEqual(result["source"], "local")
        self.assertEqual(result["foods"][0]["id"], saved["id"])
        self.food_database.lookup.assert_not_called()

    def test_unknown_barcode_falls_back_to_food_database_and_labels_source(self):
        result = self.service.lookup_product({"barcode": "4006381333999"})

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
        self.assertEqual(self.service.list_products(), [])

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
            self.service.save_product(self.product_payload(source="coach"))

    def test_product_nutrients_are_snapshotted_when_consumed(self):
        saved = self.service.save_product(self.product_payload())
        entry = self.service.log_product(saved["id"], 50, "g")
        self.assertEqual(entry["kcal"], 188)
        self.assertEqual(entry["protein_g"], 39)
        self.assertEqual(entry["nutrition_basis"]["kind"], "local_product")

        self.service.update_product(saved["id"], {"kcal": 400, "protein_g": 82})

        fetched = self.service.get_meal(entry["id"])
        self.assertEqual(fetched["kcal"], 188)
        self.assertEqual(fetched["protein_g"], 39)
        self.assertEqual(fetched["nutrition_basis"]["product"]["kcal"], 376)

    def test_product_calculation_preserves_unknown_nutrients_and_does_not_convert_units(
        self,
    ):
        saved = self.service.save_product(
            self.product_payload(basis_unit="ml", carbs_g=None, protein_g=None)
        )

        result = self.service.calculate_product(saved["id"], 250, "ml")

        self.assertEqual(result["kcal"], 940)
        self.assertIsNone(result["carbs_g"])
        self.assertIsNone(result["protein_g"])
        with self.assertRaises(AppError):
            self.service.calculate_product(saved["id"], 250, "g")

    def test_photo_candidate_is_not_saved_until_explicit_save(self):
        response = {
            "output_text": '{"name":"Synthetic cocoa mix","basis_amount":100,"basis_unit":"g","kcal":376,"protein_g":78}'
        }
        extractor = NutritionPhotoExtractionService(
            selected_provider=lambda: "openai",
            selected_model=lambda _provider: "gpt-6-luna",
            openai_request=lambda _path, _payload: response,
        )
        self.service._photo_extractor = extractor
        data_url = "data:image/jpeg;base64," + base64.b64encode(
            b"\xff\xd8\xffsynthetic-image"
        ).decode("ascii")

        candidate = self.service.extract_packaging_photo({"image_data_url": data_url})

        self.assertTrue(candidate["requires_confirmation"])
        self.assertEqual(candidate["provenance"], "packaging_label")
        self.assertNotIn("image_data_url", candidate)
        self.assertEqual(self.service.list_products(), [])
        self.assertTrue(
            self.service.save_product({**candidate["candidate"], "confirmed": True})[
                "id"
            ]
        )

    def test_database_backup_contains_confirmed_products(self):
        self.service.save_product(self.product_payload())
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
