import copy
import unittest

from backend.activities.matching import (
    _activities_by_paired_event_id,
    _paired_activity_match,
    _planned_workout_rows,
    _unpaired_activity_match,
    is_planned_workout_event,
    match_planned_workouts,
    record_date,
)


class ActivityMatchingTests(unittest.TestCase):
    def test_category_and_duration_fallback_match_the_workout_contract(self):
        self.assertTrue(is_planned_workout_event({"category": " workout "}))
        self.assertFalse(
            is_planned_workout_event({"category": "race", "moving_time": 1})
        )
        self.assertTrue(is_planned_workout_event({"moving_time": "1,5"}))
        self.assertTrue(is_planned_workout_event({"elapsed_time": "3600"}))
        self.assertFalse(is_planned_workout_event({"moving_time": "not-a-number"}))
        self.assertFalse(is_planned_workout_event({"moving_time": "nan"}))
        self.assertFalse(is_planned_workout_event("not-a-record"))

    def test_workout_rows_keep_original_indices_and_ignore_malformed_rows(self):
        planned = [
            "not-a-record",
            {"category": "RACE"},
            {"category": "WORKOUT", "id": "workout"},
            {"type": "Run", "moving_time": 1200},
        ]
        self.assertEqual(
            _planned_workout_rows(planned), [(2, planned[2]), (3, planned[3])]
        )

    def test_paired_event_id_has_priority_and_each_activity_is_used_once(self):
        planned = [
            {
                "id": "event-1",
                "category": "WORKOUT",
                "type": "Ride",
                "date": "2026-09-20",
            },
            {
                "id": "event-2",
                "category": "WORKOUT",
                "type": "Run",
                "date": "2026-09-20",
            },
        ]
        activities = [
            {
                "id": "fallback",
                "type": "Run",
                "start_date_local": "2026-09-20T08:00:00",
            },
            {
                "id": "paired",
                "paired_event_id": "event-1",
                "type": "Run",
                "start_date_local": "2026-09-20T20:00:00",
            },
        ]
        result = match_planned_workouts(planned, activities)
        self.assertEqual(result, {0: activities[1], 1: activities[0]})

    def test_paired_activities_are_never_stolen_by_unpaired_fallback(self):
        planned = [
            {
                "id": "event-1",
                "category": "WORKOUT",
                "type": "Ride",
                "date": "2026-09-20",
            },
            {
                "id": "event-2",
                "category": "WORKOUT",
                "type": "Ride",
                "date": "2026-09-20",
            },
        ]
        protected = {
            "id": "protected",
            "paired_event_id": "event-2",
            "type": "Ride",
            "start_date_local": "2026-09-20T08:00:00",
        }
        self.assertEqual(match_planned_workouts(planned, [protected]), {1: protected})

    def test_unpaired_matching_is_same_date_same_sport_and_nearest_start(self):
        event = {
            "category": "WORKOUT",
            "type": "Run",
            "start_date_local": "2026-09-20T10:00:00",
        }
        activities = [
            {"id": "far", "type": "Run", "start_date_local": "2026-09-20T12:00:00"},
            {
                "id": "wrong-date",
                "type": "Run",
                "start_date_local": "2026-09-21T09:59:00",
            },
            {
                "id": "wrong-sport",
                "type": "Ride",
                "start_date_local": "2026-09-20T10:01:00",
            },
            {"id": "near", "type": "Run", "start_date_local": "2026-09-20T10:01:00"},
        ]
        self.assertEqual(
            _unpaired_activity_match(event, activities, set(range(len(activities)))), 3
        )

    def test_unpaired_matching_has_deterministic_index_tie_break(self):
        event = {"type": "Run", "date": "2026-09-20"}
        activities = [
            {"id": "first", "type": "Run", "start_date_local": "2026-09-20"},
            {"id": "second", "type": "Run", "start_date_local": "2026-09-20"},
        ]
        self.assertEqual(_unpaired_activity_match(event, activities, {0, 1}), 0)

    def test_paired_candidates_use_earliest_provider_start(self):
        event = {"id": "event"}
        activities = [
            {
                "id": "later",
                "paired_event_id": "event",
                "start_date_local": "2026-09-20T10:00:00",
            },
            {
                "id": "earlier",
                "paired_event_id": "event",
                "start_date_local": "2026-09-20T09:00:00",
            },
        ]
        self.assertEqual(
            _paired_activity_match(
                event, activities, _activities_by_paired_event_id(activities), {0, 1}
            ),
            1,
        )

    def test_date_only_unit_uses_best_fit_ranking(self):
        def planned(kind, duration, load=None):
            unit = {
                "category": "WORKOUT",
                "type": kind,
                "date": "2026-09-20",
                "moving_time": duration,
            }
            if load is not None:
                unit["icu_training_load"] = load
            return unit

        def activity(kind, start, duration, load=None, **extra):
            row = {
                "type": kind,
                "start_date_local": f"2026-09-20T{start}",
                "moving_time": duration,
                **extra,
            }
            if load is not None:
                row["icu_training_load"] = load
            return row

        midnight_unit = {
            "category": "WORKOUT",
            "type": "Run",
            "start_date_local": "2026-09-20T00:00:00",
            "moving_time": 1800,
        }
        timed_unit = {
            "category": "WORKOUT",
            "type": "Run",
            "start_date_local": "2026-09-20T10:00:00",
            "moving_time": 1800,
        }
        cases = [
            (
                "different sports pick the compatible activity",
                planned("Run", 1800),
                [activity("Ride", "07:00:00", 1800), activity("Run", "09:00:00", 5400)],
                1,
            ),
            (
                "same sport prefers the closer duration",
                planned("Run", 1800),
                [activity("Run", "07:00:00", 5400), activity("Run", "10:00:00", 2100)],
                1,
            ),
            (
                "equal duration is decided by load",
                planned("Ride", 3600, 60),
                [
                    activity("Ride", "07:00:00", 3600, 90),
                    activity("Ride", "10:00:00", 3600, 55),
                ],
                1,
            ),
            (
                "equal duration and load is decided by start time",
                planned("Run", 1800, 30),
                [
                    activity("Run", "11:00:00", 1800, 30),
                    activity("Run", "08:00:00", 1800, 30),
                ],
                1,
            ),
            (
                "ride family includes virtual and e-bike rides",
                planned("VirtualRide", 3600),
                [
                    activity("Ride", "07:00:00", 5400),
                    activity("EBikeRide", "10:00:00", 3600),
                ],
                1,
            ),
            (
                "ride family matches a single virtual ride",
                planned("Ride", 3600),
                [activity("VirtualRide", "10:00:00", 3600)],
                0,
            ),
            (
                "already paired activity is never selected",
                planned("Run", 1800),
                [
                    activity("Run", "08:00:00", 1800, paired_event_id="other-event"),
                    activity("Run", "10:00:00", 5400),
                ],
                1,
            ),
            (
                "single candidate is unchanged",
                planned("Run", 1800),
                [activity("Run", "07:00:00", 9000)],
                0,
            ),
            (
                "local library units rank by duration_minutes",
                {
                    "category": "WORKOUT",
                    "type": "Run",
                    "date": "2026-09-20",
                    "duration_minutes": 30,
                },
                [activity("Run", "07:00:00", 5400), activity("Run", "10:00:00", 1800)],
                1,
            ),
            (
                "midnight placeholder is treated as date-only",
                midnight_unit,
                [activity("Run", "07:00:00", 5400), activity("Run", "10:00:00", 1800)],
                1,
            ),
            (
                "unit with a start time keeps nearest-start matching",
                timed_unit,
                [activity("Run", "12:00:00", 1800), activity("Run", "10:01:00", 5400)],
                1,
            ),
        ]
        for name, event, activities, expected in cases:
            with self.subTest(name):
                self.assertEqual(
                    _unpaired_activity_match(
                        event, activities, set(range(len(activities)))
                    ),
                    expected,
                )

    def test_invalid_timestamps_are_safe_and_inputs_are_not_mutated(self):
        planned = [{"category": "WORKOUT", "type": "Run", "start": "invalid"}]
        activities = [{"id": "bad", "type": "Run", "start": "invalid"}, "ignored"]
        before = copy.deepcopy((planned, activities))
        self.assertEqual(record_date("not-a-date"), "not-a-date")
        self.assertEqual(
            match_planned_workouts(planned, activities), {0: activities[0]}
        )
        self.assertEqual((planned, activities), before)


if __name__ == "__main__":
    unittest.main()
