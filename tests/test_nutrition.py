from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.db.manager import DatabaseManager
from backend.db.repositories import NutritionRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition import (
    NutritionDaySummary,
    NutritionEntry,
    NutritionService,
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
        fixed_dt = datetime(2026, 9, 24, 12, 30, tzinfo=timezone.utc)
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
            {"meal_date": "2026-09-24", "meal_time": "07:15", "description": "Oats", "kcal": 350},
            local_now_factory=lambda: datetime(2026, 9, 24, 18, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(entry["logged_at"], "2026-09-24T07:15")
        self.assertEqual(entry["meal_type"], "breakfast")

    def test_normalize_defaults_and_clamps(self) -> None:
        fixed_dt = datetime(2026, 9, 24, 13, 15, tzinfo=timezone.utc)
        payload = {
            "description": "x" * 600,
            "kcal": 99999,
            "carbs_g": 5000.0,
            "protein_g": -10,
        }
        entry = normalize_nutrition_entry(payload, local_now_factory=lambda: fixed_dt, clamp_out_of_bounds=True)
        self.assertEqual(len(entry["description"]), 500)
        self.assertEqual(entry["kcal"], 10000)
        self.assertEqual(entry["carbs_g"], 1000.0)
        self.assertEqual(entry["protein_g"], 0.0)
        self.assertIsNone(entry["fat_g"])
        self.assertEqual(entry["meal_type"], "lunch")
        self.assertEqual(entry["meal_date"], "2026-09-24")

    def test_normalize_invalid_meal_type(self) -> None:
        with self.assertRaises(AppError) as cm:
            normalize_nutrition_entry({"description": "Test", "kcal": 100, "meal_type": "brunch"})
        self.assertEqual(cm.exception.status, 400)

    def test_zero_values_are_preserved_and_client_cannot_claim_sync_state(self) -> None:
        entry = normalize_nutrition_entry({
            "meal_date": "2026-09-24", "description": "Plain tea", "kcal": 0, "carbs_g": 0,
            "protein_g": 0, "fat_g": 0, "sync_state": "synced",
        })
        self.assertEqual(entry["kcal"], 0)
        self.assertEqual((entry["carbs_g"], entry["protein_g"], entry["fat_g"]), (0, 0, 0))
        self.assertEqual(entry["sync_state"], "local")


class NutritionRepositoryAndServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_nutrition.db"
        self.manager = DatabaseManager(self.db_path, sqlite3, row_factory=sqlite3.Row)
        self.lock = threading.Lock()
        with self.manager.unit_of_work() as db:
            initialize_schema(db)

        self.fixed_now = "2026-09-24T12:00:00+00:00"
        self.repo = NutritionRepository(now=lambda: self.fixed_now)
        self.service = NutritionService(
            database_manager=self.manager,
            db_lock=self.lock,
            nutrition_repository=self.repo,
            utc_now=lambda: self.fixed_now,
            local_now=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_log_and_get_meal(self) -> None:
        saved = self.service.log_meal({
            "meal_date": "2026-09-24",
            "meal_type": "lunch",
            "description": "Pasta mit Pesto",
            "kcal": 650,
            "carbs_g": 85,
            "protein_g": 20,
            "fat_g": 25,
            "source": "manual",
        })
        self.assertIsNotNone(saved["id"])
        self.assertEqual(saved["kcal"], 650)
        self.assertEqual(saved["meal_type"], "lunch")

        fetched = self.service.get_meal(saved["id"])
        self.assertEqual(fetched["id"], saved["id"])
        self.assertEqual(fetched["description"], "Pasta mit Pesto")

    def test_update_meal(self) -> None:
        saved = self.service.log_meal({
            "meal_date": "2026-09-24",
            "meal_type": "lunch",
            "description": "Salat",
            "kcal": 200,
        })
        updated = self.service.update_meal(saved["id"], {
            "meal_date": "2026-09-24",
            "meal_type": "lunch",
            "description": "Großer Salat mit Hähnchen",
            "kcal": 450,
            "protein_g": 35.0,
        })
        self.assertEqual(updated["description"], "Großer Salat mit Hähnchen")
        self.assertEqual(updated["kcal"], 450)
        self.assertEqual(updated["protein_g"], 35.0)

    def test_delete_meal(self) -> None:
        saved = self.service.log_meal({
            "meal_date": "2026-09-24",
            "meal_type": "snack",
            "description": "Apfel",
            "kcal": 80,
        })
        result = self.service.delete_meal(saved["id"])
        self.assertEqual(result["status"], "ok")

        with self.assertRaises(AppError) as cm:
            self.service.get_meal(saved["id"])
        self.assertEqual(cm.exception.status, 404)

    def test_deleting_last_synced_entry_keeps_empty_date_pending(self) -> None:
        saved = self.service.log_meal({
            "meal_date": "2026-09-24", "meal_type": "lunch", "description": "Lunch", "kcal": 500,
        })
        snapshot = self.service.get_sync_snapshot("2026-09-24")
        self.assertTrue(self.service.mark_date_synced("2026-09-24", snapshot["sync_revision"]))
        self.assertEqual(self.service.list_unsynced_dates(), [])
        self.service.delete_meal(saved["id"])
        self.assertEqual(self.service.list_unsynced_dates(), ["2026-09-24"])
        self.assertEqual(self.service.get_day_summary("2026-09-24")["total_kcal"], 0)

    def test_day_summary(self) -> None:
        self.service.log_meal({
            "meal_date": "2026-09-24",
            "meal_type": "breakfast",
            "description": "Müsli",
            "kcal": 400,
            "carbs_g": 60,
            "protein_g": 15,
            "fat_g": 10,
        })
        self.service.log_meal({
            "meal_date": "2026-09-24",
            "meal_type": "lunch",
            "description": "Reis mit Tofu",
            "kcal": 600,
            "carbs_g": 80,
            "protein_g": 25,
            "fat_g": 15,
        })
        summary = self.service.get_day_summary("2026-09-24")
        self.assertEqual(summary["date"], "2026-09-24")
        self.assertEqual(summary["total_kcal"], 1000)
        self.assertEqual(summary["total_carbs_g"], 140.0)
        self.assertEqual(summary["total_protein_g"], 40.0)
        self.assertEqual(summary["total_fat_g"], 25.0)
        self.assertEqual(summary["entry_count"], 2)

    def test_range_summary_and_unsynced_dates(self) -> None:
        self.service.log_meal({
            "meal_date": "2026-09-23",
            "meal_type": "dinner",
            "description": "Suppe",
            "kcal": 300,
        })
        self.service.log_meal({
            "meal_date": "2026-09-24",
            "meal_type": "lunch",
            "description": "Sandwich",
            "kcal": 500,
        })
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
        self.service.log_meal({
            "meal_date": "2026-09-24",
            "meal_type": "breakfast",
            "description": "Porridge",
            "kcal": 350,
        })
        ctx = self.service.context()
        self.assertIn("today", ctx)
        self.assertEqual(ctx["today"]["total_kcal"], 350)
        self.assertIn("recent_entries", ctx)


if __name__ == "__main__":
    unittest.main()
