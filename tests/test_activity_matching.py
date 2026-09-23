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
