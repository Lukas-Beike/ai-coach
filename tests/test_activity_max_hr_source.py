"""Activity max HR: Garmin and Wahoo maxima, else a labelled summary value (#1686)."""

import unittest
from datetime import date

from backend.canonical.vocabulary import Sport
from backend.performance.current_metrics import (
    _max_hr_metric,
    _overall_max_hr,
    metric,
)
from backend.performance.garmin_canonical import ActivityMaxHr

_NO_GARMIN = {"cycling_max_hr_bpm": metric(None, "bpm", None)}
_GARMIN_ACTIVITY = {
    "value": 182,
    "unit": "bpm",
    "source": "Garmin Connect",
    "source_provider": "garmin",
    "observed_at": "2026-10-01",
}


def _summary(max_hr: float, source: str) -> dict:
    return {"sport": "ride", "max_hr": max_hr, "sources": {"max_hr": source}}


class ActivityMaxHrSourceTests(unittest.TestCase):
    def test_the_highest_garmin_or_wahoo_summary_names_its_provider(self) -> None:
        result = _max_hr_metric(
            "cycling",
            Sport.RIDE,
            [_summary(181, "Wahoo"), _summary(186, "Garmin Connect")],
            {},
            _NO_GARMIN,
        )

        self.assertEqual((186, "Garmin Connect"), (result["value"], result["source"]))

    def test_an_intervals_summary_is_not_a_fallback(self) -> None:
        result = _max_hr_metric(
            "cycling", Sport.RIDE, [_summary(199, "Intervals.icu")], {}, _NO_GARMIN
        )

        self.assertIsNone(result["value"])

    def test_an_aged_out_garmin_profile_max_hr_is_not_a_fallback(self) -> None:
        profile = {"value": 188, "unit": "bpm", "source": "Garmin Connect"}
        result = _max_hr_metric(
            "cycling",
            Sport.RIDE,
            [_summary(181, "Wahoo")],
            {},
            {"cycling_max_hr_bpm": {**profile, "observed_at": None}},
        )
        self.assertEqual((181, "Wahoo"), (result["value"], result["source"]))
        activity = {**profile, "observed_at": "2026-10-01"}
        result = _max_hr_metric(
            "cycling", Sport.RIDE, [], {}, {"cycling_max_hr_bpm": activity}
        )
        self.assertEqual(188, result["value"])

    def test_an_unlabelled_value_is_not_counted(self) -> None:
        result = _max_hr_metric(
            "cycling",
            Sport.RIDE,
            [{"sport": "ride", "max_hr": 190}],
            {},
            _NO_GARMIN,
        )

        self.assertIsNone(result["value"])

    def test_a_higher_stored_wahoo_maximum_beats_garmin_and_is_dated(self) -> None:
        garmin = {"cycling_max_hr_bpm": _GARMIN_ACTIVITY}
        higher = _max_hr_metric(
            "cycling",
            Sport.RIDE,
            [_summary(199, "Garmin Connect")],
            {},
            garmin,
            {"cycling": ActivityMaxHr(191.0, date(2026, 6, 2))},
        )
        tie = _max_hr_metric(
            "cycling",
            Sport.RIDE,
            [],
            {},
            garmin,
            {"cycling": ActivityMaxHr(182.0, date(2026, 6, 2))},
        )

        self.assertEqual((191.0, "Wahoo"), (higher["value"], higher["source"]))
        self.assertEqual("2026-06-02", higher["observed_at"])
        self.assertIs(_GARMIN_ACTIVITY, tie)


class OverallMaxHrTests(unittest.TestCase):
    def test_activity_maxima_rank_after_thresholds_and_compare_by_value(self) -> None:
        wahoo = {"value": 195, "source": "Wahoo", "source_provider": "wahoo"}
        garmin = dict(_GARMIN_ACTIVITY, value=180)
        both_activity = _overall_max_hr(((wahoo, True), (garmin, True)))
        threshold = dict(garmin, value=176)
        with_threshold = _overall_max_hr(((wahoo, True), (threshold, False)))

        self.assertIs(wahoo, both_activity)
        self.assertIs(threshold, with_threshold)


if __name__ == "__main__":
    unittest.main()
