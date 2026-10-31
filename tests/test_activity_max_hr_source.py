"""Activity max HR keeps the provider its summary names for the value."""

import unittest

from backend.canonical.vocabulary import Sport
from backend.performance.canonical_current import NO_CURRENT_INPUTS
from backend.performance.current_metrics import _intervals_max_hr_metric


def _summary(max_hr: float, source: str) -> dict:
    return {"sport": "ride", "max_hr": max_hr, "sources": {"max_hr": source}}


class ActivityMaxHrSourceTests(unittest.TestCase):
    def test_the_highest_value_names_its_provider(self) -> None:
        metric = _intervals_max_hr_metric(
            "cycling",
            Sport.RIDE,
            [_summary(181, "Intervals.icu"), _summary(186, "Garmin Connect")],
            NO_CURRENT_INPUTS,
        )

        self.assertEqual((186, "Garmin Connect"), (metric["value"], metric["source"]))

    def test_an_unlabelled_value_is_not_counted(self) -> None:
        metric = _intervals_max_hr_metric(
            "cycling", Sport.RIDE, [{"sport": "ride", "max_hr": 190}], NO_CURRENT_INPUTS
        )

        self.assertIsNone(metric["value"])


if __name__ == "__main__":
    unittest.main()
