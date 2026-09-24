import copy
import unittest

from backend.performance.current_metrics import current_performance_metrics


def empty_garmin(**overrides):
    keys = (
        "weight_kg",
        "cycling_ftp_watts",
        "run_threshold_watts",
        "run_threshold_pace_seconds_per_km",
        "bike_threshold_hr_bpm",
        "run_threshold_hr_bpm",
        "cycling_max_hr_bpm",
        "running_max_hr_bpm",
        "cycling_vo2max_ml_kg_min",
        "running_vo2max_ml_kg_min",
        "run_5k_seconds",
        "run_10k_seconds",
        "run_half_marathon_seconds",
        "run_marathon_seconds",
    )
    result = {
        key: {"value": None, "unit": "", "source": None, "note": ""} for key in keys
    }
    result.update(overrides)
    return result


class CurrentPerformanceMetricsTests(unittest.TestCase):
    def test_garmin_priority_and_metric_shape(self):
        garmin = empty_garmin(
            weight_kg={
                "value": 70,
                "unit": "kg",
                "source": "Garmin Connect",
                "note": "weight",
            },
            cycling_ftp_watts={
                "value": 302,
                "unit": "W",
                "source": "Garmin Connect",
                "note": "ftp",
            },
            cycling_max_hr_bpm={
                "value": 188,
                "unit": "bpm",
                "source": "Garmin Connect",
                "note": "",
            },
            cycling_vo2max_ml_kg_min={
                "value": 60,
                "unit": "ml/kg/min",
                "source": "Garmin Connect",
                "note": "",
            },
        )
        result = current_performance_metrics(
            {
                "athlete": {
                    "weight": 75,
                    "sport_settings": [
                        {"types": ["Ride"], "ftp": 250, "max_hr": 180, "vo2max": 50}
                    ],
                },
                "recent_wellness": [],
                "recent_activities": [],
            },
            {"weight_kg": 80},
            garmin,
        )
        self.assertEqual(result["weight_kg"], garmin["weight_kg"])
        self.assertEqual(result["cycling_ftp_watts"], garmin["cycling_ftp_watts"])
        self.assertEqual(result["cycling_max_hr_bpm"], garmin["cycling_max_hr_bpm"])
        self.assertEqual(
            result["cycling_vo2max_ml_kg_min"], garmin["cycling_vo2max_ml_kg_min"]
        )

    def test_intervals_wellness_athlete_profile_fallbacks_and_eftp(self):
        snapshot = {
            "athlete": {
                "weight": 78,
                "bodyFat": 18,
                "height": 1.8,
                "icu_ftp": 240,
                "sport_settings": [
                    {
                        "types": ["Rad"],
                        "ftp": 250,
                        "eftp": 260,
                        "lthr": 160,
                        "vo2max": 52,
                    },
                    {
                        "types": ["Laufen"],
                        "ftp": 280,
                        "lthr": 165,
                        "vo2max": 48,
                        "threshold_pace": 4.0,
                    },
                ],
            },
            "recent_wellness": [
                {
                    "id": "2026-08-30",
                    "sportInfo": [{"types": ["Ride"], "ftp": 255, "eFTP": 265}],
                },
                {
                    "id": "2026-08-31",
                    "sport_info": [
                        {"types": ["Ride"], "ftp": 256, "eFTP": 266},
                        {"types": ["Run"], "lthr": 166},
                    ],
                },
            ],
            "recent_activities": [
                {"type": "Ride", "start_date_local": "2026-08-30", "icu_eftp": 270},
                {"type": "Ride", "start_date_local": "2026-08-31", "icu_eftp": 275},
            ],
        }
        result = current_performance_metrics(
            snapshot,
            {"weight_kg": 80, "body_fat_pct": 20, "height_cm": 170},
            empty_garmin(),
        )
        self.assertEqual(result["weight_kg"]["value"], 78)
        self.assertEqual(result["body_fat_pct"]["value"], 18)
        self.assertEqual(result["height_cm"]["value"], 180)
        self.assertEqual(result["cycling_ftp_watts"]["value"], 250)
        self.assertEqual(result["cycling_eftp_watts"]["value"], 260)
        self.assertEqual(result["run_threshold_watts"]["value"], 280)
        self.assertEqual(result["run_threshold_hr_bpm"]["value"], 165)

    def test_eftp_uses_mmp_model_and_latest_ride_fallback(self):
        snapshot = {
            "athlete": {
                "sport_settings": [
                    {"types": ["Ride"], "ftp": 300, "mmp_model": {"ftp": 309}}
                ]
            },
            "recent_wellness": [{"id": "2026-08-31"}],
            "recent_activities": [
                {"type": "Ride", "start_date_local": "2026-09-01", "icu_eftp": 290}
            ],
        }
        result = current_performance_metrics(snapshot, {}, empty_garmin())
        self.assertEqual(result["cycling_ftp_watts"]["value"], 300)
        self.assertEqual(result["cycling_eftp_watts"]["value"], 309)
        snapshot["athlete"]["sport_settings"][0].pop("mmp_model")
        result = current_performance_metrics(snapshot, {}, empty_garmin())
        self.assertEqual(result["cycling_eftp_watts"]["value"], 290)

    def test_max_hr_activity_fallback_and_sport_aliases(self):
        snapshot = {
            "athlete": {"sport_settings": [{"types": ["Ride"]}, {"types": ["Run"]}]},
            "recent_wellness": [],
            "recent_activities": [
                {"sport": "Radfahren", "maxHR": 181},
                {"activityName": "Laufen", "maxHeartRate": 191},
                {"type": "Ride", "maxHR": 400},
            ],
        }
        result = current_performance_metrics(snapshot, {}, empty_garmin())
        self.assertEqual(result["cycling_max_hr_bpm"]["value"], 181)
        self.assertEqual(result["running_max_hr_bpm"]["value"], 191)
        self.assertEqual(result["cycling_max_hr_bpm"]["source"], "Intervals.icu")

    def test_threshold_zone2_and_prediction_metrics(self):
        snapshot = {
            "athlete": {
                "sport_settings": [
                    {"types": ["Ride"], "lthr": 160},
                    {
                        "types": ["Run"],
                        "threshold_pace": 4.0,
                        "zone2_pace": 5.0,
                        "lthr": 165,
                        "vo2max": 48,
                    },
                ]
            },
            "recent_wellness": [],
            "recent_activities": [],
        }
        result = current_performance_metrics(snapshot, {}, empty_garmin())
        self.assertEqual(result["run_threshold_pace_seconds_per_km"]["value"], 250)
        self.assertEqual(result["run_zone2_pace_seconds_per_km"]["value"], 200)
        self.assertEqual(result["bike_threshold_hr_bpm"]["value"], 160)
        self.assertEqual(result["running_vo2max_ml_kg_min"]["value"], 48)
        self.assertEqual(result["run_5k_seconds"]["value"], None)

    def test_invalid_values_and_inputs_are_not_mutated(self):
        snapshot = {
            "athlete": {
                "weight": "invalid",
                "height": "nan",
                "sport_settings": [{"types": ["Run"], "threshold_pace": 10000}],
            },
            "recent_wellness": [{"id": "2026-08-31", "bodyFat": "invalid"}],
            "recent_activities": [],
        }
        profile = {"weight_kg": 72, "body_fat_pct": 20, "height_cm": 175}
        garmin = empty_garmin()
        before = copy.deepcopy((snapshot, profile, garmin))
        result = current_performance_metrics(snapshot, profile, garmin)
        self.assertEqual(result["weight_kg"]["value"], 72)
        self.assertEqual(result["body_fat_pct"]["value"], 20)
        self.assertEqual(result["run_threshold_pace_seconds_per_km"]["value"], 10000)
        self.assertEqual((snapshot, profile, garmin), before)


if __name__ == "__main__":
    unittest.main()
