import copy
import unittest
from datetime import date

from backend.performance.trends import garmin_history_average


class GarminHistoryAverageTests(unittest.TestCase):
    def test_inclusive_window_other_keys_and_rounding(self):
        history = {
            "weight_kg": {
                date(2026, 9, 7): 90.0,
                date(2026, 9, 8): 70.0,
                date(2026, 9, 9): 70.5,
                date(2026, 9, 10): 71.0,
                date(2026, 9, 11): 100.0,
            },
            "other": {date(2026, 9, 10): 1.0},
        }
        self.assertEqual(
            garmin_history_average("weight_kg", 3, date(2026, 9, 10), history),
            70.5,
        )
        self.assertIsNone(
            garmin_history_average("missing", 3, date(2026, 9, 10), history)
        )

    def test_empty_history_is_empty(self):
        anchor = date(2026, 9, 10)
        self.assertIsNone(garmin_history_average("weight_kg", 7, anchor, {}))
        self.assertIsNone(
            garmin_history_average("weight_kg", 7, anchor, {"weight_kg": {}})
        )

    def test_end_date_and_history_are_required(self):
        with self.assertRaises(TypeError):
            garmin_history_average("weight_kg", 7, date(2026, 9, 10))


class InputTests(unittest.TestCase):
    def test_inputs_are_not_mutated(self):
        history = {"x": {date(2026, 9, 10): 1.0}}
        before = copy.deepcopy(history)
        garmin_history_average("x", 1, date(2026, 9, 10), history)
        self.assertEqual(history, before)


if __name__ == "__main__":
    unittest.main()
