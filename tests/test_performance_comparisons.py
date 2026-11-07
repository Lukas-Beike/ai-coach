import copy
import unittest
from datetime import date

from performance_day_support import garmin_metrics_from_payload

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
        history = garmin_metrics_from_payload(garmin).performance_history
        metrics = {
            "weight_kg": {"source": GARMIN_SOURCE},
            "cycling_ftp_watts": {"source": GARMIN_SOURCE},
        }

        self.assertEqual(
            performance_trend_average(
                metrics, "weight_kg", 7, TODAY, garmin_history=history
            ),
            71.0,
        )
        self.assertEqual(
            performance_trend_average(
                metrics, "cycling_ftp_watts", 7, TODAY, garmin_history=history
            ),
            290.0,
        )

    def test_a_non_garmin_source_has_no_trend_average(self):
        metrics = {"readiness": {"source": "Intervals.icu Wellness"}}
        history = {"readiness": {TODAY: 80.0}}

        self.assertIsNone(
            performance_trend_average(
                metrics, "readiness", 7, TODAY, garmin_history=history
            )
        )


class PerformanceComparisonsTests(unittest.TestCase):
    def _history(self):
        history_metrics = {
            key: value
            for key, value in (
                ("weight_kg", 70),
                ("readiness", 65),
                ("cycling_ftp_watts", 280),
                ("bike_threshold_hr_bpm", 165),
                ("run_threshold_watts", 300),
                ("run_threshold_pace_seconds_per_km", 280),
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
        return garmin_metrics_from_payload(garmin).performance_history

    def _inputs(self):
        metrics = {
            "weight_kg": {"value": 72, "source": GARMIN_SOURCE},
            "readiness": {"value": 80, "source": GARMIN_SOURCE},
            "cycling_ftp_watts": {"value": 300, "source": GARMIN_SOURCE},
            "bike_threshold_hr_bpm": {"value": 170, "source": GARMIN_SOURCE},
            "run_threshold_watts": {"value": 320, "source": GARMIN_SOURCE},
            "run_threshold_pace_seconds_per_km": {
                "value": 270,
                "source": GARMIN_SOURCE,
            },
            "run_threshold_hr_bpm": {"value": 175, "source": GARMIN_SOURCE},
            "cycling_vo2max_ml_kg_min": {"value": 60, "source": GARMIN_SOURCE},
            "running_vo2max_ml_kg_min": {"value": 58, "source": GARMIN_SOURCE},
            "run_5k_seconds": {"value": 1_300, "source": GARMIN_SOURCE},
            "run_10k_seconds": {"value": 2_700, "source": GARMIN_SOURCE},
            "run_half_marathon_seconds": {"value": 5_800, "source": GARMIN_SOURCE},
            "run_marathon_seconds": {"value": 12_000, "source": GARMIN_SOURCE},
        }
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
            # The local fitness (M7) and its own 7-day averages.
            "load": {
                "ctl": 70,
                "tsb": -5,
                "atl": 80,
                "averages_7d": {"ctl": 68, "tsb": -8, "atl": 76},
            },
            "last_7": {"training_load": 100, "duration_hours": 10},
            "previous_7": {"training_load": 90, "duration_hours": 8},
            "previous_30": {"training_load": 400, "duration_hours": 30},
        }
        return (metrics, recovery, load_context)

    def test_comparisons_preserve_keys_units_labels_and_direction_flags(self):
        values = self._inputs()
        history = self._history()
        before = copy.deepcopy(values)
        result = performance_comparisons(*values, TODAY, garmin_history=history)

        self.assertEqual(result["sleep_hours"]["unit"], "h")
        self.assertEqual(result["sleep_hours"]["days"], 7)
        self.assertEqual(result["sleep_hours"]["color"], "good")
        self.assertEqual(result["resting_hr_bpm"]["color"], "good")
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
        self.assertEqual(result["readiness_30d"]["days"], 30)
        self.assertEqual(values, before)

    def test_eftp_is_not_compared_and_form_compares_the_local_values(self):
        metrics, recovery, load_context = self._inputs()
        metrics = {
            **metrics,
            "cycling_eftp_watts": {"value": 309, "source": "Intervals.icu"},
        }
        result = performance_comparisons(
            metrics, recovery, load_context, TODAY, garmin_history=self._history()
        )
        self.assertNotIn("cycling_eftp_30d", result)
        self.assertFalse(any("eftp" in key for key in result))
        self.assertEqual(
            (result["form_tsb"]["current"], result["form_tsb"]["average"]), (-5, -8)
        )

    def test_fitness_form_and_fatigue_compare_the_local_values(self):
        # Only the local values and their averages count.
        result = performance_comparisons(
            *self._inputs(), TODAY, garmin_history=self._history()
        )
        self.assertEqual(
            (result["form_tsb"]["current"], result["form_tsb"]["average"]), (-5, -8)
        )
        self.assertEqual(result["fitness_ctl"]["average"], 68)
        self.assertEqual(result["fatigue_atl"]["average"], 76)
        self.assertNotIn("fatigue_atl_actual", result)

    def test_missing_values_return_none_without_mutation(self):
        values = self._inputs()
        history = self._history()
        values = list(values)
        values[0] = {"cycling_eftp_watts": {"value": None, "source": None}}
        values[1] = {
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
        result = performance_comparisons(*values, TODAY, garmin_history=history)

        self.assertIsNone(result["sleep_hours"])
        self.assertIsNone(result["readiness"])
        self.assertNotIn("cycling_eftp_30d", result)
        self.assertEqual(values, before)


if __name__ == "__main__":
    unittest.main()
