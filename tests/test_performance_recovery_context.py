"""Current recovery values from canonical observations only.

The raw Garmin sections and wellness rows below go through the real provider
mappers first (``mapped_recovery_inputs``), so the fixtures stay comparable with
the legacy reader they replaced. Where the canonical result differs from the
legacy one, the test says so.
"""

import unittest
from dataclasses import replace
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
from backend.performance.source_policy import preferences_from_profile

TODAY = date(2026, 9, 7)
GARMIN = "Garmin Connect"
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

    def test_sleep_with_only_intervals_values_is_none(self):
        rows = [
            {"id": "2026-08-30", "sleepSecs": 36_000},
            {"id": "2026-09-07", "sleepSecs": 21_600, "sleepScore": 75},
        ]

        result = performance_recovery_context(mapped_recovery_inputs(None, rows), TODAY)

        self.assertIsNone(result["sleep_hours"])
        self.assertIsNone(result["sleep_source"])
        self.assertIsNone(result["sleep_average"])
        self.assertIsNone(result["sleep_score"])
        self.assertIsNone(result["sleep_score_source"])

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

    def test_intervals_resting_hr_and_hrv_without_garmin_are_none(self):
        rows = [
            {"id": "2026-09-01", "restingHR": 50, "hrv": 40},
            {"id": "2026-09-07", "restingHR": 60, "hrv_ms": 50},
        ]

        result = performance_recovery_context(mapped_recovery_inputs(None, rows), TODAY)

        self.assertIsNone(result["resting_hr"])
        self.assertIsNone(result["resting_hr_average"])
        self.assertIsNone(result["hrv"])
        self.assertIsNone(result["hrv_average"])

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

    def test_readiness_comes_from_garmin_only(self):
        rows = [
            {"id": "2026-09-01", "readiness": 70},
            {"id": "2026-09-07", "readiness": 82},
        ]
        garmin = {"readiness": [{"calendarDate": "2026-09-07", "score": 65}]}

        result = performance_recovery_context(
            mapped_recovery_inputs(garmin, rows), TODAY
        )

        self.assertEqual(result["readiness"], 65)
        self.assertEqual(result["readiness_source"], GARMIN)
        self.assertEqual(result["readiness_average"], 65.0)

        only_intervals = performance_recovery_context(
            mapped_recovery_inputs(None, rows), TODAY
        )
        self.assertIsNone(only_intervals["readiness"])
        self.assertIsNone(only_intervals["readiness_source"])

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

    def test_the_weekly_average_is_not_replaced_by_an_intervals_rmssd(self):
        inputs = mapped_recovery_inputs(
            {"hrv": [{"calendarDate": "2026-09-07", "weeklyAvg": 58}]},
            [{"id": "2026-09-07", "hrv": 44}],
        )

        result = performance_recovery_context(inputs, TODAY)

        self.assertEqual(result["hrv"], 58)
        self.assertEqual(result["hrv_source"], GARMIN_WEEKLY_HRV_SOURCE)

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
        )

        result = performance_recovery_context(inputs, TODAY)

        self.assertEqual(result["resting_hr"], 48)
        self.assertEqual(result["resting_hr_average"], 48.0)

    def test_missing_inputs_yield_no_values(self):
        self.assertEqual(performance_recovery_context(None, TODAY), _EMPTY)
        self.assertEqual(performance_recovery_context(recovery_inputs(), TODAY), _EMPTY)


def _resting_hr_days() -> list:
    """Garmin on 2026-09-01..06, an equal Intervals series on 09-01..07."""
    observations = []
    for day in range(1, 8):
        iso = f"2026-09-0{day}"
        observations.append(
            recovery_observation(
                MetricKind.RESTING_HR,
                50.0 + day,
                iso,
                ProviderId.INTERVALS,
                record_id=iso,
            )
        )
        if day < 7:
            observations.append(
                recovery_observation(MetricKind.RESTING_HR, 50.0 + day, iso)
            )
    return observations


class IntervalsIsNeverASourceTests(unittest.TestCase):
    def test_an_equal_intervals_series_is_not_a_relay_and_adds_no_day(self):
        context = performance_recovery_context(
            recovery_inputs(_resting_hr_days()), TODAY
        )

        self.assertEqual(context["resting_hr"], 56)
        self.assertEqual(context["resting_hr_source"], GARMIN)
        self.assertEqual(context["resting_hr_average"], 53.5)

    def test_a_stored_intervals_preference_is_ignored(self):
        inputs = replace(
            recovery_inputs(_resting_hr_days()),
            preferences=preferences_from_profile(
                {"preferred_source_resting_hr": "intervals"}
            ),
        )

        self.assertEqual(inputs.preferences, {})
        context = performance_recovery_context(inputs, TODAY)

        self.assertEqual(context["resting_hr"], 56)
        self.assertEqual(context["resting_hr_source"], GARMIN)

    def test_an_intervals_hrv_preference_still_shows_the_garmin_weekly_value(self):
        weekly = recovery_observation(MetricKind.HRV_WEEKLY_AVERAGE, 61, "2026-09-07")
        inputs = replace(
            recovery_inputs([weekly]),
            preferences=preferences_from_profile({"preferred_source_hrv": "intervals"}),
        )

        context = performance_recovery_context(inputs, TODAY)

        self.assertEqual(context["hrv"], 61)
        self.assertEqual(context["hrv_source"], GARMIN_WEEKLY_HRV_SOURCE)


if __name__ == "__main__":
    unittest.main()
