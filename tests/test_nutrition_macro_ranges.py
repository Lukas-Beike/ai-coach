import unittest
from unittest.mock import Mock

from backend.nutrition.macro_context import macro_context
from backend.nutrition.macro_ranges import macro_ranges


class MacroRangeTests(unittest.TestCase):
    def workout(self, minutes, high_seconds=0):
        return {
            "date": "2026-11-02",
            "planned_duration_s": minutes * 60,
            "workout_profile": {
                "axis": "duration",
                "segments": [
                    {"duration": high_seconds, "zone": 4},
                    {"duration": minutes * 60 - high_seconds, "zone": 2},
                ],
            },
        }

    def test_weight_duration_and_intensity_boundaries(self):
        for minutes, high, expected in [
            (60, 0, (270, 450)),
            (90, 0, (450, 630)),
            (120, 0, (540, 900)),
            (60, 600, (450, 630)),
            (90, 600, (540, 900)),
        ]:
            with self.subTest(minutes=minutes, high=high):
                ranges = macro_ranges(
                    90, [self.workout(minutes, high)], "2026-11-02", 2700
                )
                self.assertEqual(expected, ranges["carbs_g"])
                self.assertEqual((153, 207), ranges["protein_g"])
                self.assertEqual((60, 90), ranges["fat_g"])

    def test_completed_replaces_plan_and_missing_intensity_is_unknown(self):
        planned = self.workout(120)
        planned["compliance"] = {
            "actual_activity": {
                "date": "2026-11-02",
                "moving_duration_s": 3600,
                "heart_rate_zone_times": [{"id": "Z4", "secs": 600}],
            }
        }
        self.assertEqual(
            (450, 630), macro_ranges(90, [planned], "2026-11-02", 2700)["carbs_g"]
        )
        planned["compliance"]["actual_activity"]["elapsed_duration_s"] = 3600
        planned["compliance"]["actual_activity"].pop("moving_duration_s")
        self.assertEqual(
            (450, 630), macro_ranges(90, [planned], "2026-11-02", 2700)["carbs_g"]
        )
        planned["compliance"]["actual_activity"].pop("heart_rate_zone_times")
        self.assertEqual(
            (270, 450), macro_ranges(90, [planned], "2026-11-02", 2700)["carbs_g"]
        )

    def test_missing_inputs_do_not_invent_ranges(self):
        self.assertEqual({}, macro_ranges(None, None, "2026-11-02", 0))
        self.assertEqual((270, 450), macro_ranges(90, None, "2026-11-02", 0)["carbs_g"])

    def test_multiple_sessions_and_exact_high_intensity_cutoff(self):
        first = self.workout(45, 599)
        second = self.workout(45)
        ranges = macro_ranges(90, [first, second], "2026-11-02", 2700)
        self.assertEqual((450, 630), ranges["carbs_g"])
        first = self.workout(45, 600)
        ranges = macro_ranges(90, [first, second], "2026-11-02", 2700)
        self.assertEqual((540, 900), ranges["carbs_g"])
        first = self.workout(45, 300)
        second = self.workout(45, 300)
        ranges = macro_ranges(90, [first, second], "2026-11-02", 2700)
        self.assertEqual((450, 630), ranges["carbs_g"])

    def test_ambiguous_zone_range_uses_light_fallback(self):
        planned = self.workout(120, 600)
        planned["workout_profile"]["segments"][0]["label"] = "Z3-Z4"
        self.assertEqual(
            (270, 450), macro_ranges(90, [planned], "2026-11-02", 2700)["carbs_g"]
        )

    def test_completed_activity_uses_actual_day_and_skips_missed_plan(self):
        planned = self.workout(60)
        planned["date"] = "2026-11-01"
        planned["compliance"] = {
            "status": "completed",
            "actual_activity": {
                "date": "2026-11-02",
                "moving_duration_s": 7200,
                "heart_rate_zone_times": [{"id": "Z2", "secs": 7200}],
            },
        }
        self.assertEqual(
            (270, 450), macro_ranges(90, [planned], "2026-11-01", 2700)["carbs_g"]
        )
        self.assertEqual(
            (540, 900), macro_ranges(90, [planned], "2026-11-02", 2700)["carbs_g"]
        )
        planned["compliance"] = {"status": "missed"}
        planned["planned_duration_s"] = 7200
        self.assertEqual(
            (270, 450), macro_ranges(90, [planned], "2026-11-01", 2700)["carbs_g"]
        )

    def test_context_keeps_profile_weight_when_plan_is_unavailable(self):
        performance = Mock()
        performance.performance_state.return_value = {"performance": {"metrics": {}}}
        plan = Mock()
        plan.read_public.side_effect = RuntimeError("unavailable")
        profile = Mock()
        profile.get.return_value = {"weight_kg": "90"}
        with self.assertLogs("intervals_coach", level="WARNING"):
            self.assertEqual(
                (90, None),
                macro_context(lambda: performance, lambda: plan, lambda: profile),
            )


if __name__ == "__main__":
    unittest.main()
