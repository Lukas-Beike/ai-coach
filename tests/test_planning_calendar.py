import unittest
from copy import deepcopy

from backend.planning import calendar as planning_calendar
from backend.planning import conflicts as planning_conflicts


class PlanningCalendarTests(unittest.TestCase):
    def test_date_only_conflict_uses_date_projection(self) -> None:
        conflicts = planning_conflicts.calendar_conflicts_for_items(
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
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {"date": "2026-10-04"},
            [{"starts_at_local": "2026-10-04T09:00:00", "duration_minutes": 60}],
            "external",
        )

        self.assertEqual(conflicts[0]["match"], "date")
        self.assertEqual(conflicts[0]["start_local"], "2026-10-04T09:00")

    def test_timed_overlap_and_non_overlap(self) -> None:
        candidate = {
            "starts_at_local": "2026-10-04T08:00:00",
            "duration_minutes": 60,
        }
        items = [
            {"starts_at_local": "2026-10-04T08:30:00", "duration_minutes": 30},
            {"starts_at_local": "2026-10-04T09:01:00", "duration_minutes": 30},
        ]

        conflicts = planning_conflicts.calendar_conflicts_for_items(
            candidate, items, "external"
        )

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["match"], "time_window")

    def test_timed_boundary_touch_is_not_a_conflict(self) -> None:
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {"starts_at_local": "2026-10-04T08:00:00", "duration_minutes": 60},
            [{"starts_at_local": "2026-10-04T09:00:00", "duration_minutes": 30}],
            "external",
        )

        self.assertEqual(conflicts, [])

    def test_explicit_end_takes_precedence_and_enforces_one_minute(self) -> None:
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {
                "starts_at_local": "2026-10-04T08:00:45",
                "end_date_local": "2026-10-04T08:00:00",
                "duration_minutes": 90,
            },
            [{"starts_at_local": "2026-10-04T08:00:30", "duration_minutes": 1}],
            "external",
        )

        self.assertEqual(conflicts[0]["start_local"], "2026-10-04T08:00")
        self.assertEqual(conflicts[0]["end_local"], "2026-10-04T08:01")

    def test_moving_time_supplies_duration_in_seconds(self) -> None:
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {"starts_at_local": "2026-10-04T08:00:00", "planned_duration_s": 900},
            [{"starts_at_local": "2026-10-04T08:14:00", "duration_minutes": 1}],
            "external",
        )

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["end_local"], "2026-10-04T08:15")

    def test_invalid_dates_do_not_create_intervals_or_matches(self) -> None:
        self.assertIsNone(planning_conflicts._calendar_interval({"date": "not-a-date"}))
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {"starts_at_local": "not-a-date"},
            [{"starts_at_local": "2026-10-04T08:00:00"}],
            "external",
        )

        self.assertEqual(conflicts, [])

    def test_timezone_input_keeps_local_wall_time_for_comparison(self) -> None:
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {
                "starts_at_local": "2026-10-04T08:00:00+02:00",
                "planned_duration_s": 3600,
            },
            [{"starts_at_local": "2026-10-04T08:30:00Z", "planned_duration_s": 600}],
            "external",
        )

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["start_local"], "2026-10-04T08:30")
        self.assertEqual(conflicts[0]["end_local"], "2026-10-04T08:40")

    def test_projection_uses_source_match_identity_and_display_fallbacks(self) -> None:
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {
                "date": "2026-10-04",
                "starts_at_local": "2026-10-04T08:00:00",
                "duration_minutes": 60,
            },
            [
                {
                    "local_id": "local-1",
                    "starts_at_local": "2026-10-04T08:30:00",
                    "duration_minutes": 30,
                }
            ],
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
                    "match": "time_window",
                    "start_local": "2026-10-04T08:30",
                    "end_local": "2026-10-04T09:00",
                }
            ],
        )

    def test_local_library_date_only_is_not_a_conflict(self) -> None:
        conflicts = planning_conflicts.calendar_conflicts_for_items(
            {"date": "2026-10-04"},
            [{"local_id": "local-1", "event_date": "2026-10-04"}],
            "local_library",
        )
        self.assertEqual(conflicts, [])

    def test_inputs_are_not_mutated(self) -> None:
        candidate = {
            "starts_at_local": "2026-10-04T08:00:00Z",
            "duration_minutes": 30,
            "metadata": {"keep": [1, 2]},
        }
        items = [
            {
                "id": "existing",
                "starts_at_local": "2026-10-04T08:15:00+02:00",
                "planned_duration_s": 1200,
            }
        ]
        originals = deepcopy((candidate, items))

        planning_conflicts.calendar_conflicts_for_items(candidate, items, "external")

        self.assertEqual((candidate, items), originals)


class AdaptiveChangeCalendarBlockedTests(unittest.TestCase):
    @staticmethod
    def change(payload: dict, triggers: list[str], events: list[dict]) -> dict:
        return {
            "payload": payload,
            "blocking_triggers": triggers,
            "external_events": events,
        }

    def test_kept_replacement_is_blocked_by_any_current_marker(self) -> None:
        change = self.change({"duration_minutes": 45}, ["calendar"], [])

        self.assertFalse(planning_calendar.adaptive_change_calendar_blocked(change, []))
        self.assertTrue(
            planning_calendar.adaptive_change_calendar_blocked(
                change, [{"id": "kita", "reason": "short_only"}]
            )
        )

    def test_no_training_archive_needs_its_original_blocker(self) -> None:
        change = self.change(
            {"archived": True},
            ["calendar"],
            [{"id": "travel", "no_training": True}],
        )

        for blockers, blocked in (
            ([], True),
            ([{"id": "other", "reason": "no_training"}], True),
            ([{"id": "travel", "reason": "no_intensity"}], True),
            ([{"id": "travel", "reason": "no_training"}], False),
        ):
            with self.subTest(blockers=blockers):
                self.assertIs(
                    planning_calendar.adaptive_change_calendar_blocked(
                        change, blockers
                    ),
                    blocked,
                )

    def test_illness_archive_beside_an_ordinary_event_is_not_calendar_bound(
        self,
    ) -> None:
        change = self.change(
            {"archived": True},
            ["illness", "calendar"],
            [{"id": "family", "no_training": False, "no_intensity": True}],
        )

        self.assertFalse(planning_calendar.adaptive_change_calendar_blocked(change, []))

    def test_archive_without_calendar_trigger_is_not_calendar_bound(self) -> None:
        change = self.change(
            {"archived": True}, ["illness"], [{"id": "travel", "no_training": True}]
        )

        self.assertFalse(planning_calendar.adaptive_change_calendar_blocked(change, []))


if __name__ == "__main__":
    unittest.main()
