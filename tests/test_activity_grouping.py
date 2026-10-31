import copy
import unittest

from backend.activities.grouping import parallel_cycling_event_groups


class ActivityGroupingTests(unittest.TestCase):
    def test_overlapping_cycling_events_are_grouped_and_sorted(self):
        groups = parallel_cycling_event_groups(
            [
                {
                    "id": "ride-2",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T08:30:00",
                    "planned_duration_s": 3600,
                },
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T08:00:00",
                    "planned_duration_s": 3600,
                },
                {
                    "id": "run-1",
                    "type": "Run",
                    "starts_at_local": "2026-08-30T08:15:00",
                },
            ]
        )
        self.assertEqual(
            [[event["id"] for event in group] for group in groups],
            [["ride-1", "ride-2"]],
        )

    def test_untimed_same_day_events_are_grouped_but_midnight_is_not_explicit(self):
        groups = parallel_cycling_event_groups(
            [
                {"id": "date-only", "type": "Ride", "date": "2026-08-30"},
                {
                    "id": "midnight",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T00:00:00",
                },
                {
                    "id": "later",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T12:00:00",
                },
            ]
        )
        self.assertEqual(
            [[event["id"] for event in group] for group in groups],
            [["date-only", "midnight", "later"]],
        )

    def test_adjacent_explicit_intervals_do_not_overlap(self):
        groups = parallel_cycling_event_groups(
            [
                {
                    "id": "first",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T08:00:00",
                    "planned_duration_s": 3600,
                },
                {
                    "id": "second",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T09:00:00",
                    "planned_duration_s": 1800,
                },
            ]
        )
        self.assertEqual(groups, [])

    def test_transitive_overlap_forms_one_component(self):
        groups = parallel_cycling_event_groups(
            [
                {
                    "id": "middle",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T09:30:00",
                    "planned_duration_s": 3600,
                },
                {
                    "id": "last",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T10:15:00",
                    "planned_duration_s": 3600,
                },
                {
                    "id": "first",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T08:00:00",
                    "planned_duration_s": 7200,
                },
            ]
        )
        self.assertEqual(
            [[event["id"] for event in group] for group in groups],
            [["first", "middle", "last"]],
        )

    def test_invalid_and_non_cycling_events_are_ignored(self):
        self.assertEqual(parallel_cycling_event_groups(None), [])
        self.assertEqual(
            parallel_cycling_event_groups(
                [
                    "not-an-event",
                    {"type": "Ride", "starts_at_local": "2026-08-30T08:00:00"},
                    {
                        "id": "run",
                        "type": "Run",
                        "starts_at_local": "2026-08-30T08:00:00",
                    },
                    {"id": "invalid", "type": "Ride", "starts_at_local": "not-a-date"},
                ]
            ),
            [],
        )

    def test_duration_defaults_to_one_hour_and_positive_duration_has_one_minute_floor(
        self,
    ):
        groups = parallel_cycling_event_groups(
            [
                {
                    "id": "default",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T08:00:00",
                    "planned_duration_s": "invalid",
                },
                {
                    "id": "short",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T08:59:30",
                    "planned_duration_s": 1,
                },
                {
                    "id": "other",
                    "type": "Ride",
                    "starts_at_local": "2026-08-30T12:00:00",
                    "planned_duration_s": None,
                },
            ]
        )
        self.assertEqual(
            [[event["id"] for event in group] for group in groups],
            [["default", "short"]],
        )

    def test_no_input_mutation(self):
        events = [
            {
                "id": "a",
                "type": "Ride",
                "starts_at_local": "2026-08-30T08:00:00",
                "planned_duration_s": 3600,
            },
            {
                "id": "b",
                "type": "Ride",
                "starts_at_local": "2026-08-30T08:30:00",
                "planned_duration_s": 3600,
            },
        ]
        before = copy.deepcopy(events)
        parallel_cycling_event_groups(events)
        self.assertEqual(events, before)


if __name__ == "__main__":
    unittest.main()
