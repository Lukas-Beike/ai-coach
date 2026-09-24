import copy
import unittest
from datetime import date

from backend.performance.trends import (
    garmin_history_average,
    intervals_performance_average,
)


class GarminHistoryAverageTests(unittest.TestCase):
    def test_inclusive_window_invalid_rows_keys_and_rounding(self):
        rows = [
            {"date": "2026-09-08", "metrics": {"weight_kg": 70}},
            {"date": "2026-09-09T08:00:00", "metrics": {"weight_kg": "70,5"}},
            {"date": "2026-09-10", "metrics": {"weight_kg": 71}},
            {"date": "2026-09-11", "metrics": {"weight_kg": 100}},
            {"date": "invalid", "metrics": {"weight_kg": 60}},
            {"date": "2026-09-10", "metrics": {"other": 1}},
            "not-a-row",
        ]
        snapshot = {"performance_history": rows}
        self.assertEqual(
            garmin_history_average(snapshot, "weight_kg", 3, date(2026, 9, 10)),
            70.5,
        )
        self.assertIsNone(
            garmin_history_average(snapshot, "missing", 3, date(2026, 9, 10))
        )

    def test_empty_or_non_list_history_is_empty(self):
        anchor = date(2026, 9, 10)
        self.assertIsNone(garmin_history_average({}, "weight_kg", 7, anchor))
        self.assertIsNone(
            garmin_history_average({"performance_history": {}}, "weight_kg", 7, anchor)
        )

    def test_end_date_is_required(self):
        with self.assertRaises(TypeError):
            garmin_history_average({}, "weight_kg", 7)
        with self.assertRaises(TypeError):
            intervals_performance_average([], "weight_kg", 7)


class IntervalsPerformanceAverageTests(unittest.TestCase):
    def test_candidate_classes_sport_aliases_pace_zone2_readiness_and_bounds(self):
        rows = [
            {
                "id": "2026-09-08",
                "weight": 70,
                "readinessScore": "80",
                "sportInfo": [
                    {"types": ["Ride"], "ftp": 280, "lthr": 160, "vo2max": 55},
                    {
                        "type": "Lauf",
                        "ftp": 300,
                        "threshold_pace": 3.3333,
                        "zone2Pace": 2.5,
                        "lthr": 175,
                        "vo2max": 58,
                    },
                ],
            },
            {
                "id": "2026-09-09",
                "sport_info": [
                    {"sport": "cycling", "indoor_ftp": 290, "vo2_max": 56, "lthr": 162},
                    {
                        "sport_type": "run",
                        "eFTP": 310,
                        "threshold_pace": 300,
                        "zone_2_pace": 400,
                        "lthr": 176,
                        "running_vo2max": 59,
                    },
                ],
                "training_readiness": {"score": 82},
                "weight": 71,
            },
            {
                "id": "2026-09-10",
                "sport_info": [
                    {"types": ["Ride"], "ftp": 300},
                    {"types": ["Run"], "threshold_pace": 10, "zone2_pace": 10},
                ],
                "readiness": 84,
                "weight": 72,
            },
            {"id": "2026-09-11", "weight": 999999},
        ]
        anchor = date(2026, 9, 10)
        self.assertEqual(
            intervals_performance_average(rows, "cycling_ftp_watts", 3, anchor),
            290,
        )
        self.assertEqual(
            intervals_performance_average(rows, "bike_threshold_hr_bpm", 3, anchor),
            161,
        )
        self.assertEqual(
            intervals_performance_average(rows, "cycling_vo2max_ml_kg_min", 3, anchor),
            55.5,
        )
        self.assertEqual(
            intervals_performance_average(rows, "run_threshold_watts", 3, anchor),
            305,
        )
        self.assertEqual(
            intervals_performance_average(
                rows, "run_threshold_pace_seconds_per_km", 3, anchor
            ),
            round((round(1000 / 3.3333) + 300) / 2, 2),
        )
        self.assertEqual(
            intervals_performance_average(
                rows, "run_zone2_pace_seconds_per_km", 3, anchor
            ),
            round((400) / 1, 2),
        )
        self.assertEqual(
            intervals_performance_average(rows, "readiness", 3, anchor),
            82,
        )
        self.assertEqual(
            intervals_performance_average(rows, "run_threshold_hr_bpm", 3, anchor),
            175.5,
        )
        self.assertEqual(
            intervals_performance_average(rows, "running_vo2max_ml_kg_min", 3, anchor),
            58.5,
        )
        self.assertEqual(
            intervals_performance_average(rows, "weight_kg", 3, anchor), 71
        )

    def test_invalid_dates_values_and_window_boundaries(self):
        rows = [
            {"id": "2026-09-07", "weight": 60},
            {"id": "2026-09-08", "weight": "bad"},
            {"id": "2026-09-09", "weight": 70},
            {"date": "2026-09-10", "weight": 72},
            {"id": "invalid", "weight": 80},
            {"id": "2026-09-11", "weight": 100},
        ]
        self.assertEqual(
            intervals_performance_average(rows, "weight_kg", 3, date(2026, 9, 10)),
            71,
        )
        self.assertIsNone(
            intervals_performance_average(rows, "unknown", 3, date(2026, 9, 10))
        )

    def test_inputs_are_not_mutated(self):
        rows = [
            {
                "id": "2026-09-10",
                "weight": 70,
                "sport_info": [{"type": "Run", "threshold_pace": 3}],
            }
        ]
        snapshot = {
            "performance_history": [{"date": "2026-09-10", "metrics": {"x": 1}}]
        }
        before = copy.deepcopy((rows, snapshot))
        intervals_performance_average(
            rows, "run_threshold_pace_seconds_per_km", 1, date(2026, 9, 10)
        )
        garmin_history_average(snapshot, "x", 1, date(2026, 9, 10))
        self.assertEqual((rows, snapshot), before)


if __name__ == "__main__":
    unittest.main()
