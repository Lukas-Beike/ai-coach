import copy
import unittest
from datetime import date, timedelta
from inspect import signature

from backend.performance.eftp import eftp_30_day_average


class EftpAggregationTests(unittest.TestCase):
    def test_end_date_is_required_and_both_30_day_boundaries_are_inclusive(self):
        self.assertIs(
            signature(eftp_30_day_average).parameters["end_date"].default,
            signature(eftp_30_day_average).empty,
        )
        anchor = date(2026, 9, 30)
        cutoff = anchor - timedelta(days=29)
        result = eftp_30_day_average(
            [
                {
                    "id": cutoff.isoformat(),
                    "sportInfo": [{"types": ["Ride"], "eFTP": 250}],
                },
                {
                    "id": anchor.isoformat(),
                    "sportInfo": [{"types": ["Ride"], "eFTP": 270}],
                },
                {
                    "id": (cutoff - timedelta(days=1)).isoformat(),
                    "sportInfo": [{"types": ["Ride"], "eFTP": 999}],
                },
                {
                    "id": (anchor + timedelta(days=1)).isoformat(),
                    "sportInfo": [{"types": ["Ride"], "eFTP": 999}],
                },
            ],
            [],
            anchor,
        )
        self.assertEqual(result, 260.0)

    def test_wellness_sport_info_aliases_are_accepted_and_non_cycling_is_ignored(self):
        anchor = date(2026, 9, 30)
        rows = [
            {"id": "2026-09-01", "sport_info": [{"types": ["Bike"], "eftp": 250}]},
            {"id": "2026-09-02", "sportInfo": [{"type": "Rad", "eFTP": 260}]},
            {"id": "2026-09-03", "sportInfo": [{"sport": "Cycling", "eFTP": 270}]},
            {"id": "2026-09-04", "sportInfo": [{"sport_type": "Ride", "eFTP": 280}]},
            {"id": "2026-09-05", "sportInfo": [{"types": ["Run"], "eFTP": 999}]},
        ]
        self.assertEqual(eftp_30_day_average(rows, [], anchor), 265.0)

    def test_activity_type_aliases_and_eftp_key_priority_are_preserved(self):
        anchor = date(2026, 9, 30)
        activities = [
            {
                "start_date_local": "2026-09-01",
                "type": "Ride",
                "icu_eftp": 250,
                "eftp": 999,
            },
            {"start_date_local": "2026-09-02", "sport": "Bike", "eftp": 260},
            {"start_date_local": "2026-09-03", "sport_type": "Rad", "eFTP": 270},
            {"start_date_local": "2026-09-04", "activity_type": "Cycling", "eFTP": 280},
            {"start_date_local": "2026-09-05", "name": "Morning Ride", "eFTP": 290},
            {"start_date_local": "2026-09-06", "type": "Run", "eFTP": 999},
        ]
        self.assertEqual(eftp_30_day_average([], activities, anchor), 270.0)

    def test_invalid_malformed_and_out_of_bounds_values_are_ignored(self):
        anchor = date(2026, 9, 30)
        rows = [
            {"id": "not-a-date", "sportInfo": [{"types": ["Ride"], "eFTP": 250}]},
            {"id": "2026-09-01", "sportInfo": [{"types": ["Ride"], "eFTP": 19}]},
            {"id": "2026-09-02", "sportInfo": [{"types": ["Ride"], "eFTP": 2001}]},
            {"id": "2026-09-03", "sportInfo": [{"types": ["Ride"], "eFTP": "invalid"}]},
            {"id": "2026-09-04", "sportInfo": "malformed", "eFTP": 300},
        ]
        activities = [
            None,
            {"start_date_local": "not-a-date", "type": "Ride", "eFTP": 250},
            {"start_date_local": "2026-09-05", "type": "Ride", "eFTP": 19},
            {"start_date_local": "2026-09-06", "type": "Ride", "eFTP": 2001},
            {"start_date_local": "2026-09-07", "type": "Ride", "eFTP": "invalid"},
            {"start_date_local": "2026-09-08", "type": "Run", "eFTP": 300},
        ]
        self.assertIsNone(eftp_30_day_average(rows, activities, anchor))

    def test_bounded_values_round_average_and_do_not_mutate_inputs(self):
        anchor = date(2026, 9, 30)
        wellness = [
            {"id": "2026-09-01", "sportInfo": [{"types": ["Ride"], "eFTP": "250,4"}]},
        ]
        activities = [
            {"start_date_local": "2026-09-02", "type": "Ride", "icu_eftp": 261},
        ]
        wellness_before = copy.deepcopy(wellness)
        activities_before = copy.deepcopy(activities)
        self.assertEqual(eftp_30_day_average(wellness, activities, anchor), 255.7)
        self.assertEqual(wellness, wellness_before)
        self.assertEqual(activities, activities_before)


if __name__ == "__main__":
    unittest.main()
