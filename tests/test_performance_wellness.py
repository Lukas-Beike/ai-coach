import copy
import unittest
from datetime import date

from backend.performance.wellness import comparison_value
from backend.sync.garmin_performance_history import current_garmin_metrics


def _readiness(value):
    result = current_garmin_metrics({"readiness": value}, date(2026, 9, 11))
    return result["readiness"]["value"]


class ReadinessTests(unittest.TestCase):
    # The legacy reader's other record shapes (``date``/``id`` keys, nested
    # ``trainingReadiness`` or ``readinessScore``, undated records) are named
    # deviations in test_garmin_health_parity (#2081).
    def test_latest_dated_entry_and_text_values(self):
        value = [
            {"calendarDate": "2026-09-10", "score": "72"},
            {"calendarDate": "2026-09-09", "score": 61},
        ]
        self.assertEqual(_readiness(value), 72)

    def test_empty_and_invalid_readiness_values(self):
        cases = (
            ([], None),
            ([{"calendarDate": "2026-09-10", "score": "bad"}], None),
            ({"calendarDate": "2026-09-10", "score": float("nan")}, None),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(_readiness(value), expected)


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
