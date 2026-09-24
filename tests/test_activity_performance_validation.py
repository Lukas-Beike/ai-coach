import copy
import unittest

from backend.performance.activity_validation import (
    activity_direct_estimates,
    activity_intensity,
    activity_pace_seconds_per_km,
    activity_performance_validation,
    activity_sport,
    bounded_activity_metric,
    bounded_performance_metric,
    latest_activity_for_validation,
)


class ActivityPerformanceValidationTests(unittest.TestCase):
    def test_running_activity_projects_pace_evidence_and_provider_comparison(self):
        comparison = {"average": 260, "direction": "up"}
        metrics = {
            "running_vo2max_ml_kg_min": {
                "value": 55,
                "unit": "ml/kg/min",
                "source": "Garmin",
                "observed_at": "2026-09-15",
            },
            "run_threshold_pace_seconds_per_km": {
                "value": 250,
                "unit": "s/km",
                "source": "Intervals.icu",
            },
        }
        result = activity_performance_validation(
            [
                {"id": "old", "type": "Run", "start_date_local": "2026-09-14T08:00:00"},
                {
                    "id": "run-b",
                    "type": "Run",
                    "name": "Tempo",
                    "start_date_local": "2026-09-15T08:00:00",
                    "moving_time": 3600,
                    "average_speed": 3.2,
                    "average_heartrate": 166,
                },
                {"id": "no-date", "type": "Run"},
            ],
            metrics,
            {
                "running_vo2max_ml_kg_min_30d": comparison,
                "run_threshold_pace_seconds_per_km_30d": {"average": 255},
            },
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["activity"]["activity_id"], "run-b")
        self.assertEqual(result["activity"]["sport"], "Laufen")
        self.assertEqual(result["activity"]["pace_seconds_per_km"], 312)
        self.assertEqual(result["activity"]["average_heart_rate_bpm"], 166)
        vo2 = result["provider_references"][0]
        self.assertEqual(vo2["source"], "Garmin")
        self.assertEqual(vo2["observed_at"], "2026-09-15")
        self.assertIs(vo2["historical_comparison"], comparison)

    def test_cycling_activity_adds_plausible_ftp_ratio_and_keeps_sources(self):
        result = activity_performance_validation(
            [
                {
                    "id": "ride",
                    "type": "Ride",
                    "start_date_local": "2026-09-15T08:00:00",
                    "moving_time": 3600,
                    "average_watts": 200,
                    "normalized_power": 270,
                    "icu_intensity": 0.9,
                    "icu_ftp": 300,
                }
            ],
            {
                "cycling_ftp_watts": {
                    "value": 300,
                    "unit": "W",
                    "source": "Intervals.icu",
                    "observed_at": "now",
                },
                "cycling_eftp_watts": {
                    "value": 290,
                    "unit": "W",
                    "source": "Intervals.icu",
                },
            },
            {},
        )

        self.assertEqual(result["activity"]["sport"], "Radfahren")
        self.assertEqual(result["activity"]["intensity"], 90)
        self.assertEqual(result["activity"]["power_as_percent_of_current_ftp"], 90.0)
        self.assertEqual(
            result["direct_activity_estimates"], {"activity_configured_ftp_watts": 300}
        )
        self.assertEqual(
            [reference["metric"] for reference in result["provider_references"]],
            ["cycling_vo2max_ml_kg_min", "cycling_ftp_watts", "cycling_eftp_watts"],
        )

    def test_unknown_sport_and_no_activity_are_explicit(self):
        unknown = activity_performance_validation(
            [{"id": "hike", "type": "Hike", "start_date_local": "2026-09-15T08:00:00"}],
            {"running_vo2max_ml_kg_min": {"value": 55}},
            {},
        )
        self.assertEqual(unknown["activity"]["sport"], "Hike")
        self.assertEqual(unknown["provider_references"], [])
        self.assertEqual(
            activity_performance_validation([], {}, {}),
            {
                "available": False,
                "status": "no_completed_activity",
                "scope": "Keine abgeschlossene Einheit mit verwertbarem Zeitstempel vorhanden.",
            },
        )
        self.assertEqual(activity_sport({"type": "Swim"}), "Schwimmen")
        self.assertEqual(activity_sport({"type": "Strength"}), "Krafttraining")

    def test_bounds_reject_nested_and_oversized_values(self):
        self.assertEqual(bounded_activity_metric(10, 1, 10), 10)
        self.assertIsNone(bounded_activity_metric({"value": 10}, 1, 10))
        self.assertIsNone(bounded_activity_metric([10], 1, 10))
        self.assertIsNone(bounded_activity_metric("1" * 33, 1, 10))
        self.assertEqual(activity_intensity(0.9), 90)
        self.assertEqual(activity_intensity(2), 200)
        self.assertEqual(activity_intensity(3), 3)
        self.assertIsNone(activity_intensity(999))
        self.assertEqual(bounded_performance_metric("cycling_ftp_watts", 300), 300)
        self.assertIsNone(
            bounded_performance_metric("cycling_ftp_watts", {"value": 300})
        )
        self.assertIsNone(activity_pace_seconds_per_km({"pace": [300]}))
        self.assertEqual(
            activity_direct_estimates(
                {"ftp": 300, "eFTP": [300], "vo2max": {"value": 60}}
            ),
            {"activity_ftp_watts": 300},
        )

    def test_latest_timestamp_uses_id_tiebreak_and_inputs_are_not_mutated(self):
        activities = [
            {
                "id": "same-a",
                "type": "Ride",
                "start_date_local": "2026-09-15T08:00:00",
                "normalized_power": 250,
            },
            {
                "id": "same-b",
                "type": "Ride",
                "start_date_local": "2026-09-15T08:00:00",
                "normalized_power": 270,
            },
        ]
        metrics = {"cycling_ftp_watts": {"value": 300, "source": "Intervals.icu"}}
        comparisons = {"cycling_ftp_watts_30d": {"average": 280}}
        before = copy.deepcopy((activities, metrics, comparisons))
        latest = latest_activity_for_validation(activities)
        result = activity_performance_validation(activities, metrics, comparisons)

        self.assertEqual(latest["id"], "same-b")
        self.assertEqual(result["activity"]["activity_id"], "same-b")
        self.assertEqual((activities, metrics, comparisons), before)
        self.assertIn("power_as_percent_of_current_ftp", result["activity"])


if __name__ == "__main__":
    unittest.main()
