import math
import unittest
from datetime import date
from inspect import signature

from backend.performance.load import activity_rollup, actual_atl_series


class PerformanceLoadTests(unittest.TestCase):
    def test_activity_rollup_has_required_end_date_and_includes_boundaries(self):
        self.assertIs(
            signature(activity_rollup).parameters["end_date"].default,
            signature(activity_rollup).empty,
        )
        anchor = date(2026, 9, 12)
        result = activity_rollup(
            [
                {
                    "start_date_local": "2026-09-11T07:00:00",
                    "moving_time": 1800,
                    "icu_training_load": 10,
                },
                {
                    "start_date_local": "2026-09-12",
                    "moving_time": "3600",
                    "icu_training_load": "42.5",
                },
                {
                    "start_date_local": "2026-09-10",
                    "moving_time": 999,
                    "icu_training_load": 99,
                },
            ],
            2,
            anchor,
        )
        self.assertEqual(
            result,
            {"days": 2, "sessions": 2, "duration_hours": 1.5, "training_load": 52.5},
        )

    def test_activity_rollup_ignores_invalid_rows_and_sums_multiple_loads_per_day(self):
        anchor = date(2026, 9, 12)
        activities = [
            {
                "start_date_local": "2026-09-12",
                "moving_time": "invalid",
                "icu_training_load": None,
            },
            {
                "start_date_local": "not-a-date",
                "moving_time": 7200,
                "icu_training_load": 90,
            },
            {
                "start_date_local": "2026-09-11",
                "moving_time": 1800,
                "icu_training_load": 10,
            },
            {
                "start_date_local": "2026-09-11",
                "moving_time": 1800,
                "icu_training_load": 15,
            },
            "not-an-activity",
        ]
        original = [row.copy() if isinstance(row, dict) else row for row in activities]
        self.assertEqual(
            activity_rollup(activities, 2, anchor),
            {
                "days": 2,
                "sessions": 3,
                "duration_hours": 1.0,
                "training_load": 25.0,
            },
        )
        self.assertEqual(activities, original)

    def test_empty_and_invalid_wellness_data_are_empty(self):
        end_date = date(2026, 9, 12)
        self.assertIs(
            signature(actual_atl_series).parameters["end_date"].default,
            signature(actual_atl_series).empty,
        )
        self.assertEqual(actual_atl_series([], [], end_date), {})
        self.assertEqual(
            actual_atl_series(
                [
                    {"id": "not-a-date", "atl": 10},
                    {"id": end_date.isoformat(), "atl": "invalid"},
                    "not-a-row",
                ],
                [],
                end_date,
            ),
            {},
        )

    def test_actual_atl_uses_completed_load_only_and_sums_same_day(self):
        end_date = date(2026, 9, 12)
        wellness = [
            {"id": "2026-09-10", "atl": 10},
            {"id": "2026-09-12", "atl": 20},
        ]
        activities = [
            {"start_date_local": "2026-09-12T08:00:00", "icu_training_load": 50},
            {"start_date_local": "2026-09-12T18:00:00", "icu_training_load": 20},
            {"start_date_local": "2026-09-13", "icu_training_load": 999},
            {"start_date_local": "not-a-date", "icu_training_load": 999},
        ]
        retention = math.exp(-1 / 7)
        decay = 1 - retention
        expected = (10 * retention * retention) + 70 * decay
        self.assertEqual(
            actual_atl_series(wellness, activities, end_date),
            {
                date(2026, 9, 10): 10.0,
                date(2026, 9, 12): round(expected, 2),
            },
        )

    def test_actual_atl_decays_across_missing_days_and_is_sorted(self):
        end_date = date(2026, 9, 12)
        wellness = [
            {"id": "2026-09-12", "atl": 40},
            {"id": "2026-09-01", "atl": 10},
            {"id": "2026-09-08", "atl": 20},
        ]
        series = actual_atl_series(wellness, [], end_date)
        self.assertEqual(
            list(series), [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 12)]
        )
        retention = math.exp(-1 / 7)
        self.assertEqual(series[date(2026, 9, 8)], round(10 * retention**7, 2))
        self.assertEqual(series[date(2026, 9, 12)], round(10 * retention**11, 2))
        self.assertEqual(
            wellness,
            [
                {"id": "2026-09-12", "atl": 40},
                {"id": "2026-09-01", "atl": 10},
                {"id": "2026-09-08", "atl": 20},
            ],
        )


if __name__ == "__main__":
    unittest.main()
