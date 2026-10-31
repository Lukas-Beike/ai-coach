import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from canonical_daily_health_support import MappedDailyReader
from nutrition_service_support import build_nutrition_services

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter


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

    def store_garmin(self, payload: dict[str, Any]) -> None:
        payload = {"synced_at": "2026-09-24T08:00:00Z", **payload}
        writer = GarminSnapshotWriter(
            KeyValueRepository(lambda: self.fixed_now), lambda: UTC
        )
        with self.manager.unit_of_work() as db:
            writer.write(db, payload)

    def test_day_summary_includes_persisted_garmin_expenditure(self) -> None:
        self.store_garmin(
            {
                "daily_stats": [
                    {
                        "date": "2026-09-24",
                        "activeKilocalories": 600,
                        "bmrKilocalories": 1500,
                        "totalKilocalories": 2100,
                    }
                ],
                "source_freshness": {
                    "daily_stats": {
                        "freshness": "current",
                        "fetched_at": "2026-09-24T08:00:00Z",
                    }
                },
            }
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

    def test_day_and_week_read_measured_energy_from_observations(self) -> None:
        reader = MappedDailyReader(
            {
                "daily_stats": [
                    {"date": "2026-09-17", "totalKilocalories": 2000},
                    {"date": "2026-09-18", "totalKilocalories": 2100},
                    {
                        "date": "2026-09-24",
                        "totalKilocalories": 2100,
                        "activeKilocalories": 600,
                        "bmrKilocalories": 1500,
                    },
                ]
            }
        )
        service, _ = build_nutrition_services(
            self.manager,
            threading.Lock(),
            lambda: self.fixed_now,
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            observation_reader=lambda: reader,
        )
        # The stored rows keep only the sync status; every value is canonical.
        self.store_garmin(
            {
                "daily_stats": [{"date": "2026-09-24"}],
                "source_freshness": {"daily_stats": {"freshness": "current"}},
            }
        )

        day = service.get_day_summary("2026-09-24")["energy_expenditure"]
        week = service.get_week_summary()

        self.assertEqual(
            (day["total_kcal"], day["active_kcal"], day["resting_kcal"]),
            (2100, 600, 1500),
        )
        self.assertEqual(day["source"], "Garmin Connect")
        self.assertEqual(day["freshness"], "current")
        self.assertEqual(day["status"], "measured")
        self.assertEqual(
            [entry["energy_expenditure"]["total_kcal"] for entry in week["days"][:3]],
            [2000, 2100, None],
        )

    def test_today_projects_persisted_resting_reference_with_current_active_energy(
        self,
    ) -> None:
        today = {
            "date": "2026-09-24",
            "activeKilocalories": 436,
            "bmrKilocalories": 1659,
            "totalKilocalories": 2095,
        }
        self.store_garmin(
            {
                "daily_stats": [
                    today,
                    {"date": "2026-09-23", "bmrKilocalories": 2200},
                ],
                "source_freshness": {"daily_stats": {"freshness": "current"}},
                "provider_sync": {
                    "read_window": {
                        "start": "2026-09-17",
                        "end": "2026-09-24",
                    }
                },
            }
        )
        reader = MappedDailyReader(
            {
                "daily_stats": [
                    today,
                    {"date": "2026-09-23", "bmrKilocalories": 2200},
                ]
            }
        )
        service, _ = build_nutrition_services(
            self.manager,
            threading.Lock(),
            lambda: self.fixed_now,
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            observation_reader=lambda: reader,
        )

        energy = service.get_day_summary("2026-09-24")["energy_expenditure"]

        self.assertEqual(energy["projected_total_kcal"], 2636)
        self.assertEqual(energy["projection_resting_kcal"], 2200)
        self.assertEqual(energy["projection_reference_date"], "2026-09-23")
        self.assertEqual(energy["total_kcal"], 2095)
        self.assertEqual(energy["resting_kcal"], 1659)
        closed = service.get_day_summary("2026-09-23")["energy_expenditure"]
        self.assertIsNone(closed["projected_total_kcal"])

    def test_malformed_garmin_snapshot_leaves_local_day_summary_available(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                ("garmin_state", "not-json", self.fixed_now),
            )

        summary = self.service.get_day_summary("2026-09-24")

        self.assertEqual(summary["date"], "2026-09-24")
        self.assertEqual(summary["energy_expenditure"]["status"], "unavailable")
        self.assertTrue(summary["energy_expenditure"]["provisional"])
        self.assertIsNone(summary["energy_expenditure"]["total_kcal"])

    def test_targeted_nutrition_refresh_freshness_is_scoped_to_requested_day(
        self,
    ) -> None:
        self.store_garmin(
            {
                "daily_stats": [
                    {"calendarDate": "2026-09-23", "totalKilocalories": 2000},
                    {"calendarDate": "2026-09-24", "totalKilocalories": 2100},
                ],
                "source_freshness": {
                    "daily_stats": {"freshness": "current", "fetched_at": "older"}
                },
                "nutrition_refresh": {
                    "daily_stats": {
                        "2026-09-23": {
                            "freshness": "partial",
                            "fetched_at": "targeted-read",
                        }
                    }
                },
            }
        )

        requested = self.service.get_day_summary("2026-09-23")["energy_expenditure"]
        untouched = self.service.get_day_summary("2026-09-24")["energy_expenditure"]

        self.assertEqual(requested["freshness"], "partial")
        self.assertEqual(requested["fetched_at"], "targeted-read")
        self.assertEqual(untouched["freshness"], "current")
        self.assertEqual(untouched["fetched_at"], "older")

    def test_week_uses_closed_days_and_only_paired_values_for_balance(self) -> None:
        for day, kcal, carbs in [
            ("2026-09-17", 2200, 200),
            ("2026-09-18", 1800, None),
            ("2026-09-19", 1600, 100),
            ("2026-09-24", 9999, 999),
        ]:
            self.service.log_meal(
                {
                    "meal_date": day,
                    "description": "Synthetic meal",
                    "kcal": kcal,
                    "carbs_g": carbs,
                    "protein_g": 100,
                    "fat_g": 50,
                }
            )
        self.store_garmin(
            {
                "daily_stats": [
                    {"date": "2026-09-17", "totalKilocalories": 2000},
                    {"date": "2026-09-18", "totalKilocalories": 2100},
                    {"date": "2026-09-20", "totalKilocalories": 2300},
                    {
                        "date": "2026-09-19",
                        "activeKilocalories": 600,
                        "bmrKilocalories": 1500,
                    },
                    {"date": "2026-09-24", "totalKilocalories": 9999},
                ]
            }
        )
        week = self.service.get_week_summary()
        self.assertEqual(
            (week["start_date"], week["end_date"]), ("2026-09-17", "2026-09-23")
        )
        self.assertEqual(len(week["days"]), 7)
        self.assertEqual(week["balance_kcal"], -100)
        self.assertEqual(week["balance_days"], 2)
        self.assertEqual(week["averages"]["intake_kcal"], {"value": 1866.7, "days": 3})
        self.assertEqual(
            week["averages"]["expenditure_kcal"], {"value": 2133.3, "days": 3}
        )
        self.assertEqual(week["averages"]["carbs_g"], {"value": 150, "days": 2})
        self.assertIsNone(week["days"][2]["balance_kcal"])
        self.assertIsNone(week["days"][3]["intake_kcal"])
        self.assertEqual(
            week["days"][0]["energy_expenditure"]["source"], "Garmin Connect"
        )

    def test_history_periods_keep_closed_days_and_missing_values(self) -> None:
        for count in (14, 84):
            with self.subTest(days=count):
                summary = self.service.get_week_summary(count)
                self.assertEqual(len(summary["days"]), count)
                self.assertEqual(
                    summary["start_date"],
                    (datetime(2026, 9, 24, tzinfo=UTC) - timedelta(days=count))
                    .date()
                    .isoformat(),
                )
                self.assertEqual(summary["end_date"], "2026-09-23")
                self.assertIsNone(summary["balance_kcal"])
                self.assertEqual(summary["balance_days"], 0)
                self.assertTrue(
                    all(day["intake_kcal"] is None for day in summary["days"])
                )

    def test_history_rejects_unsupported_periods(self) -> None:
        from backend.errors import AppError

        invalid_periods: tuple[Any, ...] = (0, 15, 85, True, "14")
        for count in invalid_periods:
            with self.subTest(days=count), self.assertRaises(AppError):
                self.service.get_week_summary(count)

    def test_empty_week_does_not_invent_zero_intake_or_macros(self) -> None:
        week = self.service.get_week_summary()
        self.assertIsNone(week["balance_kcal"])
        self.assertEqual(week["balance_days"], 0)
        for metric in week["averages"].values():
            self.assertEqual(metric, {"value": None, "days": 0})


if __name__ == "__main__":
    unittest.main()
