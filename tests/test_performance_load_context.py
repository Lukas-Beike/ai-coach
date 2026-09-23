import copy
import unittest
from datetime import date, timedelta

from backend.performance.load_context import performance_load_context


class PerformanceLoadContextTests(unittest.TestCase):
    def test_rollup_windows_include_boundaries_and_have_previous_windows(self):
        today = date(2026, 9, 30)
        activities = [
            {
                "start_date_local": (today - timedelta(days=offset)).isoformat(),
                "moving_time": 3600,
                "icu_training_load": 10,
            }
            for offset in (0, 6, 7, 29, 30, 36)
        ]
        result = performance_load_context(activities, [], {}, today)
        self.assertEqual(result["last_7"]["sessions"], 2)
        self.assertEqual(result["last_7"]["training_load"], 20)
        self.assertEqual(result["previous_7"]["sessions"], 1)
        self.assertEqual(result["last_30"]["sessions"], 4)
        self.assertEqual(result["previous_30"]["sessions"], 2)

    def test_empty_data_and_future_atl_are_excluded(self):
        today = date(2026, 9, 30)
        result = performance_load_context(
            [],
            [{"id": (today + timedelta(days=1)).isoformat(), "atl": 50}],
            {},
            today,
        )
        self.assertEqual(result["last_7"]["sessions"], 0)
        self.assertIsNone(result["actual_atl_current"])
        self.assertIsNone(result["actual_atl_date"])
        self.assertIsNone(result["actual_atl_average"])

    def test_actual_atl_average_uses_last_seven_days_and_rounds(self):
        today = date(2026, 9, 30)
        wellness_rows = [
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
        result = performance_load_context([], wellness_rows, {}, today)
        self.assertEqual(result["actual_atl_current"], 4.24)
        self.assertEqual(result["actual_atl_date"], today)
        self.assertEqual(result["actual_atl_average"], 6.78)

    def test_load_alias_priority_and_tsb(self):
        today = date(2026, 9, 30)
        latest = {
            "id": today.isoformat(),
            "ctl": "invalid",
            "ctLoad": 55,
            "atlLoad": 65,
            "atl": 65,
            "tsb": "invalid",
            "form": 3,
            "rampRate": "1.5",
        }
        result = performance_load_context([], [], latest, today)
        self.assertEqual(
            result["load"],
            {
                "id": today.isoformat(),
                "ctl": "invalid",
                "atl": 65,
                "tsb": None,
                "rampRate": "1.5",
            },
        )
        latest["ctl"] = 55
        self.assertEqual(
            performance_load_context([], [], latest, today)["load"]["tsb"], -10.0
        )

    def test_input_data_is_not_mutated(self):
        today = date(2026, 9, 30)
        activities = [{"start_date_local": today.isoformat(), "icu_training_load": 20}]
        wellness_rows = [{"id": today.isoformat(), "atl": 20, "ctl": 30}]
        latest = {"id": today.isoformat(), "ctl": 30, "atl": 20}
        before = copy.deepcopy((activities, wellness_rows, latest))
        performance_load_context(activities, wellness_rows, latest, today)
        self.assertEqual((activities, wellness_rows, latest), before)


if __name__ == "__main__":
    unittest.main()
