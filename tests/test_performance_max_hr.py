import copy
import math
import unittest

from backend.performance.max_hr import garmin_activity_max_hr, merge_garmin_max_hr


class MaxHrTests(unittest.TestCase):
    def test_activity_sport_and_key_variants_keep_each_sport_maximum(self):
        result = garmin_activity_max_hr(
            [
                {"type": "Ride", "maxHR": 180},
                {"sport": "cycling", "maxHeartRate": "190"},
                {"sport_type": "Run", "max_heartrate": "181,5"},
                {"activityType": "Lauf", "maxHR": 200},
                {"name": "Bike commute", "maxHeartRate": 185},
            ]
        )
        self.assertEqual(result, {"cycling": 190, "running": 200})

    def test_inclusive_bounds_and_invalid_values_are_handled(self):
        result = garmin_activity_max_hr(
            [
                {"type": "Ride", "maxHR": 80},
                {"type": "Ride", "maxHR": 260},
                {"type": "Ride", "maxHR": 79.99},
                {"type": "Ride", "maxHR": 260.01},
                {"type": "Ride", "maxHR": "nan"},
                {"type": "Ride", "maxHR": math.inf},
                {"type": "Ride", "maxHR": "invalid"},
                {"type": "Swimming", "maxHR": 220},
                "not-an-activity",
            ]
        )
        self.assertEqual(result, {"cycling": 260})

    def test_non_list_activity_input_is_empty(self):
        self.assertEqual(garmin_activity_max_hr(None), {})
        self.assertEqual(garmin_activity_max_hr({"type": "Ride", "maxHR": 180}), {})

    def test_merge_uses_previous_then_current_and_keeps_valid_maxima(self):
        result = merge_garmin_max_hr(
            {"cycling": "210,5", "running": 261, "other": 200},
            {"cycling": 180, "running": 190},
        )
        self.assertEqual(result, {"cycling": 210.5, "running": 190})

    def test_merge_ignores_invalid_sources_and_out_of_bounds_values(self):
        result = merge_garmin_max_hr(
            {"cycling": "nan", "running": 79},
            {"cycling": float("inf"), "running": "invalid"},
        )
        self.assertEqual(result, {})
        self.assertEqual(merge_garmin_max_hr(None, [80, 260]), {})

    def test_inputs_are_not_mutated(self):
        activities = [
            {"type": "Ride", "maxHR": 180},
            {"type": "Run", "maxHR": 190},
        ]
        current = {"cycling": 200}
        previous = {"running": 185}
        activities_before = copy.deepcopy(activities)
        current_before = copy.deepcopy(current)
        previous_before = copy.deepcopy(previous)
        garmin_activity_max_hr(activities)
        merge_garmin_max_hr(current, previous)
        self.assertEqual(activities, activities_before)
        self.assertEqual(current, current_before)
        self.assertEqual(previous, previous_before)


if __name__ == "__main__":
    unittest.main()
