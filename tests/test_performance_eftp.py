import copy
import unittest
from datetime import date, timedelta
from inspect import signature

from backend.performance.eftp import eftp_30_day_average, eftp_daily_values


class EftpAggregationTests(unittest.TestCase):
    def test_end_date_is_required_and_both_30_day_boundaries_are_inclusive(self):
        self.assertIs(
            signature(eftp_30_day_average).parameters["end_date"].default,
            signature(eftp_30_day_average).empty,
        )
        anchor = date(2026, 9, 30)
        cutoff = anchor - timedelta(days=29)
        result = eftp_30_day_average(
            {
                cutoff: 250.0,
                anchor: 270.0,
                cutoff - timedelta(days=1): 999.0,
                anchor + timedelta(days=1): 999.0,
            },
            [],
            anchor,
        )
        self.assertEqual(result, 260.0)

    def test_without_canonical_days_only_activity_eftp_contributes(self):
        anchor = date(2026, 9, 30)
        activities = [
            {"started_at_local": "2026-09-02", "sport": "ride", "eftp_w": 260}
        ]
        self.assertEqual(eftp_30_day_average(None, activities, anchor), 260.0)
        self.assertEqual(eftp_30_day_average({}, activities, anchor), 260.0)
        self.assertIsNone(eftp_30_day_average(None, [], anchor))

    def test_only_ride_summaries_contribute_eftp(self):
        anchor = date(2026, 9, 30)
        activities = [
            {"started_at_local": "2026-09-01", "sport": "ride", "eftp_w": 250},
            {
                "started_at_local": "2026-09-02",
                "sport": "ride",
                "environment": "virtual",
                "eftp_w": 270,
            },
            {"started_at_local": "2026-09-03", "sport": "run", "eftp_w": 999},
            {"started_at_local": "2026-09-04", "eftp_w": 999},
        ]
        self.assertEqual(eftp_30_day_average([], activities, anchor), 260.0)

    def test_invalid_malformed_and_out_of_bounds_values_are_ignored(self):
        anchor = date(2026, 9, 30)
        canonical_days = {
            date(2026, 9, 1): 19.0,
            date(2026, 9, 2): 2001.0,
            date(2026, 9, 3): 20.0,
            date(2026, 9, 4): 2000.0,
        }
        self.assertEqual(
            eftp_daily_values(canonical_days, [], date(2026, 9, 1), anchor),
            {"2026-09-03": 20.0, "2026-09-04": 2000.0},
        )
        activities = [
            None,
            {"started_at_local": "not-a-date", "sport": "ride", "eftp_w": 250},
            {"started_at_local": "2026-09-05", "sport": "ride", "eftp_w": 19},
            {"started_at_local": "2026-09-06", "sport": "ride", "eftp_w": 2001},
            {"started_at_local": "2026-09-07", "sport": "ride", "eftp_w": "invalid"},
            {"started_at_local": "2026-09-08", "sport": "run", "eftp_w": 300},
        ]
        self.assertIsNone(eftp_30_day_average({}, activities, anchor))

    def test_same_day_wellness_and_activity_eftp_count_once_with_wellness_precedence(
        self,
    ):
        anchor = date(2026, 9, 30)
        wellness = {date(2026, 9, 10): 250.0, date(2026, 9, 20): 260.0}
        activities = [
            {"started_at_local": "2026-09-10", "sport": "ride", "eftp_w": 270},
        ]
        self.assertEqual(eftp_30_day_average(wellness, activities, anchor), 255.0)

    def test_daily_values_skip_non_dict_activities(self):
        self.assertEqual(
            eftp_daily_values(
                {},
                [
                    None,
                    "junk",
                    {"started_at_local": "2026-09-10", "sport": "ride", "eftp_w": 260},
                ],
                date(2026, 9, 1),
                date(2026, 9, 30),
            ),
            {"2026-09-10": 260.0},
        )

    def test_round_average_and_do_not_mutate_inputs(self):
        anchor = date(2026, 9, 30)
        wellness = {date(2026, 9, 1): 250.4}
        activities = [
            {"started_at_local": "2026-09-02", "sport": "ride", "eftp_w": 261},
        ]
        wellness_before = copy.deepcopy(wellness)
        activities_before = copy.deepcopy(activities)
        self.assertEqual(eftp_30_day_average(wellness, activities, anchor), 255.7)
        self.assertEqual(wellness, wellness_before)
        self.assertEqual(activities, activities_before)


if __name__ == "__main__":
    unittest.main()
