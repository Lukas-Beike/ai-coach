from __future__ import annotations

import unittest
from copy import deepcopy

from backend.activities.duplicates import (
    deduplicate_api_records,
    filter_garmin_activities,
    garmin_activity_duplicates_intervals,
    intervals_cycling_activities_match,
    latest_wahoo_garmin_duplicate,
)


class ApiRecordDeduplicationTests(unittest.TestCase):
    def test_keeps_order_and_unidentified_rows(self):
        unidentified = {"name": "no id"}
        scalar = "provider marker"
        records = [
            {"id": 1, "name": "first"},
            {"activityId": "1", "name": "duplicate"},
            unidentified,
            scalar,
            {"external_id": "two"},
            {"id": "two"},
        ]

        result = deduplicate_api_records(records)

        self.assertEqual(result, [records[0], unidentified, scalar, records[4]])
        self.assertIs(result[1], unidentified)


def _garmin(**overrides):
    activity = {
        "activityId": "garmin-1",
        "activityType": "cycling",
        "startTimeLocal": "2026-08-29T07:05:00",
        "duration": 3600,
        "distance": 30_000,
    }
    activity.update(overrides)
    return activity


def _intervals(**overrides):
    activity = {
        "id": "intervals-1",
        "type": "Ride",
        "start_date_local": "2026-08-29T07:00:00",
        "moving_time": 3560,
        "distance": 30_000,
    }
    activity.update(overrides)
    return activity


class GarminDuplicateTests(unittest.TestCase):
    def test_start_boundary_and_sport(self):
        self.assertTrue(garmin_activity_duplicates_intervals(_garmin(), [_intervals()]))
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(startTimeLocal="2026-08-29T07:30:00"), [_intervals()]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(startTimeLocal="2026-08-29T07:31:00"), [_intervals()]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(activityType="running"), [_intervals(type="Ride")]
            )
        )

    def test_duration_and_distance_tolerances_use_reference_and_fixed_floor(self):
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(duration=3_960, distance=33_000),
                [_intervals(moving_time=3_600, distance=30_000)],
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(duration=3_961), [_intervals(moving_time=3_600)]
            )
        )
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(distance=30_501), [_intervals(distance=30_000)]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(distance=33_001), [_intervals(distance=30_000)]
            )
        )

    def test_missing_invalid_and_nonpositive_measurements(self):
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(duration="invalid", distance="invalid"), [_intervals()]
            )
        )
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(distance=0), [_intervals(distance=0)]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(startTimeLocal="not-a-date"), [_intervals()]
            )
        )

    def test_garmin_date_and_measurement_aliases_are_supported(self):
        garmin = _garmin(
            startTimeLocal=None,
            start_time_local="2026-08-29T07:05:00",
            duration=None,
            movingTime=3600,
        )
        self.assertTrue(garmin_activity_duplicates_intervals(garmin, [_intervals()]))

    def test_filter_keeps_dict_entries_and_counts_only_removed_duplicates(self):
        activities = [
            _garmin(),
            "not-an-activity",
            _garmin(activityId="other", distance=1),
        ]
        original = deepcopy(activities)
        kept, removed = filter_garmin_activities(activities, [_intervals()])
        self.assertEqual(
            kept,
            [
                {
                    "activityId": "other",
                    "activityType": "cycling",
                    "startTimeLocal": "2026-08-29T07:05:00",
                    "duration": 3600,
                    "distance": 1,
                }
            ],
        )
        self.assertEqual(removed, 1)
        self.assertEqual(activities, original)


class IntervalsCyclingMatchTests(unittest.TestCase):
    def test_alias_dates_and_duration_fields_match(self):
        left = _intervals(
            start_date_local=None,
            start_date="2026-08-29T07:00:00",
            moving_time=None,
            elapsed_time=3600,
        )
        right = _intervals(
            id="right",
            start_date_local=None,
            start_date="2026-08-29T07:30:00",
            moving_time=None,
            elapsed_time=3600,
        )
        self.assertTrue(intervals_cycling_activities_match(left, right))

    def test_positive_start_duration_distance_are_required(self):
        base = _intervals()
        for field, value in (
            ("start_date_local", "bad"),
            ("moving_time", 0),
            ("distance", -1),
        ):
            with self.subTest(field=field):
                invalid = dict(base)
                invalid[field] = value
                self.assertFalse(intervals_cycling_activities_match(base, invalid))

    def test_noncycling_and_tolerance_mismatch_are_rejected(self):
        self.assertFalse(
            intervals_cycling_activities_match(_intervals(type="Run"), _intervals())
        )
        self.assertFalse(
            intervals_cycling_activities_match(
                _intervals(), _intervals(distance=40_000)
            )
        )


class WahooGarminDuplicateTests(unittest.TestCase):
    def test_wahoo_is_canonical_and_view_limits_fields(self):
        snapshot = {
            "synced_at": "2026-08-29T10:00:00+00:00",
            "raw_provider_data": {
                "activities": [
                    _intervals(
                        id="wahoo",
                        source="Wahoo",
                        name="W" * 300,
                        distance=60_000,
                        moving_time=7200,
                    ),
                    _intervals(
                        id=None,
                        activityId="garmin",
                        source="Garmin",
                        name="G" * 300,
                        distance=59_800,
                        moving_time=7160,
                    ),
                ]
            },
        }
        original = deepcopy(snapshot)
        pair = latest_wahoo_garmin_duplicate(snapshot)
        self.assertEqual(pair["canonical_id"], "wahoo")
        self.assertEqual(pair["duplicate_id"], "garmin")
        self.assertEqual(len(pair["canonical_name"]), 200)
        self.assertEqual(len(pair["duplicate_name"]), 200)
        self.assertLessEqual(len(pair["start_date_local"]), 40)
        self.assertEqual(pair["snapshot_synced_at"], snapshot["synced_at"])
        self.assertEqual(snapshot, original)

    def test_newer_unrelated_activity_blocks_pair(self):
        activities = [
            _intervals(id="wahoo", source="Wahoo"),
            _intervals(activityId="garmin", source="Garmin"),
            _intervals(
                id="new-run",
                source="Garmin",
                type="Run",
                start_date_local="2026-08-30T07:00:00",
            ),
        ]
        self.assertIsNone(
            latest_wahoo_garmin_duplicate(
                {"raw_provider_data": {"activities": activities}}
            )
        )

    def test_missing_or_same_ids_are_rejected(self):
        base = [
            _intervals(id=None, activityId=None, source="Wahoo"),
            _intervals(id=None, activityId=None, source="Garmin"),
        ]
        self.assertIsNone(
            latest_wahoo_garmin_duplicate({"raw_provider_data": {"activities": base}})
        )
        same = [
            _intervals(id="same", source="Wahoo"),
            _intervals(id=None, activityId="same", source="Garmin"),
        ]
        self.assertIsNone(
            latest_wahoo_garmin_duplicate({"raw_provider_data": {"activities": same}})
        )

    def test_snapshot_is_required_and_recent_activities_is_fallback(self):
        with self.assertRaises(TypeError):
            latest_wahoo_garmin_duplicate()  # type: ignore[call-arg]
        activities = [
            _intervals(id="wahoo", source="Wahoo"),
            _intervals(activityId="garmin", source="Garmin"),
        ]
        pair = latest_wahoo_garmin_duplicate({"recent_activities": activities})
        self.assertEqual(pair["canonical_id"], "wahoo")


if __name__ == "__main__":
    unittest.main()
