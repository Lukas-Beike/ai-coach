import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path

from nutrition_service_support import build_nutrition_services

from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema


class NutritionGarminExpenditureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        manager = DatabaseManager(
            Path(self.temp_dir.name) / "nutrition.db", sqlite3, row_factory=sqlite3.Row
        )
        self.manager = manager
        with manager.unit_of_work() as db:
            initialize_schema(db)
        self.fixed_now = "2026-09-24T12:00:00+00:00"
        self.service, _ = build_nutrition_services(
            manager,
            threading.Lock(),
            lambda: self.fixed_now,
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_day_summary_includes_persisted_garmin_expenditure(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                (
                    "garmin_snapshot",
                    '{"synced_at":"2026-09-24T08:00:00Z","daily_stats":[{"date":"2026-09-24","activeKilocalories":600,"bmrKilocalories":1500,"totalKilocalories":2100}],"source_freshness":{"daily_stats":{"freshness":"current","fetched_at":"2026-09-24T08:00:00Z"}}}',
                    self.fixed_now,
                ),
            )

        expenditure = self.service.get_day_summary("2026-09-24")["energy_expenditure"]

        self.assertEqual(expenditure["active_kcal"], 600)
        self.assertEqual(expenditure["resting_kcal"], 1500)
        self.assertEqual(expenditure["total_kcal"], 2100)
        self.assertEqual(expenditure["source"], "Garmin Connect")
        self.assertEqual(expenditure["measured_date"], "2026-09-24")
        self.assertEqual(expenditure["freshness"], "current")
        self.assertEqual(expenditure["synced_at"], "2026-09-24T08:00:00Z")
        self.assertTrue(expenditure["provisional"])
        self.assertEqual(expenditure["status"], "measured")

    def test_malformed_garmin_snapshot_leaves_local_day_summary_available(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                ("garmin_snapshot", "not-json", self.fixed_now),
            )

        summary = self.service.get_day_summary("2026-09-24")

        self.assertEqual(summary["date"], "2026-09-24")
        self.assertEqual(summary["energy_expenditure"]["status"], "unavailable")
        self.assertTrue(summary["energy_expenditure"]["provisional"])
        self.assertIsNone(summary["energy_expenditure"]["total_kcal"])


if __name__ == "__main__":
    unittest.main()
