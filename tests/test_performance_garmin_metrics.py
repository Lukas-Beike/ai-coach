import copy
import unittest
from datetime import date

from backend.performance.garmin_metrics import (
    GARMIN_PERFORMANCE_SOURCE,
    garmin_bounded_metric,
    garmin_duration_seconds,
    garmin_performance_context,
    garmin_performance_metrics,
    garmin_profile_max_hr,
)

CURRENT_DATE = date(2026, 9, 7)


class GarminMetricHelperTests(unittest.TestCase):
    def test_duration_variants_and_bounds(self):
        self.assertEqual(garmin_duration_seconds("01:42:30"), 6150)
        self.assertEqual(garmin_duration_seconds("42:30"), 2550)
        self.assertEqual(
            garmin_duration_seconds({"racePredictionTime": "00:10:00"}), 600
        )
        self.assertEqual(garmin_duration_seconds(131000), 131)
        self.assertIsNone(garmin_duration_seconds("01:02:03:04"))
        self.assertIsNone(garmin_duration_seconds("00:00"))
        self.assertIsNone(garmin_duration_seconds(float("nan")))

        self.assertEqual(garmin_bounded_metric("302", 50, 700), 302)
        self.assertEqual(garmin_bounded_metric(50, 50, 700), 50)
        self.assertEqual(garmin_bounded_metric(700, 50, 700), 700)
        self.assertIsNone(garmin_bounded_metric(49, 50, 700))
        self.assertIsNone(garmin_bounded_metric(float("inf"), 50, 700))

    def test_profile_max_hr_uses_nested_sport_categories(self):
        zones = [
            {"sport": "cycling", "maxHeartRateUsed": 181},
            {"sportType": "RUN", "maxHeartRate": 194},
            {"activityType": "DEFAULT", "maxHR": 186},
            {"nested": [{"sport": "cycling", "maxHeartRateUsed": 188}]},
        ]
        self.assertEqual(
            garmin_profile_max_hr({"heart_rate_zones": zones}),
            {"cycling": 188, "running": 194, "generic": 186},
        )


class GarminPerformanceMetricTests(unittest.TestCase):
    def test_context_projects_normalized_metrics_without_raw_payload(self):
        result = garmin_performance_context(
            {
                "weight": {"calendarDate": "2026-09-07", "weight": 72},
                "cycling_ftp": {"functionalThresholdPower": 302},
                "race_predictions": {"5k": 1320},
            },
            CURRENT_DATE,
        )

        self.assertEqual(result["source"], GARMIN_PERFORMANCE_SOURCE)
        self.assertEqual(result["weight"]["value"], 72)
        self.assertEqual(result["thresholds"]["cycling_ftp_watts"]["value"], 302)
        self.assertEqual(result["estimated_run_times"]["5k_seconds"]["value"], 1320)
        self.assertNotIn("race_predictions", result)

    def test_vo2_race_variants_and_latest_values(self):
        snapshot = {
            "max_metrics": [
                {"generic": {"vo2MaxValue": 51}},
                {"generic": {"vo2MaxValue": 55}},
                {"running": {"vo2MaxPreciseValue": 57.4}},
                {"cycling": {"vo2MaxValue": 61}},
            ],
            "race_predictions": {
                "racePredictions": [
                    {"raceDistance": "5K", "raceTime": 1310},
                    {"raceDistance": "5K", "raceTime": 1400},
                    {"raceDistance": "halfMarathon", "raceTime": "01:42:30"},
                ],
                "10k": {"predictedTime": 2740},
                "marathon": {"racePredictionTime": 2_400_000},
            },
        }
        result = garmin_performance_metrics(snapshot, CURRENT_DATE)

        self.assertEqual(result["cycling_vo2max_ml_kg_min"]["value"], 61)
        self.assertEqual(result["running_vo2max_ml_kg_min"]["value"], 57.4)
        self.assertEqual(result["run_5k_seconds"]["value"], 1310)
        self.assertEqual(result["run_10k_seconds"]["value"], 2740)
        self.assertEqual(result["run_half_marathon_seconds"]["value"], 6150)
        self.assertEqual(result["run_marathon_seconds"]["value"], 2400)
        self.assertEqual(result["run_5k_seconds"]["source"], GARMIN_PERFORMANCE_SOURCE)
        self.assertEqual(
            result["running_vo2max_ml_kg_min"]["source"], GARMIN_PERFORMANCE_SOURCE
        )

    def test_threshold_aliases_speed_scaling_and_bounds(self):
        cases = (
            ("speedInMetersPerSecond", 3.8, 263),
            ("thresholdPace", "4:27", 267),
            ("speed", 0.35833233, 280),
        )
        for key, value, expected in cases:
            with self.subTest(key=key):
                result = garmin_performance_metrics(
                    {"running_threshold": {key: value}}, CURRENT_DATE
                )
                self.assertEqual(
                    result["run_threshold_pace_seconds_per_km"]["value"], expected
                )

        result = garmin_performance_metrics(
            {
                "cycling_ftp": {"functionalThresholdPower": 302},
                "running_threshold": {
                    "speed_and_heart_rate": {
                        "speed": 3.8,
                        "heartRate": 176,
                        "heartRateCycling": 169,
                    },
                    "power": {"functionalThresholdPower": 328},
                },
            },
            CURRENT_DATE,
        )
        self.assertEqual(result["cycling_ftp_watts"]["value"], 302)
        self.assertEqual(result["run_threshold_watts"]["value"], 328)
        self.assertEqual(result["run_threshold_hr_bpm"]["value"], 176)
        self.assertEqual(result["bike_threshold_hr_bpm"]["value"], 169)

        invalid = garmin_performance_metrics(
            {"cycling_ftp": 49, "running_threshold": {"speed": 10}}, CURRENT_DATE
        )
        self.assertIsNone(invalid["cycling_ftp_watts"]["value"])
        self.assertIsNone(invalid["run_threshold_pace_seconds_per_km"]["value"])

    def test_profile_stored_activity_max_hr_priority_and_observed_at(self):
        profile = garmin_performance_metrics(
            {
                "heart_rate_zones": [{"sport": "DEFAULT", "maxHeartRateUsed": 186}],
                "sport_max_hr": {"cycling": 178, "running": 181},
                "activities": [
                    {"activityType": "cycling", "maxHR": 178},
                    {"activityType": "running", "maxHeartRate": 181},
                ],
                "source_freshness": {
                    "heart_rate_zones": {
                        "freshness": "current",
                        "observed_at": "2026-09-06",
                        "fetched_at": "2026-09-07T08:00:00Z",
                    }
                },
            },
            CURRENT_DATE,
        )
        self.assertEqual(profile["cycling_max_hr_bpm"]["value"], 186)
        self.assertEqual(profile["running_max_hr_bpm"]["value"], 186)
        self.assertIn(
            "Garmin Connect Herzfrequenzzonen", profile["cycling_max_hr_bpm"]["note"]
        )
        self.assertEqual(profile["cycling_max_hr_bpm"]["measurement_age_days"], 1)

        activity_snapshot = {
            "sport_max_hr": {"cycling": 200, "running": 205},
            "activities": [
                {
                    "activityType": "cycling",
                    "maxHR": 190,
                    "startTimeLocal": "2026-09-01T10:00:00",
                },
                {
                    "activityType": "running",
                    "maxHR": 194,
                    "startTimeLocal": "2026-09-02T10:00:00",
                },
            ],
            "source_freshness": {
                "activities": {
                    "freshness": "stale",
                    "observed_at": "2026-09-07",
                    "fetched_at": "2026-09-07T11:00:00Z",
                }
            },
        }
        stored = garmin_performance_metrics(activity_snapshot, CURRENT_DATE)
        self.assertEqual(stored["cycling_max_hr_bpm"]["value"], 200)
        self.assertEqual(stored["running_max_hr_bpm"]["value"], 205)
        self.assertIsNone(stored["cycling_max_hr_bpm"]["observed_at"])
        self.assertIn("Letzter guter Wert", stored["cycling_max_hr_bpm"]["note"])

        del activity_snapshot["sport_max_hr"]
        activity = garmin_performance_metrics(activity_snapshot, CURRENT_DATE)
        self.assertEqual(activity["cycling_max_hr_bpm"]["value"], 190)
        self.assertEqual(activity["cycling_max_hr_bpm"]["observed_at"], "2026-09-01")
        self.assertEqual(activity["cycling_max_hr_bpm"]["measurement_age_days"], 6)
        self.assertIn("6 Tage alt", activity["cycling_max_hr_bpm"]["note"])

    def test_weight_freshness_and_input_nonmutation(self):
        snapshot = {
            "weight": {
                "dailyWeightSummaries": [
                    {"summaryDate": "2026-09-06", "latestWeight": {"weight": 73500}},
                    {"summaryDate": "2026-09-07", "latestWeight": {"weight": 72800}},
                ]
            },
            "source_freshness": {
                "weight": {
                    "freshness": "partial",
                    "observed_at": "2026-09-06",
                    "fetched_at": "2026-09-07T12:00:00Z",
                }
            },
        }
        original = copy.deepcopy(snapshot)
        result = garmin_performance_metrics(snapshot, CURRENT_DATE)

        self.assertEqual(result["weight_kg"]["value"], 72.8)
        self.assertEqual(result["weight_kg"]["freshness"], "partial")
        self.assertEqual(result["weight_kg"]["fetched_at"], "2026-09-07T12:00:00Z")
        self.assertEqual(result["weight_kg"]["measurement_age_days"], 1)
        self.assertIn("Quelle nur teilweise aktualisiert", result["weight_kg"]["note"])
        self.assertEqual(snapshot, original)

    def test_current_stale_and_future_freshness_states(self):
        result = garmin_performance_metrics(
            {
                "cycling_ftp": {"functionalThresholdPower": 300},
                "running_threshold": {"power": {"power": 320}},
                "source_freshness": {
                    "cycling_ftp": {
                        "freshness": "current",
                        "observed_at": "2026-09-07",
                    },
                    "running_threshold": {
                        "freshness": "stale",
                        "observed_at": "2026-09-08",
                    },
                },
            },
            CURRENT_DATE,
        )
        self.assertEqual(result["cycling_ftp_watts"]["freshness"], "current")
        self.assertEqual(result["cycling_ftp_watts"]["measurement_status"], "today")
        self.assertEqual(result["run_threshold_watts"]["freshness"], "stale")
        self.assertEqual(result["run_threshold_watts"]["measurement_status"], "future")
        self.assertEqual(result["run_threshold_watts"]["measurement_age_days"], -1)
        self.assertIn("Letzter guter Wert", result["run_threshold_watts"]["note"])

    def test_current_date_is_required(self):
        with self.assertRaises(TypeError):
            garmin_performance_metrics({})  # type: ignore[call-arg]


if __name__ == "__main__":
    unittest.main()
