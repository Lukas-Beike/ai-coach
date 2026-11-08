"""Load context: rollups and local fitness (M7); no Intervals.icu history."""

import copy
import unittest
from datetime import date, timedelta

from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
)
from backend.performance.load_context import performance_load_context

TODAY = date(2026, 9, 30)


def _context(activities=(), canonical=EMPTY_PERFORMANCE_INPUTS, today=TODAY):
    return performance_load_context(
        list(activities), today, canonical=canonical, timezone="UTC"
    )


def _loads(days: int, value: float = 50.0) -> dict[str, float]:
    return {
        (TODAY - timedelta(days=offset)).isoformat(): value for offset in range(days)
    }


class PerformanceLoadContextTests(unittest.TestCase):
    def test_rollup_windows_include_boundaries_and_have_previous_windows(self):
        activities = [
            {
                "started_at_local": (TODAY - timedelta(days=offset)).isoformat(),
                "moving_duration_s": 3600,
                "training_load": 10,
            }
            for offset in (0, 6, 7, 29, 30, 36)
        ]
        result = _context(activities)
        self.assertEqual(result["last_7"]["sessions"], 2)
        self.assertEqual(result["last_7"]["training_load"], 20)
        self.assertEqual(result["previous_7"]["sessions"], 1)
        self.assertEqual(result["last_30"]["sessions"], 4)
        self.assertEqual(result["previous_30"]["sessions"], 2)

    def test_load_is_the_latest_local_day(self):
        canonical = CanonicalPerformanceInputs(local_load_days=_loads(150))
        load = _context(canonical=canonical)["load"]
        self.assertEqual(load["id"], TODAY.isoformat())
        self.assertEqual(load["source"], "Lokal berechnet (M7)")
        self.assertEqual(
            (load["method_id"], load["method_version"], load["status"]),
            ("local-fitness-fatigue", 1, "estimate"),
        )
        # A constant 50 TSS per day for 150 days approaches 50 on both curves.
        self.assertAlmostEqual(load["ctl"], 50 * (1 - 0.9764**150), delta=1.0)
        self.assertEqual(load["tsb"], round(load["ctl"] - load["atl"], 1))
        self.assertNotIn("ramp_rate", load)

    def test_averages_cover_the_last_seven_days(self):
        canonical = CanonicalPerformanceInputs(local_load_days=_loads(150))
        load = _context(canonical=canonical)["load"]
        self.assertIsNotNone(load["averages_7d"]["ctl"])
        self.assertLessEqual(load["averages_7d"]["ctl"], load["ctl"])

    def test_without_local_load_the_values_are_unknown(self):
        load = _context()["load"]
        self.assertEqual((load["ctl"], load["atl"], load["tsb"]), (None, None, None))
        self.assertEqual(load["reason"], "no_load")
        self.assertEqual(load["averages_7d"], {"ctl": None, "atl": None, "tsb": None})

    def test_the_inputs_hold_no_intervals_load_and_the_context_no_history(self):
        result = _context(canonical=CanonicalPerformanceInputs())
        self.assertIsNone(result["load"]["ctl"])
        self.assertNotIn("intervals_history", result)
        for name in ("wellness_day", "ctl", "atl", "form_by_day"):
            self.assertFalse(hasattr(CanonicalPerformanceInputs(), name), name)

    def test_unloaded_sessions_mark_the_incomplete_days(self):
        canonical = CanonicalPerformanceInputs(local_load_days=_loads(150))
        strength = {
            "id": "gym",
            "sport": "strength",
            "started_at_local": f"{(TODAY - timedelta(days=2)).isoformat()}T18:00:00",
            "elapsed_duration_s": 2700,
        }
        load = _context([strength], canonical=canonical)["load"]
        self.assertEqual(load["incomplete_days_7d"], 1)

    def test_input_data_is_not_mutated(self):
        activities = [{"started_at_local": TODAY.isoformat(), "training_load": 20}]
        loads = _loads(10)
        before = copy.deepcopy((activities, loads))
        _context(activities, CanonicalPerformanceInputs(local_load_days=loads))
        self.assertEqual((activities, loads), before)


if __name__ == "__main__":
    unittest.main()
