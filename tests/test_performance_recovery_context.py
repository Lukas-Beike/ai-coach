import copy
import unittest
from datetime import date

from backend.performance.recovery_context import performance_recovery_context

TODAY = date(2026, 9, 7)


class PerformanceRecoveryContextTests(unittest.TestCase):
    def test_garmin_sleep_priority_average_score_source_and_observed_date(self):
        garmin = {
            "sleep": [
                {
                    "calendarDate": "2026-09-07",
                    "sleepTimeSeconds": 28_800,
                    "sleepScore": 90,
                },
                {
                    "calendarDate": "2026-09-05",
                    "sleepTimeSeconds": 25_200,
                    "sleepScore": 80,
                },
            ]
        }
        latest = {"sleepSecs": 18_000, "sleepScore": 70}
        rows = [
            {"id": "2026-09-01", "sleepSecs": 21_600},
            {"id": "2026-09-05", "sleepSecs": 25_200},
            {"id": "2026-09-07", "sleepSecs": 28_800},
            {"id": "2026-08-31", "sleepSecs": 36_000},
        ]

        result = performance_recovery_context(garmin, latest, rows, TODAY)

        self.assertEqual(result["sleep_hours"], 8.0)
        self.assertEqual(result["sleep_source"], "Garmin Connect")
        self.assertEqual(result["sleep_average"], 7.5)
        self.assertEqual(result["sleep_score"], 90)
        self.assertEqual(result["sleep_score_source"], "Garmin Connect")
        self.assertIsNone(result["sleep_date"])

    def test_intervals_sleep_fallback_and_sleep_hours_average(self):
        latest = {"sleepSecs": 21_600, "sleepScore": 75}
        rows = [
            {"date": "2026-09-02", "sleep_seconds": 25_200},
            {"date": "2026-09-07", "sleepSecs": 28_800},
            {"date": "2026-08-30", "sleepSecs": 36_000},
        ]

        result = performance_recovery_context({}, latest, rows, TODAY)

        self.assertEqual(result["sleep_hours"], 6.0)
        self.assertEqual(result["sleep_source"], "Intervals.icu Wellness")
        self.assertEqual(result["sleep_average"], 7.5)
        self.assertEqual(result["sleep_score"], 75)
        self.assertEqual(result["sleep_score_source"], "Intervals.icu Wellness")
        self.assertIsNone(result["sleep_date"])

        hours_only = performance_recovery_context(
            {}, {"sleepScore": 72}, [{"id": "2026-09-07", "sleep_hours": 7.25}], TODAY
        )
        self.assertEqual(hours_only["sleep_hours"], None)
        self.assertEqual(hours_only["sleep_average"], 7.25)

    def test_recovery_metrics_use_garmin_bounds_observed_dates_and_averages(self):
        garmin = {
            "resting_hr": [
                {"calendarDate": "2026-09-07", "restingHeartRate": 20},
                {"calendarDate": "2026-09-05", "restingHeartRate": 50},
            ],
            "hrv": [
                {"calendarDate": "2026-09-07", "hrvLastNight": 60},
                {"calendarDate": "2026-09-05", "weeklyAvg": 40},
            ],
        }
        latest = {"restingHR": 55, "hrv": 45}
        rows = [
            {"id": "2026-09-05", "restingHR": 52, "hrv": 42},
            {"id": "2026-09-07", "restingHR": 54, "hrv": 44},
        ]

        result = performance_recovery_context(garmin, latest, rows, TODAY)

        self.assertEqual(result["resting_hr"], 50)
        self.assertEqual(result["resting_hr_source"], "Garmin Connect")
        self.assertEqual(result["resting_hr_average"], 50.0)
        self.assertEqual(result["resting_hr_date"], "2026-09-05")
        self.assertEqual(result["hrv"], 60)
        self.assertEqual(result["hrv_source"], "Garmin Connect")
        self.assertEqual(result["hrv_average"], 50.0)
        self.assertEqual(result["hrv_date"], "2026-09-07")

    def test_fallback_recovery_values_and_bounds(self):
        latest = {"resting_hr": 55, "hrv_ms": 45}
        rows = [
            {"id": "2026-09-01", "resting_hr": 50, "hrv_ms": 40},
            {"id": "2026-09-07", "resting_hr": 60, "hrv_ms": 50},
        ]
        result = performance_recovery_context({}, latest, rows, TODAY)

        self.assertEqual(result["resting_hr"], 55)
        self.assertEqual(result["resting_hr_source"], "Intervals.icu Wellness")
        self.assertEqual(result["resting_hr_average"], 55.0)
        self.assertIsNone(result["resting_hr_date"])
        self.assertEqual(result["hrv"], 45)
        self.assertEqual(result["hrv_source"], "Intervals.icu Wellness")
        self.assertEqual(result["hrv_average"], 45.0)
        self.assertIsNone(result["hrv_date"])

        invalid = performance_recovery_context(
            {
                "resting_hr": [{"date": "2026-09-07", "restingHR": 29}],
                "hrv": [{"date": "2026-09-07", "hrv": 301}],
            },
            {},
            [],
            TODAY,
        )
        self.assertIsNone(invalid["resting_hr"])
        self.assertIsNone(invalid["hrv"])

    def test_readiness_prefers_intervals_and_falls_back_to_garmin(self):
        latest = {"trainingReadiness": {"score": 82}}
        rows = [
            {"id": "2026-09-01", "readiness": 70},
            {"id": "2026-09-07", "training_readiness": {"score": 80}},
        ]
        result = performance_recovery_context(
            {"readiness": [{"calendarDate": "2026-09-07", "score": 65}]},
            latest,
            rows,
            TODAY,
        )
        self.assertEqual(result["readiness"], 82)
        self.assertEqual(result["readiness_source"], "Intervals.icu Wellness")
        self.assertEqual(result["readiness_average"], 70.0)

        fallback = performance_recovery_context(
            {"readiness": {"trainingReadiness": {"score": 65}}}, {}, rows, TODAY
        )
        self.assertEqual(fallback["readiness"], 65)
        self.assertEqual(fallback["readiness_source"], "Garmin Connect")
        self.assertEqual(fallback["readiness_average"], 70.0)

    def test_missing_values_and_input_nonmutation(self):
        garmin = {"sleep": [], "resting_hr": [], "hrv": [], "readiness": None}
        latest = {}
        rows = []
        original = copy.deepcopy((garmin, latest, rows))

        result = performance_recovery_context(garmin, latest, rows, TODAY)

        self.assertEqual(
            result,
            {
                "sleep_hours": None,
                "sleep_source": None,
                "sleep_average": None,
                "sleep_score": None,
                "sleep_score_source": None,
                "sleep_date": None,
                "resting_hr": None,
                "resting_hr_source": None,
                "resting_hr_average": None,
                "resting_hr_date": None,
                "hrv": None,
                "hrv_source": None,
                "hrv_average": None,
                "hrv_date": None,
                "readiness": None,
                "readiness_source": None,
                "readiness_average": None,
            },
        )
        self.assertEqual((garmin, latest, rows), original)


if __name__ == "__main__":
    unittest.main()
