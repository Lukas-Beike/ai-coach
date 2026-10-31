from __future__ import annotations

import unittest

from backend.activities.duplicates import (
    deduplicate_api_records,
)
from backend.sync.garmin_activity_duplicates import (
    garmin_activity_duplicates_intervals,
    intervals_cycling_activities_match,
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

    def test_garmin_walk_merges_when_only_the_moving_duration_agrees(self):
        # Garmin duration is elapsed time (4500 s); Intervals reports moving time.
        walk = _garmin(
            activityType="walking",
            duration=4_500,
            movingDuration=3_600,
            distance=5_000,
        )
        copy = _intervals(type="Walk", moving_time=3_620, distance=5_000)
        self.assertTrue(garmin_activity_duplicates_intervals(walk, [copy]))
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                {**walk, "movingDuration": 3_000}, [copy]
            )
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                {key: value for key, value in walk.items() if key != "movingDuration"},
                [copy],
            )
        )

    def test_matching_moving_duration_does_not_override_distance_or_start(self):
        walk = _garmin(duration=4_500, movingDuration=3_600)
        copy = _intervals(moving_time=3_620)
        self.assertTrue(garmin_activity_duplicates_intervals(walk, [copy]))
        self.assertFalse(
            garmin_activity_duplicates_intervals({**walk, "distance": 40_000}, [copy])
        )
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                {**walk, "startTimeLocal": "2026-08-29T07:31:00"}, [copy]
            )
        )

    def test_present_zero_durations_are_still_compared(self):
        # A zero Garmin duration falls back to movingTime, as before.
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(duration=0, movingTime=3_600), [_intervals()]
            )
        )
        # A zero Intervals moving_time is compared as zero; only an agreeing
        # elapsed_time keeps the pair.
        self.assertFalse(
            garmin_activity_duplicates_intervals(
                _garmin(), [_intervals(moving_time=0, elapsed_time=5_000)]
            )
        )
        self.assertTrue(
            garmin_activity_duplicates_intervals(
                _garmin(), [_intervals(moving_time=0, elapsed_time=3_600)]
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


if __name__ == "__main__":
    unittest.main()
