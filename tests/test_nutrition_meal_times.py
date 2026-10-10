"""Honest meal times and display-only partial macro sums in the nutrition diary."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

from nutrition_service_support import build_nutrition_services

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition.contracts import nutrition_approval_item
from backend.nutrition.sync import IntervalsNutritionSyncService


class NutritionMealTimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = DatabaseManager(
            Path(self.temp_dir.name) / "meal_times.db", sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.service, _ = build_nutrition_services(
            self.manager,
            threading.Lock(),
            lambda: "2026-09-24T12:00:00+00:00",
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )

    def log_full_macros(self) -> dict:
        return self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "logged_at": "2026-09-24T08:15:00",
                "meal_type": "breakfast",
                "description": "Müsli",
                "kcal": 400,
                "carbs_g": 60,
                "protein_g": 15,
                "fat_g": 10,
            }
        )

    def log_without_macros(self) -> dict:
        return self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "snack",
                "description": "Unbekannter Snack",
                "kcal": 200,
            }
        )

    def sync_service(self) -> tuple[IntervalsNutritionSyncService, Mock]:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        api = Mock()
        return IntervalsNutritionSyncService(config, api, self.service), api

    def test_known_time_is_the_default_and_is_returned(self) -> None:
        entry = self.log_full_macros()

        self.assertIs(entry["logged_time_known"], True)
        self.assertEqual(entry["logged_at"], "2026-09-24T08:15:00")
        self.assertIs(self.service.get_meal(entry["id"])["logged_time_known"], True)

    def test_unknown_time_keeps_explicit_meal_type_and_noon_anchor(self) -> None:
        entry = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "logged_at": "2026-09-24T19:30:00",
                "meal_type": "dinner",
                "description": "Pasta",
                "kcal": 700,
                "logged_time_known": False,
            }
        )

        self.assertIs(entry["logged_time_known"], False)
        self.assertEqual(entry["logged_at"], "2026-09-24T12:00:00")
        self.assertEqual(entry["meal_type"], "dinner")
        stored = self.service.get_meal(entry["id"])
        self.assertIs(stored["logged_time_known"], False)

    def test_unknown_time_requires_an_explicit_meal_type(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.log_meal(
                {
                    "meal_date": "2026-09-24",
                    "description": "Ohne Typ",
                    "kcal": 300,
                    "logged_time_known": False,
                }
            )

        self.assertEqual(raised.exception.status, 400)

    def test_invalid_meal_type_is_rejected(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.log_meal(
                {
                    "meal_date": "2026-09-24",
                    "meal_type": "brunch",
                    "description": "Frühstück",
                    "kcal": 300,
                }
            )

        self.assertEqual(raised.exception.status, 400)

    def test_logged_time_known_must_be_a_boolean(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.log_meal(
                {
                    "meal_date": "2026-09-24",
                    "meal_type": "lunch",
                    "description": "Suppe",
                    "kcal": 300,
                    "logged_time_known": "nein",
                }
            )

        self.assertEqual(raised.exception.status, 400)

    def test_update_and_correction_can_change_time_knowledge(self) -> None:
        entry = self.log_full_macros()

        updated = self.service.update_meal(entry["id"], {"logged_time_known": False})
        self.assertIs(updated["logged_time_known"], False)
        self.assertEqual(updated["meal_type"], "breakfast")
        self.assertEqual(updated["logged_at"], "2026-09-24T12:00:00")

        corrected = self.service.correct_meal(
            entry["id"],
            {"logged_time_known": True, "logged_at": "2026-09-24T07:45:00"},
        )
        self.assertIs(corrected["logged_time_known"], True)
        self.assertEqual(corrected["logged_at"], "2026-09-24T07:45:00")

    def test_naming_a_time_makes_an_unknown_time_known(self) -> None:
        entry = self.service.log_meal(
            {
                "meal_date": "2026-09-24",
                "meal_type": "snack",
                "logged_time_known": False,
                "description": "Riegel",
                "kcal": 200,
            }
        )
        self.assertIs(entry["logged_time_known"], False)

        corrected = self.service.correct_meal(entry["id"], {"meal_time": "16:30"})
        self.assertIs(corrected["logged_time_known"], True)
        self.assertEqual(corrected["logged_at"], "2026-09-24T16:30")

        unknown = self.service.update_meal(entry["id"], {"logged_time_known": False})
        updated = self.service.update_meal(
            unknown["id"], {"logged_at": "2026-09-24T17:00:00"}
        )
        self.assertIs(updated["logged_time_known"], True)
        self.assertEqual(updated["logged_at"], "2026-09-24T17:00:00")

    def test_partial_macros_keep_daily_totals_unknown_but_expose_known_sums(
        self,
    ) -> None:
        self.log_full_macros()
        self.log_without_macros()

        summary = self.service.get_day_summary("2026-09-24")

        self.assertEqual(summary["total_kcal"], 600)
        self.assertEqual(summary["entry_count"], 2)
        self.assertIsNone(summary["total_carbs_g"])
        self.assertIsNone(summary["total_protein_g"])
        self.assertIsNone(summary["total_fat_g"])
        self.assertEqual(
            summary["known_macro_totals"],
            {"carbs_g": 60.0, "protein_g": 15.0, "fat_g": 10.0},
        )
        self.assertEqual(summary["entries_without_macros"], 1)

    def test_range_summary_matches_partial_day_totals(self) -> None:
        self.log_full_macros()
        self.log_without_macros()

        (day,) = self.service.get_range_summary("2026-09-24", "2026-09-24")

        self.assertIsNone(day["total_carbs_g"])
        self.assertEqual(day["known_macro_totals"]["carbs_g"], 60.0)
        self.assertEqual(day["entries_without_macros"], 1)

    def test_day_without_any_macros_has_no_macro_total(self) -> None:
        self.log_without_macros()

        summary = self.service.get_day_summary("2026-09-24")

        self.assertIsNone(summary["total_carbs_g"])
        self.assertIsNone(summary["total_protein_g"])
        self.assertIsNone(summary["total_fat_g"])
        self.assertEqual(
            summary["known_macro_totals"],
            {"carbs_g": None, "protein_g": None, "fat_g": None},
        )
        self.assertEqual(summary["entries_without_macros"], 1)

    def test_approval_withholds_partial_macros_but_keeps_kcal(self) -> None:
        self.log_full_macros()
        self.log_without_macros()

        item = nutrition_approval_item(self.service.get_sync_snapshot("2026-09-24"))

        self.assertEqual(item["total_kcal"], 600)
        self.assertIsNone(item["total_carbs_g"])
        self.assertIsNone(item["total_protein_g"])
        self.assertIsNone(item["total_fat_g"])

    def test_sync_never_writes_partial_macros_and_keeps_day_pending(self) -> None:
        self.log_full_macros()
        self.log_without_macros()
        sync, api = self.sync_service()

        result = sync.sync_day("2026-09-24")

        self.assertEqual(
            api.put.call_args.args[1], {"id": "2026-09-24", "kcalConsumed": 600}
        )
        self.assertTrue(result["pending"])
        self.assertEqual(self.service.list_unsynced_dates(), ["2026-09-24"])

    def test_complete_macros_are_written_and_day_is_synced(self) -> None:
        self.log_full_macros()
        sync, api = self.sync_service()

        result = sync.sync_day("2026-09-24")

        self.assertEqual(
            api.put.call_args.args[1],
            {
                "id": "2026-09-24",
                "kcalConsumed": 400,
                "carbs": 60.0,
                "protein": 15.0,
                "fat": 10.0,
            },
        )
        self.assertFalse(result["pending"])


if __name__ == "__main__":
    unittest.main()
