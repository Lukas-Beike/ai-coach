"""Threshold running pace reaches planned-unit load estimates."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from backend.canonical.vocabulary import MetricKind, Sport
from backend.planning.planned_unit_load import (
    estimate_planned_unit,
    unit_thresholds,
)

PACE: Any = SimpleNamespace(
    kind=MetricKind.THRESHOLD_PACE, sport=Sport.RUN, value=SimpleNamespace(value=4.0)
)
RIDE_PACE: Any = SimpleNamespace(
    kind=MetricKind.THRESHOLD_PACE, sport=Sport.RIDE, value=SimpleNamespace(value=9.0)
)
RUN = {
    "date": "2026-11-04",
    "sport": "run",
    "planned_duration_s": 3600,
    "description": "- 60m 5:00/km pace",
}


class PlannedUnitPaceTests(unittest.TestCase):
    def test_pace_targeted_run_gets_a_load_with_the_threshold(self) -> None:
        thresholds = unit_thresholds(RUN, [PACE], [])
        self.assertEqual(4.0, thresholds.threshold_speed_mps)
        estimate = estimate_planned_unit(RUN, thresholds)
        self.assertEqual((), estimate.unknown)
        # 5:00/km = 3.33 m/s over 4.0 m/s: intensity 0.833, load 69.4
        self.assertAlmostEqual(69.4, estimate.load or 0.0, places=1)

    def test_pace_targets_stay_unknown_without_the_threshold(self) -> None:
        thresholds = unit_thresholds(RUN, [], [])
        self.assertIsNone(thresholds.threshold_speed_mps)
        estimate = estimate_planned_unit(RUN, thresholds)
        self.assertIsNone(estimate.load)
        self.assertEqual(("missing_threshold_pace",), estimate.unknown)

    def test_speed_is_per_sport(self) -> None:
        both = unit_thresholds(RUN, [RIDE_PACE, PACE], [])
        self.assertEqual(4.0, both.threshold_speed_mps)
        self.assertIsNone(unit_thresholds(RUN, [RIDE_PACE], []).threshold_speed_mps)


if __name__ == "__main__":
    unittest.main()
