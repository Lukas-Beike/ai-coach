import copy
import unittest
from datetime import date, timedelta

from backend.performance.daily_health import (
    GARMIN_DAILY_HEALTH_FIELDS,
    garmin_daily_expenditure,
    garmin_daily_health_by_date,
    garmin_daily_health_metrics,
)


class GarminDailyHealthTests(unittest.TestCase):
    def test_daily_expenditure_keeps_components_total_provenance_and_freshness(self):
        snapshot = {
            "daily_stats": [
                {
                    "calendarDate": "2026-08-31",
                    "activeKilocalories": 0,
                    "bmrKilocalories": 1420,
                    "totalKilocalories": 1420,
                }
            ],
            "source_freshness": {
                "daily_stats": {
                    "freshness": "partial",
                    "fetched_at": "2026-09-01T08:00:00Z",
                }
            },
        }

        result = garmin_daily_expenditure(snapshot, "2026-08-31", date(2026, 9, 1))

        self.assertEqual(result["active_kcal"], 0)
        self.assertEqual(result["resting_kcal"], 1420)
        self.assertEqual(result["total_kcal"], 1420)
        self.assertEqual(result["source"], "Garmin Connect")
        self.assertEqual(result["measured_date"], "2026-08-31")
        self.assertEqual(result["freshness"], "partial")
        self.assertEqual(result["fetched_at"], "2026-09-01T08:00:00Z")
        self.assertEqual(result["measurement_age_days"], 1)
        self.assertFalse(result["provisional"])
        self.assertEqual(result["status"], "measured")
        self.assertIsNone(result["synced_at"])

    def test_daily_expenditure_does_not_invent_a_total_or_reuse_another_date(self):
        snapshot = {
            "daily_stats": [
                {
                    "date": "2026-08-30",
                    "activeCalories": 900,
                    "restingCalories": 1500,
                }
            ]
        }

        result = garmin_daily_expenditure(snapshot, "2026-08-31", date(2026, 8, 31))

        self.assertEqual(result["active_kcal"], None)
        self.assertEqual(result["resting_kcal"], None)
        self.assertEqual(result["total_kcal"], None)
        self.assertIsNone(result["source"])
        self.assertIsNone(result["measured_date"])
        self.assertEqual(result["freshness"], "unknown")
        self.assertTrue(result["provisional"])
        self.assertEqual(result["status"], "unavailable")

        prior_day = garmin_daily_expenditure(snapshot, "2026-08-31", date(2026, 9, 1))
        self.assertFalse(prior_day["provisional"])
        self.assertEqual(prior_day["status"], "unavailable")

    def test_daily_expenditure_rejects_negative_and_nonfinite_values_but_keeps_zero(
        self,
    ):
        result = garmin_daily_expenditure(
            {
                "daily_stats": [
                    {
                        "date": "2026-08-31",
                        "activeKilocalories": 0,
                        "bmrKilocalories": -1500,
                        "totalKilocalories": "inf",
                    }
                ]
            },
            "2026-08-31",
            date(2026, 9, 1),
        )

        self.assertEqual(result["active_kcal"], 0)
        self.assertIsNone(result["resting_kcal"])
        self.assertIsNone(result["total_kcal"])
        self.assertEqual(result["status"], "measured")

    def test_daily_expenditure_ignores_malformed_snapshots_and_future_records(self):
        for snapshot in (
            {"daily_stats": None, "source_freshness": []},
            {
                "daily_stats": [
                    {
                        "date": "2026-09-02",
                        "activeKilocalories": 500,
                        "totalKilocalories": 2000,
                    }
                ]
            },
        ):
            with self.subTest(snapshot=snapshot):
                result = garmin_daily_expenditure(
                    snapshot, "2026-09-02", date(2026, 9, 1)
                )
                self.assertIsNone(result["active_kcal"])
                self.assertIsNone(result["total_kcal"])
                self.assertIsNone(result["measured_date"])
                self.assertEqual(result["status"], "unavailable")

    def test_daily_expenditure_exposes_components_without_summing_them(self):
        result = garmin_daily_expenditure(
            {
                "daily_stats": [
                    {
                        "date": "2026-08-31",
                        "active_calories": 500,
                        "resting_calories": 1500,
                    }
                ]
            },
            "2026-08-31",
            date(2026, 8, 31),
        )

        self.assertEqual(result["active_kcal"], 500)
        self.assertEqual(result["resting_kcal"], 1500)
        self.assertIsNone(result["total_kcal"])

    def test_nested_records_aliases_and_same_date_merge(self):
        snapshot = {
            "daily_stats": {
                "records": [
                    {
                        "date": "2026-08-30",
                        "totalSteps": 1000,
                        "totalCalories": 200.25,
                    },
                    {
                        "date": "2026-08-30",
                        "steps": 3000,
                        "floorsAscended": 4.4,
                        "calories": 250.5,
                    },
                ]
            }
        }
        self.assertEqual(
            garmin_daily_health_by_date(snapshot),
            {
                "2026-08-30": {
                    "steps": 1000,
                    "calories": 200.25,
                    "floors": 4,
                    "source": "Garmin Connect",
                }
            },
        )

    def test_first_present_invalid_value_does_not_fallback(self):
        snapshot = {
            "daily_stats": [
                {
                    "date": "2026-08-30",
                    "totalSteps": "invalid",
                    "steps": 3000,
                    "floors": "5,5",
                    "totalCalories": "250,25",
                }
            ]
        }
        self.assertEqual(
            garmin_daily_health_by_date(snapshot),
            {
                "2026-08-30": {
                    "floors": 6,
                    "calories": 250.25,
                    "source": "Garmin Connect",
                }
            },
        )

    def test_recovery_list_limit_is_respected(self):
        records = [
            {"date": f"2026-08-{index:02}", "steps": index} for index in range(1, 32)
        ]
        snapshot = {"daily_stats": records}
        health = garmin_daily_health_by_date(snapshot)
        self.assertEqual(len(health), 31)
        records = [
            {
                "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                "steps": index,
            }
            for index in range(501)
        ]
        health = garmin_daily_health_by_date({"daily_stats": records})
        self.assertEqual(health["2027-05-15"]["steps"], 499)

    def test_window_boundaries_rounding_and_missing_values(self):
        snapshot = {
            "daily_stats": [
                {"date": "2026-08-29", "totalSteps": 100, "calories": 1.11},
                {
                    "date": "2026-08-30",
                    "totalSteps": 101,
                    "floors": 2,
                    "calories": 1.12,
                },
                {
                    "date": "2026-08-31",
                    "totalSteps": 102,
                    "floors": 3,
                    "calories": 1.13,
                },
                {"date": "2026-09-01", "totalSteps": 999, "floors": 9, "calories": 99},
            ],
            "source_freshness": {
                "daily_stats": {
                    "freshness": "fresh",
                    "observed_at": "2026-08-29",
                }
            },
        }
        result = garmin_daily_health_metrics(
            snapshot, 2, date(2026, 8, 31), date(2026, 9, 2)
        )
        self.assertEqual(result["steps_7d"]["value"], 102)
        self.assertEqual(result["floors_7d"]["value"], 2)
        self.assertEqual(result["calories_7d"]["value"], 1.12)
        self.assertEqual(result["steps_7d"]["measurement_age_days"], 4)
        self.assertEqual(result["steps_7d"]["measurement_status"], "earlier")

    def test_freshness_projection_current_and_stale(self):
        snapshot = {
            "daily_stats": [{"date": "2026-08-31", "steps": 100}],
            "source_freshness": {
                "daily_stats": {
                    "freshness": "stale",
                    "fetched_at": "2026-09-02T08:00:00Z",
                    "observed_at": "2026-08-31",
                }
            },
        }
        result = garmin_daily_health_metrics(
            snapshot, 1, date(2026, 8, 31), date(2026, 9, 1)
        )
        self.assertEqual(result["steps_7d"]["freshness"], "stale")
        self.assertIn("Letzter guter Wert", result["steps_7d"]["note"])
        snapshot["source_freshness"]["daily_stats"]["freshness"] = "fresh"
        result = garmin_daily_health_metrics(
            snapshot, 1, date(2026, 8, 31), date(2026, 8, 31)
        )
        self.assertEqual(result["steps_7d"]["freshness"], "fresh")
        self.assertEqual(result["steps_7d"]["measurement_status"], "today")

    def test_missing_values_keep_metric_keys_and_input_is_unchanged(self):
        snapshot = {"daily_stats": [{"date": "2026-08-31", "unknown": 1}]}
        before = copy.deepcopy(snapshot)
        result = garmin_daily_health_metrics(
            snapshot, 7, date(2026, 8, 31), date(2026, 8, 31)
        )
        self.assertEqual(set(result), {"steps_7d", "floors_7d", "calories_7d"})
        self.assertTrue(all(item["value"] is None for item in result.values()))
        self.assertTrue(all(item["source"] is None for item in result.values()))
        self.assertEqual(snapshot, before)
        self.assertEqual(
            GARMIN_DAILY_HEALTH_FIELDS["steps"],
            ("totalSteps", "total_steps", "steps", "stepCount", "step_count"),
        )


if __name__ == "__main__":
    unittest.main()
