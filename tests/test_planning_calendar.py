import unittest
from copy import deepcopy

from backend.planning import calendar


class PlanningCalendarTests(unittest.TestCase):
    def test_date_only_conflict_uses_date_projection(self) -> None:
        conflicts = calendar.calendar_conflicts_for_items(
            {"date": "2026-10-04"},
            [{"event_date": "2026-10-04", "id": "race", "name": "Race"}],
            "local_competition",
        )

        self.assertEqual(
            conflicts,
            [
                {
                    "id": "race",
                    "name": "Race",
                    "date": "2026-10-04",
                    "source": "local_competition",
                    "match": "date",
                    "start_local": None,
                    "end_local": None,
                }
            ],
        )

    def test_date_fallback_applies_when_only_one_event_is_timed(self) -> None:
        conflicts = calendar.calendar_conflicts_for_items(
            {"date": "2026-10-04"},
            [{"start_date_local": "2026-10-04T09:00:00", "duration_minutes": 60}],
            "external",
        )

        self.assertEqual(conflicts[0]["match"], "date")
        self.assertEqual(conflicts[0]["start_local"], "2026-10-04T09:00")

    def test_timed_overlap_and_non_overlap(self) -> None:
        candidate = {
            "start_date_local": "2026-10-04T08:00:00",
            "duration_minutes": 60,
        }
        items = [
            {"start_date_local": "2026-10-04T08:30:00", "duration_minutes": 30},
            {"start_date_local": "2026-10-04T09:01:00", "duration_minutes": 30},
        ]

        conflicts = calendar.calendar_conflicts_for_items(candidate, items, "external")

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["match"], "time_window")

    def test_timed_boundary_touch_is_not_a_conflict(self) -> None:
        conflicts = calendar.calendar_conflicts_for_items(
            {"start_date_local": "2026-10-04T08:00:00", "duration_minutes": 60},
            [{"start_date_local": "2026-10-04T09:00:00", "duration_minutes": 30}],
            "external",
        )

        self.assertEqual(conflicts, [])

    def test_explicit_end_takes_precedence_and_enforces_one_minute(self) -> None:
        conflicts = calendar.calendar_conflicts_for_items(
            {
                "start_date_local": "2026-10-04T08:00:45",
                "end_date_local": "2026-10-04T08:00:00",
                "duration_minutes": 90,
            },
            [{"start_date_local": "2026-10-04T08:00:30", "duration_minutes": 1}],
            "external",
        )

        self.assertEqual(conflicts[0]["start_local"], "2026-10-04T08:00")
        self.assertEqual(conflicts[0]["end_local"], "2026-10-04T08:01")

    def test_moving_time_supplies_duration_in_seconds(self) -> None:
        conflicts = calendar.calendar_conflicts_for_items(
            {"start_date_local": "2026-10-04T08:00:00", "moving_time": 900},
            [{"start_date_local": "2026-10-04T08:14:00", "duration_minutes": 1}],
            "external",
        )

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["end_local"], "2026-10-04T08:15")

    def test_invalid_dates_do_not_create_intervals_or_matches(self) -> None:
        self.assertIsNone(calendar._calendar_interval({"date": "not-a-date"}))
        conflicts = calendar.calendar_conflicts_for_items(
            {"start_date_local": "not-a-date"},
            [{"start_date_local": "2026-10-04T08:00:00"}],
            "external",
        )

        self.assertEqual(conflicts, [])

    def test_timezone_input_keeps_local_wall_time_for_comparison(self) -> None:
        conflicts = calendar.calendar_conflicts_for_items(
            {"start_date_local": "2026-10-04T08:00:00+02:00", "moving_time": 3600},
            [{"start_date_local": "2026-10-04T08:30:00Z", "moving_time": 600}],
            "external",
        )

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["start_local"], "2026-10-04T08:30")
        self.assertEqual(conflicts[0]["end_local"], "2026-10-04T08:40")

    def test_projection_uses_source_match_identity_and_display_fallbacks(self) -> None:
        conflicts = calendar.calendar_conflicts_for_items(
            {"date": "2026-10-04"},
            [{"local_id": "local-1", "event_date": "2026-10-04"}],
            "local_library",
        )

        self.assertEqual(
            conflicts,
            [
                {
                    "id": "local-1",
                    "name": "Einheit",
                    "date": "2026-10-04",
                    "source": "local_library",
                    "match": "date",
                    "start_local": None,
                    "end_local": None,
                }
            ],
        )

    def test_inputs_are_not_mutated(self) -> None:
        candidate = {
            "start_date_local": "2026-10-04T08:00:00Z",
            "duration_minutes": 30,
            "metadata": {"keep": [1, 2]},
        }
        items = [
            {
                "id": "existing",
                "start_date_local": "2026-10-04T08:15:00+02:00",
                "moving_time": 1200,
            }
        ]
        originals = deepcopy((candidate, items))

        calendar.calendar_conflicts_for_items(candidate, items, "external")

        self.assertEqual((candidate, items), originals)


if __name__ == "__main__":
    unittest.main()
