import copy
import unittest
from datetime import date

from backend.performance.wellness import (
    comparison_value,
    readiness_score_value,
    wellness_average,
    wellness_form_average,
    wellness_form_value,
)


class WellnessAverageTests(unittest.TestCase):
    def test_window_is_inclusive_and_anchored(self):
        rows = [
            {"id": "2026-09-08", "sleepSecs": 25200},
            {"id": "2026-09-09", "sleepSecs": 28800},
            {"id": "2026-09-10", "sleepSecs": 32400},
            {"id": "2026-09-11", "sleepSecs": 36000},
            {"id": "2026-09-12", "sleepSecs": 100000},
        ]
        self.assertEqual(
            wellness_average(rows, ("sleepSecs",), 3, date(2026, 9, 10), 3600),
            8.0,
        )

    def test_invalid_dates_and_numbers_are_ignored(self):
        rows = [
            {"id": "not-a-date", "value": 10},
            {"date": "2026-09-09T08:00:00", "value": "bad"},
            {"id": "2026-09-09", "value": "2,5"},
            {"id": "2026-09-10", "value": float("nan")},
            {"id": "2026-09-10", "value": 4},
        ]
        anchor = date(2026, 9, 10)
        self.assertEqual(wellness_average(rows, ("value",), 2, anchor, 2), 1.62)

    def test_zero_id_uses_date_fallback(self):
        rows = [{"id": 0, "date": "2026-09-10", "value": 4}]
        self.assertEqual(wellness_average(rows, ("value",), 1, date(2026, 9, 10)), 4)


class WellnessFormTests(unittest.TestCase):
    def test_direct_form_alias_wins_over_ctl_atl_derivation(self):
        self.assertEqual(wellness_form_value({"tsb": 3, "ctl": 80, "atl": 100}), 3)
        self.assertEqual(wellness_form_value({"form": "-2,5"}), -2.5)
        self.assertEqual(
            wellness_form_value({"freshness": 0, "ctl": 80, "atl": 100}), 0
        )
        self.assertEqual(wellness_form_value({"ctl": 80, "atl": 100}), -20)

    def test_form_average_uses_same_window_and_skips_invalid_rows(self):
        rows = [
            {"id": "2026-09-08", "ctl": 80, "atl": 90},
            {"id": "2026-09-09", "form": 2},
            {"id": "2026-09-10", "ctl": 60, "atl": 70},
            {"id": "2026-09-11", "ctl": 100, "atl": 0},
            {"id": "invalid", "form": 50},
        ]
        self.assertEqual(wellness_form_average(rows, 3, date(2026, 9, 10)), -6)
        self.assertIsNone(wellness_form_average([], 7, date(2026, 9, 10)))


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
