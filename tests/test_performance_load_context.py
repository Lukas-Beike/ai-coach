import copy
import unittest
from datetime import date, timedelta

from performance_day_support import current_days

from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
)
from backend.performance.load_context import performance_load_context


class PerformanceLoadContextTests(unittest.TestCase):
    def test_rollup_windows_include_boundaries_and_have_previous_windows(self):
        today = date(2026, 9, 30)
        activities = [
            {
                "started_at_local": (today - timedelta(days=offset)).isoformat(),
                "moving_duration_s": 3600,
                "training_load": 10,
            }
            for offset in (0, 6, 7, 29, 30, 36)
        ]
        result = performance_load_context(
            activities, (), today, canonical=EMPTY_PERFORMANCE_INPUTS
        )
        self.assertEqual(result["last_7"]["sessions"], 2)
        self.assertEqual(result["last_7"]["training_load"], 20)
        self.assertEqual(result["previous_7"]["sessions"], 1)
        self.assertEqual(result["last_30"]["sessions"], 4)
        self.assertEqual(result["previous_30"]["sessions"], 2)

    def test_empty_data_and_future_atl_are_excluded(self):
        today = date(2026, 9, 30)
        days = current_days(
            [{"id": (today + timedelta(days=1)).isoformat(), "atl": 50}]
        )
        result = performance_load_context(
            [], days, today, canonical=EMPTY_PERFORMANCE_INPUTS
        )
        self.assertEqual(result["last_7"]["sessions"], 0)
        self.assertIsNone(result["actual_atl_current"])
        self.assertIsNone(result["actual_atl_date"])
        self.assertIsNone(result["actual_atl_average"])

    def test_actual_atl_average_uses_last_seven_days_and_rounds(self):
        today = date(2026, 9, 30)
        days = current_days(
            [
                {"id": (today - timedelta(days=offset)).isoformat(), "atl": value}
                for offset, value in (
                    (6, 10),
                    (5, 11),
                    (4, 12),
                    (3, 13),
                    (2, 14),
                    (1, 15),
                    (0, 16),
                )
            ]
        )
        result = performance_load_context(
            [], days, today, canonical=EMPTY_PERFORMANCE_INPUTS
        )
        self.assertEqual(result["actual_atl_current"], 4.24)
        self.assertEqual(result["actual_atl_date"], today)
        self.assertEqual(result["actual_atl_average"], 6.78)

    def test_load_alias_priority_and_carrier_form_and_ramp_rate_are_ignored(self):
        today = date(2026, 9, 30)
        days = current_days(
            [
                {
                    "id": today.isoformat(),
                    "ctl": "invalid",
                    "ctLoad": 55,
                    "atlLoad": 65,
                    "atl": 65,
                    "tsb": 7,
                    "rampRate": 1.5,
                }
            ]
        )
        load = performance_load_context(
            [], days, today, canonical=EMPTY_PERFORMANCE_INPUTS
        )["load"]
        self.assertEqual(
            load,
            {
                "id": today.isoformat(),
                "ctl": None,
                "atl": None,
                "tsb": None,
                "ramp_rate": None,
                "ramp_rate_source": None,
            },
        )

    def test_form_and_ramp_rate_come_from_the_canonical_inputs(self):
        today = date(2026, 9, 30)
        days = current_days([{"id": today.isoformat(), "ctl": 58.4, "atl": 60}])
        canonical = CanonicalPerformanceInputs(
            wellness_day=today,
            ctl=58.4,
            atl=60.0,
            form_by_day={today: -1.6},
            ramp_rate=4.3,
        )
        load = performance_load_context([], days, today, canonical=canonical)["load"]
        self.assertEqual(load["tsb"], -1.6)
        self.assertEqual(load["ramp_rate"], 4.3)
        self.assertEqual(load["ramp_rate_source"], "Intervals.icu CTL (berechnet)")

    def test_missing_canonical_form_and_ramp_rate_are_unknown(self):
        today = date(2026, 9, 30)
        days = current_days([{"id": today.isoformat(), "tsb": 9, "rampRate": 2}])
        for name, canonical in {
            "no_form_day": CanonicalPerformanceInputs(
                wellness_day=today,
                ctl=50,
                atl=40,
                form_by_day={today - timedelta(days=1): 1.0},
            ),
            "form_not_read": CanonicalPerformanceInputs(
                wellness_day=today, ctl=50, atl=40
            ),
            "no_wellness_day": CanonicalPerformanceInputs(
                wellness_day=None, ctl=None, atl=None, form_by_day={today: 1.0}
            ),
        }.items():
            with self.subTest(name):
                load = performance_load_context([], days, today, canonical=canonical)[
                    "load"
                ]
                self.assertIsNone(load["tsb"])
                self.assertIsNone(load["ramp_rate"])
                self.assertIsNone(load["ramp_rate_source"])

    def test_canonical_ctl_and_atl_override_legacy_when_observed(self):
        today = date(2026, 9, 30)
        days = current_days([{"id": today.isoformat(), "ctl": 55, "atl": 65}])
        canonical = CanonicalPerformanceInputs(wellness_day=today, ctl=60.5, atl=70.25)
        result = performance_load_context([], days, today, canonical=canonical)
        self.assertEqual(result["load"]["ctl"], 60.5)
        self.assertEqual(result["load"]["atl"], 70.25)

    def test_input_data_is_not_mutated(self):
        today = date(2026, 9, 30)
        activities = [{"started_at_local": today.isoformat(), "training_load": 20}]
        days = current_days([{"id": today.isoformat(), "atl": 20, "ctl": 30}])
        before = copy.deepcopy((activities, days))
        performance_load_context(
            activities, days, today, canonical=EMPTY_PERFORMANCE_INPUTS
        )
        self.assertEqual((activities, days), before)


if __name__ == "__main__":
    unittest.main()
