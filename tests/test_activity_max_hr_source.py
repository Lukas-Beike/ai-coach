"""Activity max HR keeps the provider its summary names for the value."""

import unittest

from backend.canonical.vocabulary import Sport
from backend.performance.current_metrics import _max_hr_metric, metric

_NO_GARMIN = {"cycling_max_hr_bpm": metric(None, "bpm", None)}


def _summary(max_hr: float, source: str) -> dict:
    return {"sport": "ride", "max_hr": max_hr, "sources": {"max_hr": source}}


class ActivityMaxHrSourceTests(unittest.TestCase):
    def test_the_highest_value_names_its_provider(self) -> None:
        result = _max_hr_metric(
            "cycling",
            Sport.RIDE,
            [_summary(181, "Intervals.icu"), _summary(186, "Garmin Connect")],
            {},
            _NO_GARMIN,
        )

        self.assertEqual((186, "Garmin Connect"), (result["value"], result["source"]))

    def test_an_aged_out_garmin_profile_max_hr_is_not_a_fallback(self) -> None:
        profile = {"value": 188, "unit": "bpm", "source": "Garmin Connect"}
        result = _max_hr_metric(
            "cycling",
            Sport.RIDE,
            [_summary(181, "Intervals.icu")],
            {},
            {"cycling_max_hr_bpm": {**profile, "observed_at": None}},
        )
        self.assertEqual((181, "Intervals.icu"), (result["value"], result["source"]))
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


if __name__ == "__main__":
    unittest.main()
