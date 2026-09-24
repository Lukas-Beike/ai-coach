import copy
import unittest
from datetime import date

from backend.performance.comparisons import (
    performance_comparisons,
    performance_trend_average,
)

TODAY = date(2026, 9, 7)
GARMIN_SOURCE = "Garmin Connect"


class PerformanceTrendAverageTests(unittest.TestCase):
    def test_garmin_weight_and_history_sources(self):
        garmin = {
            "weight": {
                "dailyWeightSummaries": [
                    {"summaryDate": "2026-09-01", "latestWeight": {"weight": 70_000}},
                    {"summaryDate": "2026-09-07", "latestWeight": {"weight": 72_000}},
                ]
            },
            "performance_history": [
                {"date": "2026-09-01", "metrics": {"cycling_ftp_watts": 280}},
                {"date": "2026-09-07", "metrics": {"cycling_ftp_watts": 300}},
            ],
        }
        metrics = {
            "weight_kg": {"source": GARMIN_SOURCE},
            "cycling_ftp_watts": {"source": GARMIN_SOURCE},
        }

        self.assertEqual(
            performance_trend_average({}, garmin, metrics, "weight_kg", 7, TODAY),
            71.0,
        )
        self.assertEqual(
            performance_trend_average(
                {}, garmin, metrics, "cycling_ftp_watts", 7, TODAY
            ),
            290.0,
        )

    def test_intervals_source_uses_wellness_trend_and_window(self):
        snapshot = {
            "recent_wellness": [
                {"id": "2026-09-01", "readiness": 70},
                {"id": "2026-09-07", "readiness": 80},
                {"id": "2026-08-31", "readiness": 99},
            ]
        }
        metrics = {"readiness": {"source": "Intervals.icu Wellness"}}

        self.assertEqual(
            performance_trend_average(snapshot, {}, metrics, "readiness", 7, TODAY),
            75.0,
        )
        self.assertIsNone(
            performance_trend_average(
                {"recent_wellness": []}, {}, metrics, "readiness", 7, TODAY
            )
        )


class PerformanceComparisonsTests(unittest.TestCase):
    def _inputs(self):
        metrics = {
            "cycling_eftp_watts": {"value": 309, "source": "Intervals.icu"},
            "weight_kg": {"value": 72, "source": GARMIN_SOURCE},
            "readiness": {"value": 80, "source": GARMIN_SOURCE},
            "cycling_ftp_watts": {"value": 300, "source": GARMIN_SOURCE},
            "bike_threshold_hr_bpm": {"value": 170, "source": GARMIN_SOURCE},
            "run_threshold_watts": {"value": 320, "source": GARMIN_SOURCE},
            "run_threshold_pace_seconds_per_km": {
                "value": 270,
                "source": GARMIN_SOURCE,
            },
            "run_zone2_pace_seconds_per_km": {"value": 360, "source": GARMIN_SOURCE},
            "run_threshold_hr_bpm": {"value": 175, "source": GARMIN_SOURCE},
            "cycling_vo2max_ml_kg_min": {"value": 60, "source": GARMIN_SOURCE},
            "running_vo2max_ml_kg_min": {"value": 58, "source": GARMIN_SOURCE},
            "run_5k_seconds": {"value": 1_300, "source": GARMIN_SOURCE},
            "run_10k_seconds": {"value": 2_700, "source": GARMIN_SOURCE},
            "run_half_marathon_seconds": {"value": 5_800, "source": GARMIN_SOURCE},
            "run_marathon_seconds": {"value": 12_000, "source": GARMIN_SOURCE},
        }
        history_metrics = {
            key: value
            for key, value in (
                ("weight_kg", 70),
                ("readiness", 65),
                ("cycling_ftp_watts", 280),
                ("bike_threshold_hr_bpm", 165),
                ("run_threshold_watts", 300),
                ("run_threshold_pace_seconds_per_km", 280),
                ("run_zone2_pace_seconds_per_km", 370),
                ("run_threshold_hr_bpm", 170),
                ("cycling_vo2max_ml_kg_min", 55),
                ("running_vo2max_ml_kg_min", 54),
                ("run_5k_seconds", 1_350),
                ("run_10k_seconds", 2_800),
                ("run_half_marathon_seconds", 5_900),
                ("run_marathon_seconds", 12_500),
            )
        }
        garmin = {
            "weight": {
                "dailyWeightSummaries": [
                    {"summaryDate": "2026-09-01", "latestWeight": {"weight": 70_000}},
                    {"summaryDate": "2026-09-07", "latestWeight": {"weight": 70_000}},
                ]
            },
            "performance_history": [
                {"date": "2026-09-01", "metrics": history_metrics},
            ],
        }
        wellness_rows = [
            {
                "id": "2026-09-01",
                "sleepSecs": 25_200,
                "readiness": 70,
                "restingHR": 60,
                "hrv": 50,
                "ctl": 65,
                "atl": 75,
                "tsb": -7,
                "sportInfo": [{"types": ["Ride"], "eFTP": 290}],
            },
            {
                "id": "2026-09-07",
                "sleepSecs": 25_200,
                "readiness": 70,
                "restingHR": 60,
                "hrv": 50,
                "ctl": 65,
                "atl": 75,
                "tsb": -8,
                "sportInfo": [{"types": ["Ride"], "eFTP": 290}],
            },
        ]
        snapshot = {"recent_wellness": wellness_rows}
        recovery = {
            "sleep_hours": 8,
            "sleep_average": 7,
            "readiness": 80,
            "readiness_source": GARMIN_SOURCE,
            "readiness_average": 70,
            "resting_hr": 55,
            "resting_hr_average": 60,
            "hrv": 60,
            "hrv_average": 50,
        }
        load_context = {
            "load": {"ctl": 70, "tsb": -5, "atl": 80},
            "last_7": {"training_load": 100, "duration_hours": 10},
            "previous_7": {"training_load": 90, "duration_hours": 8},
            "previous_30": {"training_load": 400, "duration_hours": 30},
            "actual_atl_current": 78,
            "actual_atl_average": 70,
        }
        activities = [
            {"start_date_local": "2026-09-07T08:00:00", "type": "Ride", "icu_eftp": 290}
        ]
        return (
            snapshot,
            garmin,
            metrics,
            recovery,
            load_context,
            wellness_rows,
            activities,
        )

    def test_comparisons_preserve_keys_units_labels_and_direction_flags(self):
        values = self._inputs()
        before = copy.deepcopy(values)
        result = performance_comparisons(*values, TODAY)

        self.assertEqual(result["sleep_hours"]["unit"], "h")
        self.assertEqual(result["sleep_hours"]["days"], 7)
        self.assertEqual(result["sleep_hours"]["color"], "good")
        self.assertEqual(result["restingHR"]["color"], "good")
        self.assertEqual(result["fatigue_atl"]["color"], "bad")
        self.assertEqual(result["weight_kg_30d"]["color"], "neutral")
        self.assertEqual(result["training_load_7d"]["label"], "vorherigen 7 Tagen")
        self.assertEqual(
            result["training_volume_7d"]["label"], "Schnitt der 30 Tage davor"
        )
        self.assertEqual(
            result["run_threshold_pace_seconds_per_km_30d"]["unit"], "s/km"
        )
        self.assertEqual(result["run_5k_seconds_30d"]["direction"], "down")
        self.assertEqual(result["run_5k_seconds_30d"]["color"], "good")
        self.assertEqual(result["cycling_eftp_30d"]["average"], 290.0)
        self.assertEqual(result["readiness_30d"]["days"], 30)
        self.assertEqual(values, before)

    def test_missing_values_return_none_without_mutation(self):
        values = self._inputs()
        values = list(values)
        values[2] = {"cycling_eftp_watts": {"value": None, "source": None}}
        values[3] = {
            "sleep_hours": None,
            "sleep_average": None,
            "readiness": None,
            "readiness_source": None,
            "readiness_average": None,
            "resting_hr": None,
            "resting_hr_average": None,
            "hrv": None,
            "hrv_average": None,
        }
        before = copy.deepcopy(values)
        result = performance_comparisons(*values, TODAY)

        self.assertIsNone(result["sleep_hours"])
        self.assertIsNone(result["readiness"])
        self.assertIsNone(result["cycling_eftp_30d"])
        self.assertEqual(values, before)


if __name__ == "__main__":
    unittest.main()
