import copy
import unittest

from backend.performance.wellness import comparison_value
from backend.sync.garmin_performance_history import readiness_score_value


class ReadinessTests(unittest.TestCase):
    def test_nested_latest_sorted_entry_and_standard_fields(self):
        value = [
            {"calendarDate": "2026-09-09", "score": 61},
            {"date": "2026-09-10", "trainingReadiness": {"score": "72"}},
            {"id": "2026-09-08", "value": 40},
        ]
        self.assertEqual(readiness_score_value(value), 72)
        self.assertEqual(
            readiness_score_value(
                {
                    "readinessScore": [
                        {"date": "2026-09-09", "value": 55},
                        {"date": "2026-09-10", "value": 66},
                    ]
                }
            ),
            66,
        )

    def test_empty_and_invalid_readiness_values(self):
        self.assertIsNone(readiness_score_value([]))
        self.assertIsNone(
            readiness_score_value([{"date": "2026-09-10", "score": "bad"}])
        )
        self.assertIsNone(readiness_score_value({"score": float("nan")}))
        self.assertEqual(readiness_score_value({"score": "7,5"}), 7.5)


class ComparisonTests(unittest.TestCase):
    def test_all_direction_and_color_paths(self):
        up = comparison_value(12, 10, "", 7)
        down = comparison_value(8, 10, "", 7)
        flat = comparison_value(10, 10, "", 7)
        lower_good = comparison_value(8, 10, "", 7, higher_is_better=False)
        unknown = comparison_value(12, 10, "", 7, higher_is_better=None)
        self.assertEqual((up["direction"], up["color"]), ("up", "good"))
        self.assertEqual((down["direction"], down["color"]), ("down", "bad"))
        self.assertEqual((flat["direction"], flat["color"]), ("flat", "neutral"))
        self.assertEqual(
            (lower_good["direction"], lower_good["color"]), ("down", "good")
        )
        self.assertEqual((unknown["direction"], unknown["color"]), ("up", "neutral"))
        self.assertEqual(up["label"], "7-Tage-Durchschnitt")
        self.assertEqual(
            comparison_value(1, 2, "bpm", 30, label="vorherige 30 Tage")["label"],
            "vorherige 30 Tage",
        )

    def test_invalid_and_non_mutating_inputs(self):
        current = {"value": "10"}
        average = {"value": "8"}
        before = copy.deepcopy((current, average))
        self.assertIsNone(comparison_value("bad", 8, "", 7))
        self.assertEqual(
            comparison_value(current["value"], average["value"], "", 7)["delta"], 2
        )
        self.assertEqual((current, average), before)


if __name__ == "__main__":
    unittest.main()
