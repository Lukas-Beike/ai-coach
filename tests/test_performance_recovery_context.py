"""Current recovery values from canonical observations only.

The raw Garmin sections and wellness rows below go through the real provider
mappers first (``mapped_recovery_inputs``), so the fixtures stay comparable with
the legacy reader they replaced. Where the canonical result differs from the
legacy one, the test says so.
"""

import unittest
from datetime import date

from canonical_recovery_support import (
    mapped_recovery_inputs,
    recovery_inputs,
    recovery_observation,
)

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.recovery_context import (
    GARMIN_WEEKLY_HRV_SOURCE,
    performance_recovery_context,
)

TODAY = date(2026, 9, 7)
GARMIN = "Garmin Connect"
INTERVALS = "Intervals.icu Wellness"
_EMPTY = {
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
}


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
        rows = [
            {"id": "2026-09-01", "sleepSecs": 21_600},
            {"id": "2026-09-05", "sleepSecs": 25_200},
            {"id": "2026-09-07", "sleepSecs": 18_000, "sleepScore": 70},
        ]

        result = performance_recovery_context(
            mapped_recovery_inputs(garmin, rows), TODAY
        )

        self.assertEqual(result["sleep_hours"], 8.0)
        self.assertEqual(result["sleep_source"], GARMIN)
        # Only Garmin nights: the Intervals history is never blended in.
        self.assertEqual(result["sleep_average"], 7.5)
        self.assertEqual(result["sleep_score"], 90)
        self.assertEqual(result["sleep_score_source"], GARMIN)
        # Intended: a Garmin value always carries its observation day.
        self.assertEqual(result["sleep_date"], "2026-09-07")

    def test_intervals_sleep_fallback_and_average_of_exact_hours(self):
        rows = [
            {"id": "2026-08-30", "sleepSecs": 36_000},
            {"id": "2026-09-02", "sleep_seconds": 25_200},
            {"id": "2026-09-07", "sleepSecs": 21_600, "sleepScore": 75},
        ]

        result = performance_recovery_context(mapped_recovery_inputs(None, rows), TODAY)

        self.assertEqual(result["sleep_hours"], 6.0)
        self.assertEqual(result["sleep_source"], INTERVALS)
        self.assertEqual(result["sleep_average"], 6.5)
        self.assertEqual(result["sleep_score"], 75)
        self.assertEqual(result["sleep_score_source"], INTERVALS)
        self.assertIsNone(result["sleep_date"])

    def test_garmin_sleep_average_uses_exact_hours(self):
        # Intended: legacy rounded each Garmin night to 0.1 h before averaging.
        garmin = {
            "sleep": [
                {"calendarDate": "2026-09-07", "sleepTimeSeconds": 25_380},
                {"calendarDate": "2026-09-06", "sleepTimeSeconds": 25_380},
            ]
        }

        result = performance_recovery_context(mapped_recovery_inputs(garmin), TODAY)

        self.assertEqual(result["sleep_hours"], 7.0)
        self.assertEqual(result["sleep_average"], 7.05)

    def test_recovery_metrics_use_garmin_bounds_observed_dates_and_averages(self):
        garmin = {
            "resting_hr": [
                {"calendarDate": "2026-09-07", "restingHeartRate": 20},
                {"calendarDate": "2026-09-05", "restingHeartRate": 50},
            ],
            "hrv": [
                {"calendarDate": "2026-09-07", "hrvLastNight": 60},
                {"calendarDate": "2026-09-05", "lastNightAvg": 40},
            ],
        }
        rows = [
            {"id": "2026-09-05", "restingHR": 52, "hrv": 42},
            {"id": "2026-09-07", "restingHR": 55, "hrv": 45},
        ]

        result = performance_recovery_context(
            mapped_recovery_inputs(garmin, rows), TODAY
        )

        # 20 bpm is outside the Garmin bounds, so the older valid Garmin day wins.
        self.assertEqual(result["resting_hr"], 50)
        self.assertEqual(result["resting_hr_source"], GARMIN)
        # The out-of-bounds day is left out of the Garmin average, as before.
        self.assertEqual(result["resting_hr_average"], 50.0)
        self.assertEqual(result["resting_hr_date"], "2026-09-05")
        self.assertEqual(result["hrv"], 60)
        self.assertEqual(result["hrv_source"], GARMIN)
        self.assertEqual(result["hrv_average"], 50.0)
        self.assertEqual(result["hrv_date"], "2026-09-07")

    def test_intervals_values_and_averages_without_garmin(self):
        rows = [
            {"id": "2026-09-01", "restingHR": 50, "hrv": 40},
            {"id": "2026-09-07", "restingHR": 60, "hrv_ms": 50},
        ]

        result = performance_recovery_context(mapped_recovery_inputs(None, rows), TODAY)

        self.assertEqual(result["resting_hr"], 60)
        self.assertEqual(result["resting_hr_source"], INTERVALS)
        self.assertEqual(result["resting_hr_average"], 55.0)
        self.assertIsNone(result["resting_hr_date"])
        self.assertEqual(result["hrv"], 50)
        self.assertEqual(result["hrv_source"], INTERVALS)
        self.assertEqual(result["hrv_average"], 45.0)
        self.assertIsNone(result["hrv_date"])

    def test_intervals_values_are_pinned_to_the_latest_wellness_row(self):
        rows = [
            {"id": "2026-09-06", "restingHR": 50, "hrv": 40},
            {"id": "2026-09-07", "sleepSecs": 25_200},
        ]

        result = performance_recovery_context(mapped_recovery_inputs(None, rows), TODAY)

        self.assertIsNone(result["resting_hr"])
        self.assertIsNone(result["hrv"])
        self.assertEqual(result["resting_hr_average"], 50.0)

    def test_out_of_bounds_garmin_values_are_not_current(self):
        invalid = performance_recovery_context(
            mapped_recovery_inputs(
                {
                    "resting_hr": [{"calendarDate": "2026-09-07", "restingHR": 29}],
                    "hrv": [{"calendarDate": "2026-09-07", "hrvLastNight": 301}],
                }
            ),
            TODAY,
        )

        self.assertIsNone(invalid["resting_hr"])
        self.assertIsNone(invalid["hrv"])

    def test_readiness_prefers_intervals_and_falls_back_to_garmin(self):
        rows = [
            {"id": "2026-09-01", "readiness": 70},
            {"id": "2026-09-07", "readiness": 82},
        ]
        garmin = {"readiness": [{"calendarDate": "2026-09-07", "score": 65}]}

        result = performance_recovery_context(
            mapped_recovery_inputs(garmin, rows), TODAY
        )

        self.assertEqual(result["readiness"], 82)
        self.assertEqual(result["readiness_source"], INTERVALS)
        self.assertEqual(result["readiness_average"], 76.0)

        fallback = performance_recovery_context(
            mapped_recovery_inputs(garmin, [{"id": "2026-09-07", "hrv": 50}]), TODAY
        )
        self.assertEqual(fallback["readiness"], 65)
        self.assertEqual(fallback["readiness_source"], GARMIN)
        # Intended: the average uses the selected provider, never a mix.
        self.assertEqual(fallback["readiness_average"], 65.0)

    def test_weekly_hrv_is_a_labelled_fallback_without_average(self):
        weekly_only = mapped_recovery_inputs(
            {
                "hrv": [
                    {"calendarDate": "2026-09-07", "weeklyAvg": 58},
                    {"calendarDate": "2026-09-06", "weeklyAvg": 57},
                ]
            }
        )

        result = performance_recovery_context(weekly_only, TODAY)

        self.assertEqual(result["hrv"], 58)
        self.assertEqual(result["hrv_source"], GARMIN_WEEKLY_HRV_SOURCE)
        self.assertEqual(result["hrv_source"], "Garmin Connect (Wochenmittel)")
        self.assertIsNone(result["hrv_average"])
        self.assertEqual(result["hrv_date"], "2026-09-07")

    def test_last_night_rmssd_wins_over_the_weekly_average(self):
        inputs = mapped_recovery_inputs(
            {"hrv": [{"calendarDate": "2026-09-07", "weeklyAvg": 58}]},
            [{"id": "2026-09-07", "hrv": 44}],
        )

        result = performance_recovery_context(inputs, TODAY)

        self.assertEqual(result["hrv"], 44)
        self.assertEqual(result["hrv_source"], INTERVALS)
        self.assertEqual(result["hrv_average"], 44.0)

    def test_garmin_values_without_a_wellness_day(self):
        inputs = recovery_inputs(
            [
                recovery_observation(MetricKind.SLEEP_DURATION, 27_000, "2026-09-07"),
                recovery_observation(MetricKind.RESTING_HR, 48, "2026-09-07"),
            ]
        )

        result = performance_recovery_context(inputs, TODAY)

        self.assertEqual(result["sleep_hours"], 7.5)
        self.assertEqual(result["sleep_source"], GARMIN)
        self.assertEqual(result["resting_hr"], 48)
        self.assertEqual(result["resting_hr_date"], "2026-09-07")

    def test_averages_never_mix_providers(self):
        inputs = recovery_inputs(
            [
                recovery_observation(MetricKind.RESTING_HR, 48, "2026-09-07"),
                recovery_observation(
                    MetricKind.RESTING_HR, 60, "2026-09-06", ProviderId.INTERVALS
                ),
                recovery_observation(
                    MetricKind.RESTING_HR, 62, "2026-09-07", ProviderId.INTERVALS
                ),
            ],
            latest_wellness_day=date(2026, 9, 7),
        )

        result = performance_recovery_context(inputs, TODAY)

        self.assertEqual(result["resting_hr"], 48)
        self.assertEqual(result["resting_hr_average"], 48.0)

    def test_missing_inputs_yield_no_values(self):
        self.assertEqual(performance_recovery_context(None, TODAY), _EMPTY)
        self.assertEqual(performance_recovery_context(recovery_inputs(), TODAY), _EMPTY)


if __name__ == "__main__":
    unittest.main()
