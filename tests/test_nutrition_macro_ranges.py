import unittest
from datetime import date
from unittest.mock import Mock

from backend.nutrition.macro_context import body_weight, macro_context
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

    def test_strength_counts_its_total_time_and_other_sports_their_moving_time(self):
        # #2317: rest between sets is part of a strength session's work.
        def completed(sport: str) -> dict:
            planned = self.workout(30)
            planned["compliance"] = {
                "actual_activity": {
                    "date": "2026-11-02",
                    "sport": sport,
                    "elapsed_duration_s": 7200,
                    "moving_duration_s": 1800,
                    "heart_rate_zone_times": [{"id": "Z4", "secs": 600}],
                }
            }
            return planned

        def carbs(minutes: int) -> tuple:
            return macro_ranges(90, [self.workout(minutes, 600)], "2026-11-02", 2700)[
                "carbs_g"
            ]

        self.assertNotEqual(carbs(120), carbs(30))
        for sport, minutes in (("strength", 120), ("run", 30)):
            with self.subTest(sport=sport):
                self.assertEqual(
                    carbs(minutes),
                    macro_ranges(90, [completed(sport)], "2026-11-02", 2700)["carbs_g"],
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
        plan.read_training_day.side_effect = RuntimeError("unavailable")
        profile = Mock()
        profile.get.return_value = {"weight_kg": "90"}
        with self.assertLogs("intervals_coach", level="WARNING"):
            self.assertEqual(
                (90, None),
                macro_context(
                    lambda: performance, lambda: plan, lambda: profile, "2026-11-02"
                ),
            )

    def test_body_weight_keeps_its_source_and_falls_back_to_the_profile(self):
        performance = Mock()
        garmin = {"value": 71.5, "source": "Garmin"}
        performance.performance_state.return_value = {
            "performance": {"metrics": {"weight_kg": garmin}}
        }
        profile = Mock()
        profile.get.return_value = {"weight_kg": "90"}
        self.assertEqual(garmin, body_weight(lambda: performance, lambda: profile))
        performance.performance_state.side_effect = RuntimeError("busy")
        with self.assertLogs("intervals_coach", level="WARNING"):
            self.assertEqual(
                {"value": 90, "source": "Manuell"},
                body_weight(lambda: performance, lambda: profile),
            )
        profile.get.return_value = {}
        with self.assertLogs("intervals_coach", level="WARNING"):
            self.assertIsNone(body_weight(lambda: performance, lambda: profile))

    def test_context_reads_only_the_requested_day_not_the_full_plan(self):
        performance = Mock()
        performance.performance_state.return_value = {
            "performance": {"metrics": {"weight_kg": {"value": 90}}}
        }
        plan = Mock()
        plan.read_training_day.return_value = [self.workout(120)]
        weight, calendar = macro_context(
            lambda: performance, lambda: plan, lambda: Mock(), "2026-11-02"
        )
        self.assertEqual(90, weight)
        plan.read_training_day.assert_called_once_with(date(2026, 11, 2))
        plan.read_public.assert_not_called()
        plan.read.assert_not_called()
        self.assertEqual(
            (540, 900), macro_ranges(weight, calendar, "2026-11-02", 2700)["carbs_g"]
        )


if __name__ == "__main__":
    unittest.main()
