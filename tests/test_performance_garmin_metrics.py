import copy
import unittest
from datetime import date

from canonical_consumer_cases import MAX_METRICS_DAILY

from backend.performance.freshness import GarminSyncStatus
from backend.performance.garmin_canonical import GarminCanonicalMetrics
from backend.performance.garmin_metrics import (
    GARMIN_PERFORMANCE_SOURCE,
    garmin_performance_context,
    garmin_performance_metrics,
)
from backend.sync.garmin_performance_history import current_garmin_metrics

CURRENT_DATE = date(2026, 9, 7)


def _race_5k_seconds(value):
    result = current_garmin_metrics({"race_predictions": {"5k": value}}, CURRENT_DATE)
    return result["run_5k_seconds"]["value"]


class GarminMetricHelperTests(unittest.TestCase):
    def test_duration_variants_and_bounds(self):
        cases = (
            ("01:42:30", 6150),
            ("42:30", 2550),
            ({"racePredictionTime": "00:10:00"}, 600),
            (131000, 131),
            ("01:02:03:04", None),
            ("00:00", None),
            (float("nan"), None),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(_race_5k_seconds(value), expected)

    def test_non_ascii_or_overlong_colon_text_is_absent(self):
        self.assertEqual(_race_5k_seconds("25:30"), 1530)
        self.assertEqual(_race_5k_seconds(" 42:30 "), 2550)
        for text in ("²:30", "1" * 4301 + ":30"):
            with self.subTest(length=len(text)):
                self.assertIsNone(_race_5k_seconds(text))
                for key in ("speed", "thresholdPace"):
                    result = current_garmin_metrics(
                        {"running_threshold": {key: text}}, CURRENT_DATE
                    )
                    self.assertIsNone(
                        result["run_threshold_pace_seconds_per_km"]["value"]
                    )

    def test_profile_max_hr_uses_nested_sport_categories(self):
        zones = [
            {"sport": "cycling", "maxHeartRateUsed": 181},
            {"sportType": "RUN", "maxHeartRate": 194},
            {"activityType": "DEFAULT", "maxHR": 186},
            {"nested": [{"sport": "cycling", "maxHeartRateUsed": 188}]},
        ]
        result = current_garmin_metrics({"heart_rate_zones": zones}, CURRENT_DATE)
        self.assertEqual(result["cycling_max_hr_bpm"]["value"], 188)
        self.assertEqual(result["running_max_hr_bpm"]["value"], 194)


class GarminPerformanceMetricTests(unittest.TestCase):
    def test_context_projects_normalized_metrics_without_raw_payload(self):
        result = garmin_performance_context(
            GarminSyncStatus.from_state(
                {
                    "weight": {"calendarDate": "2026-09-07", "weight": 72},
                    "cycling_ftp": {"functionalThresholdPower": 302},
                    "race_predictions": {"5k": 1320},
                }
            ),
            CURRENT_DATE,
            GarminCanonicalMetrics(
                weight_kg=72,
                cycling_ftp_watts=302,
                race_predictions={"run_5k_seconds": 1320},
            ),
        )

        self.assertEqual(result["source"], GARMIN_PERFORMANCE_SOURCE)
        self.assertEqual(result["weight"]["value"], 72)
        self.assertEqual(result["thresholds"]["cycling_ftp_watts"]["value"], 302)
        self.assertEqual(result["estimated_run_times"]["5k_seconds"]["value"], 1320)
        self.assertNotIn("race_predictions", result)

    def test_vo2_race_variants_and_latest_values(self):
        snapshot = {
            "max_metrics": [
                {"generic": {"calendarDate": "2026-09-06", "vo2MaxValue": 51}},
                {"generic": {"calendarDate": "2026-09-07", "vo2MaxValue": 55}},
                {"running": {"calendarDate": "2026-09-07", "vo2MaxPreciseValue": 57.4}},
                {"cycling": {"calendarDate": "2026-09-07", "vo2MaxValue": 61}},
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
        result = current_garmin_metrics(snapshot, CURRENT_DATE)

        self.assertEqual(result["cycling_vo2max_ml_kg_min"]["value"], 61)
        self.assertEqual(
            result["running_vo2max_ml_kg_min"],
            {
                "value": 57.4,
                "unit": "ml/kg/min",
                "source": GARMIN_PERFORMANCE_SOURCE,
                "source_provider": "garmin",
                "note": "Garmin Connect max metrics",
                "freshness": "unknown",
                "fetched_at": None,
                "observed_at": "2026-09-07",
                "measurement_status": "today",
                "measurement_age_days": 0,
            },
        )
        self.assertEqual(result["run_5k_seconds"]["value"], 1310)
        self.assertEqual(result["run_10k_seconds"]["value"], 2740)
        self.assertEqual(result["run_half_marathon_seconds"]["value"], 6150)
        self.assertEqual(result["run_marathon_seconds"]["value"], 2400)
        self.assertEqual(result["run_5k_seconds"]["source"], GARMIN_PERFORMANCE_SOURCE)
        # The latest generic reading of a range payload is the running value.
        generic = {"max_metrics": snapshot["max_metrics"][:2]}
        self.assertEqual(
            current_garmin_metrics(generic, CURRENT_DATE)["running_vo2max_ml_kg_min"][
                "value"
            ],
            55,
        )

    def test_maxmet_daily_rows_date_each_vo2max_by_its_own_reading(self):
        # #2345: the recorded daily shape dates the sport objects, not the row; the
        # newest reading of each sport wins whatever the row order.
        rows = MAX_METRICS_DAILY
        for order in (rows, list(reversed(rows))):
            result = current_garmin_metrics({"max_metrics": order}, CURRENT_DATE)
            running = result["running_vo2max_ml_kg_min"]
            cycling = result["cycling_vo2max_ml_kg_min"]
            self.assertEqual(
                (running["value"], running["observed_at"]), (54.3, "2026-11-12")
            )
            self.assertEqual(
                (cycling["value"], cycling["observed_at"]), (58.6, "2026-11-11")
            )

    def test_canonical_vo2max_is_dated_by_each_sport_reading(self):
        # #2345: the canonical read dates each VO2max by its own reading.
        metrics = garmin_performance_metrics(
            GarminSyncStatus.from_state({}),
            date(2026, 11, 12),
            GarminCanonicalMetrics(
                cycling_vo2max=58.6,
                running_vo2max=54.3,
                cycling_vo2max_on=date(2026, 11, 11),
                running_vo2max_on=date(2026, 11, 12),
            ),
        )
        self.assertEqual(
            [
                (metrics[key]["value"], metrics[key]["observed_at"])
                for key in ("running_vo2max_ml_kg_min", "cycling_vo2max_ml_kg_min")
            ],
            [(54.3, "2026-11-12"), (58.6, "2026-11-11")],
        )

    def test_precise_vo2max_wins_over_its_rounded_twin(self):
        # Garmin sends both fields in one section; the precise one keeps its decimal (#2263).
        snapshot = {
            "max_metrics": [
                {
                    "generic": {
                        "calendarDate": "2026-09-07",
                        "vo2MaxPreciseValue": 54.3,
                        "vo2MaxValue": 54,
                    },
                    "cycling": {
                        "calendarDate": "2026-09-07",
                        "vo2MaxPreciseValue": 58.6,
                        "VO2MaxValue": 58,
                    },
                }
            ]
        }
        result = current_garmin_metrics(snapshot, CURRENT_DATE)

        self.assertEqual(result["running_vo2max_ml_kg_min"]["value"], 54.3)
        self.assertEqual(result["cycling_vo2max_ml_kg_min"]["value"], 58.6)
        # A placeholder precise value is dropped like in the canonical mapping, not replaced.
        placeholder = current_garmin_metrics(
            {
                "max_metrics": {
                    "generic": {
                        "calendarDate": "2026-09-07",
                        "vo2MaxPreciseValue": 0.0,
                        "vo2MaxValue": 54,
                    }
                }
            },
            CURRENT_DATE,
        )
        self.assertIsNone(placeholder["running_vo2max_ml_kg_min"]["value"])

    def test_threshold_aliases_speed_scaling_and_bounds(self):
        # Garmin's scaled speed below 1 is multiplied by ten. The legacy flat
        # aliases are named deviations in test_garmin_health_parity (#2081).
        result = current_garmin_metrics(
            {"running_threshold": {"speed_and_heart_rate": {"speed": 0.35833233}}},
            CURRENT_DATE,
        )
        self.assertEqual(result["run_threshold_pace_seconds_per_km"]["value"], 279)
        self.assertEqual(
            result["run_threshold_pace_seconds_per_km"]["source"],
            GARMIN_PERFORMANCE_SOURCE,
        )

        result = current_garmin_metrics(
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

        invalid = current_garmin_metrics(
            {"cycling_ftp": 49, "running_threshold": {"speed": 10}}, CURRENT_DATE
        )
        self.assertIsNone(invalid["cycling_ftp_watts"]["value"])
        self.assertIsNone(invalid["run_threshold_pace_seconds_per_km"]["value"])

    def test_profile_max_hr_and_no_ingest_activity_maximum(self):
        profile = current_garmin_metrics(
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

        # The ingest-only history keeps no activity maximum (#1686); the
        # fallback is read from canonical activity records.
        activity_snapshot = {
            "sport_max_hr": {"cycling": 200, "running": 205},
            "activities": [{"activityType": "cycling", "maxHR": 190}],
        }
        activity = current_garmin_metrics(activity_snapshot, CURRENT_DATE)
        self.assertIsNone(activity["cycling_max_hr_bpm"]["value"])
        self.assertIsNone(activity["running_max_hr_bpm"]["value"])

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
        result = current_garmin_metrics(snapshot, CURRENT_DATE)

        self.assertEqual(result["weight_kg"]["value"], 72.8)
        self.assertEqual(result["weight_kg"]["source"], GARMIN_PERFORMANCE_SOURCE)
        self.assertEqual(result["weight_kg"]["freshness"], "partial")
        self.assertEqual(result["weight_kg"]["fetched_at"], "2026-09-07T12:00:00Z")
        self.assertEqual(result["weight_kg"]["measurement_age_days"], 1)
        self.assertIn("Quelle nur teilweise aktualisiert", result["weight_kg"]["note"])
        self.assertEqual(snapshot, original)

    def test_weight_metric_shape_source_note_and_empty_value(self):
        weight = current_garmin_metrics(
            {"weight": [{"date": "2026-08-30", "weightKg": 72}]}, CURRENT_DATE
        )["weight_kg"]
        self.assertEqual(
            {key: weight[key] for key in ("value", "unit", "source", "note")},
            {
                "value": 72.0,
                "unit": "kg",
                "source": "Garmin Connect",
                "note": "Garmin Connect Körpergewicht",
            },
        )
        empty = current_garmin_metrics({}, CURRENT_DATE)["weight_kg"]
        self.assertEqual(
            {key: empty[key] for key in ("value", "unit", "source", "note")},
            {"value": None, "unit": "kg", "source": None, "note": ""},
        )

    def test_current_stale_and_future_freshness_states(self):
        result = current_garmin_metrics(
            {
                "cycling_ftp": {"functionalThresholdPower": 300},
                "running_threshold": {"power": {"functionalThresholdPower": 320}},
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
            garmin_performance_metrics(GarminSyncStatus.from_state({}))  # type: ignore[call-arg]


if __name__ == "__main__":
    unittest.main()
