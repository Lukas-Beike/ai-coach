"""Characterize duplicate matching and calendar projection before refactoring.

The assertions pin the current behavior, quirks included, as the parity
reference for later provider-neutral refactors. Deliberately pinned quirks are
marked with a "Quirk:" comment.
"""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from backend.activities.calendar_projection import (
    calendar_activity_identity,
    calendar_activity_payload,
    planning_compliance_state,
    training_calendar_items,
    workout_compliance,
)
from backend.activities.matching import match_planned_workouts
from backend.planning.calendar_read_model import project_planning_calendar

TODAY = date(2026, 5, 4)
STALE_DUPLICATE_MESSAGE = (
    "Das Wahoo-/Garmin-Duplikat ist nicht mehr aktuell. "
    "Bitte die letzte Einheit erneut analysieren."
)


def _garmin(**overrides: Any) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "activityId": "garmin-1",
        "activityType": "cycling",
        "startTimeLocal": "2026-05-04T07:05:00",
        "duration": 3600,
        "distance": 30_000,
    }
    activity.update(overrides)
    return activity


def _intervals(**overrides: Any) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "id": "intervals-1",
        "type": "Ride",
        "start_date_local": "2026-05-04T07:00:00",
        "moving_time": 3600,
        "distance": 30_000,
    }
    activity.update(overrides)
    return activity


def _planned(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": "event-1",
        "category": "WORKOUT",
        "type": "Ride",
        "starts_at_local": "2026-05-04T09:00:00",
        "planned_duration_s": 3600,
        "name": "Endurance",
    }
    event.update(overrides)
    return event


def _activity(**overrides: Any) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "id": "activity-1",
        "sport": "ride",
        "started_at_local": "2026-05-04T07:00:00",
        "moving_duration_s": 3600,
        "distance_m": 30_000,
        "name": "Morning ride",
    }
    activity.update(overrides)
    return activity


def _unit(name: str, day: str, **overrides: Any) -> dict[str, Any]:
    unit: dict[str, Any] = {
        "id": f"unit-{name}",
        "date": day,
        "starts_at_local": f"{day}T09:00:00",
        "name": name,
        "type": "Ride",
        "planned_duration_s": 3600,
    }
    unit.update(overrides)
    return unit


class MatchingPrecedenceCharacterizationTests(unittest.TestCase):
    def test_paired_activity_ignores_sport_and_calendar_day(self) -> None:
        # Quirk: paired_event_id is trusted without a sport or date check.
        planned = [_planned(id="event", type="Ride", starts_at_local="2026-05-04")]
        paired = _activity(
            id="paired",
            planned_event_id="event",
            sport="run",
            started_at_local="2026-05-06T07:00:00",
        )
        self.assertEqual(match_planned_workouts(planned, [paired]), {0: paired})

    def test_unknown_sport_units_match_only_through_paired_id(self) -> None:
        # Quirk: a unit with an unknown sport never gets a fallback candidate,
        # even when an unpaired same-day activity is also unknown-sport.
        unit = {
            "category": "WORKOUT",
            "type": "Workout",
            "date": "2026-05-04",
            "planned_duration_s": 3600,
        }
        unpaired = {
            "id": "unpaired",
            "sport": "other",
            "started_at_local": "2026-05-04T07:00:00",
        }
        self.assertEqual(match_planned_workouts([unit], [unpaired]), {})

        paired_unknown = {**unpaired, "id": "paired", "planned_event_id": "unit-id"}
        matched = match_planned_workouts([{**unit, "id": "unit-id"}], [paired_unknown])
        self.assertEqual(matched, {0: paired_unknown})

    def test_midnight_units_are_date_only_and_other_starts_are_timed(self) -> None:
        # Two same-day rides: "early" is closest in start time but its duration
        # is a worse fit. Date-only units use best-fit (duration), timed units use
        # nearest start.
        activities = [
            _activity(
                id="early",
                started_at_local="2026-05-04T09:00:00",
                moving_duration_s=1_800,
            ),
            _activity(
                id="late",
                started_at_local="2026-05-04T14:00:00",
                moving_duration_s=3_600,
            ),
        ]
        expectations = (
            ("2026-05-04", "late"),
            ("2026-05-04 00:00", "late"),
            ("2026-05-04T00:00:00.000", "late"),
            ("2026-05-04T00:00:01", "early"),
            ("2026-05-04T09:00:00", "early"),
        )
        for start, expected_id in expectations:
            with self.subTest(start=start):
                unit = {
                    "category": "WORKOUT",
                    "type": "Ride",
                    "starts_at_local": start,
                    "planned_duration_s": 3_600,
                }
                matches = match_planned_workouts([unit], activities)
                self.assertEqual(matches[0]["id"], expected_id)

    def test_offset_aware_activity_start_is_compared_by_its_utc_day(self) -> None:
        # Known defect, pinned as current behavior: an activity at 01:00 on
        # 2026-05-04 with a +02:00 offset is attributed to 2026-05-03 because day
        # matching uses the UTC date.
        unit = {"category": "WORKOUT", "type": "Ride", "date": "2026-05-04"}
        shifted = _activity(started_at_local="2026-05-04T01:00:00+02:00")
        local = _activity(id="local", started_at_local="2026-05-04T01:00:00")
        self.assertEqual(match_planned_workouts([unit], [shifted]), {})
        self.assertEqual(match_planned_workouts([unit], [local]), {0: local})


class CalendarIdentityCharacterizationTests(unittest.TestCase):
    def test_fallback_identity_uses_the_sport_and_drops_negative_metrics(
        self,
    ) -> None:
        identity = calendar_activity_identity(
            {
                "started_at_local": "2026-05-04T07:00:00",
                "sport": "ride",
                "moving_duration_s": -1,
                "distance_m": "12.5",
            }
        )
        self.assertEqual(
            identity,
            ("fallback", "2026-05-04T07:00:00", "ride", None, 12.5),
        )

    def test_fallback_identity_is_case_insensitive_and_start_field_order_is_fixed(
        self,
    ) -> None:
        upper = calendar_activity_identity(
            {
                "started_at_local": "2026-05-04T07:00:00",
                "date": "2026-05-01",
                "sport": "RIDE",
            }
        )
        assert upper is not None
        lower = calendar_activity_identity(
            {"started_at_local": "2026-05-04T07:00:00", "sport": "ride"}
        )
        self.assertEqual(upper, lower)
        self.assertEqual(upper[1], "2026-05-04T07:00:00")

    def test_empty_id_is_skipped(self) -> None:
        self.assertIsNone(calendar_activity_identity({"id": "", "activityId": "x"}))
        self.assertEqual(
            calendar_activity_identity({"id": "act_7"}),
            ("id", "act_7", "", "", ""),
        )


class CompliancePlanningCharacterizationTests(unittest.TestCase):
    def test_status_is_missed_only_for_past_units_without_an_activity(self) -> None:
        past = _planned(starts_at_local="2026-05-03T09:00:00")
        today = _planned(starts_at_local="2026-05-04T09:00:00")
        future = _planned(starts_at_local="2026-05-05T09:00:00")

        self.assertEqual(workout_compliance(past, None, TODAY)["status"], "missed")
        self.assertEqual(workout_compliance(today, None, TODAY)["status"], "planned")
        self.assertEqual(workout_compliance(future, None, TODAY)["status"], "planned")
        self.assertEqual(
            workout_compliance(past, _activity(), TODAY)["status"], "completed"
        )

    def test_missed_unit_scores_zero_and_has_no_basis(self) -> None:
        result = workout_compliance(
            _planned(starts_at_local="2026-05-03T09:00:00"), None, TODAY
        )
        self.assertEqual(result["percentage"], 0)
        self.assertIsNone(result["basis"])
        self.assertIsNone(result["planned_value"])

    def test_zero_planned_load_is_neither_unavailable_nor_scored(self) -> None:
        # Quirk: a planned load of 0 is not "unavailable" (that needs both planned
        # load and planned duration to be missing), and it is not a valid basis.
        result = workout_compliance(
            _planned(planned_load=0, planned_duration_s=None),
            _activity(training_load=40),
            TODAY,
        )
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["basis"])
        self.assertIsNone(result["percentage"])

    def test_load_basis_falls_back_to_duration_when_actual_load_is_missing(
        self,
    ) -> None:
        result = workout_compliance(
            _planned(planned_load=50, planned_duration_s=3_600),
            _activity(moving_duration_s=1_800),
            TODAY,
        )
        self.assertEqual((result["basis"], result["percentage"]), ("duration", 50))

    def test_undated_unit_is_reported_missed_and_left_out_of_weeks(self) -> None:
        # Quirk: an undated unit has an empty date, which sorts before today's
        # ISO string, so it is reported as missed. It cannot be placed in a week.
        enriched, weekly = planning_compliance_state(
            [{"category": "WORKOUT", "type": "Ride", "planned_duration_s": 3_600}],
            [],
            TODAY,
        )
        self.assertEqual(enriched[0]["compliance"]["status"], "missed")
        self.assertEqual(weekly, [])

    def test_non_workout_entries_pass_through_without_compliance(self) -> None:
        race = {"id": "race", "category": "RACE_A", "date": "2026-05-09"}
        enriched, weekly = planning_compliance_state([race], [], TODAY)
        self.assertEqual(enriched, [race])
        self.assertEqual(weekly, [])

    def test_weekly_rows_start_on_monday_and_sunday_belongs_to_previous_week(
        self,
    ) -> None:
        planned = [
            _planned(id="sunday", starts_at_local="2026-05-03T09:00:00"),
            _planned(id="monday", starts_at_local="2026-05-04T09:00:00"),
            _planned(id="next-sunday", starts_at_local="2026-05-10T09:00:00"),
        ]
        _enriched, weekly = planning_compliance_state(planned, [], TODAY)
        self.assertEqual(
            [
                (row["week_start"], row["week_end"], row["planned_units"])
                for row in weekly
            ],
            [("2026-04-27", "2026-05-03", 1), ("2026-05-04", "2026-05-10", 2)],
        )

    def test_weekly_totals_count_missed_units_as_zero_actual(self) -> None:
        planned = [
            _planned(
                id="done",
                starts_at_local="2026-04-27T09:00:00",
                planned_load=50,
            ),
            _planned(
                id="missed",
                starts_at_local="2026-05-03T09:00:00",
                planned_load=50,
            ),
        ]
        activities = [
            _activity(
                id="done-activity",
                planned_event_id="done",
                started_at_local="2026-04-27T09:00:00",
                training_load=40,
            )
        ]
        _enriched, weekly = planning_compliance_state(planned, activities, TODAY)
        self.assertEqual(len(weekly), 1)
        row = weekly[0]
        self.assertEqual(
            (
                row["basis"],
                row["planned_value"],
                row["actual_value"],
                row["percentage"],
            ),
            ("training_load", 100.0, 40.0, 40),
        )
        self.assertEqual(
            (row["planned_units"], row["completed_units"], row["unit_percentage"]),
            (2, 1, 50),
        )

    def test_weekly_basis_falls_back_to_duration_when_any_unit_lacks_load(self) -> None:
        planned = [
            _planned(
                id="with-load",
                starts_at_local="2026-04-28T09:00:00",
                planned_duration_s=3_600,
                planned_load=50,
            ),
            _planned(
                id="duration-only",
                starts_at_local="2026-04-29T09:00:00",
                planned_duration_s=1_800,
            ),
        ]
        activities = [
            _activity(
                id="done",
                planned_event_id="with-load",
                started_at_local="2026-04-28T09:00:00",
                moving_duration_s=3_000,
                training_load=40,
            )
        ]
        _enriched, weekly = planning_compliance_state(planned, activities, TODAY)
        self.assertEqual(weekly[0]["basis"], "duration")
        self.assertEqual(weekly[0]["planned_value"], 5_400.0)
        self.assertEqual(weekly[0]["actual_value"], 3_000.0)
        self.assertEqual(weekly[0]["percentage"], 56)

    def test_weekly_score_is_none_without_a_shared_basis(self) -> None:
        planned = [
            _planned(
                id="bare",
                starts_at_local="2026-04-28T09:00:00",
                planned_duration_s=None,
            )
        ]
        activities = [
            _activity(
                id="done",
                planned_event_id="bare",
                started_at_local="2026-04-28T09:00:00",
            )
        ]
        _enriched, weekly = planning_compliance_state(planned, activities, TODAY)
        self.assertIsNone(weekly[0]["basis"])
        self.assertIsNone(weekly[0]["percentage"])
        self.assertIsNone(weekly[0]["planned_value"])


class TrainingCalendarCharacterizationTests(unittest.TestCase):
    def test_fallback_identity_hides_a_matched_activity_without_an_id(self) -> None:
        activity = {
            "started_at_local": "2026-05-04T07:00:00",
            "sport": "ride",
            "moving_duration_s": 3_600,
            "distance_m": 30_000,
        }
        planned = [
            {
                "id": "event",
                "starts_at_local": "2026-05-04T09:00:00",
                "compliance": {"actual_activity": calendar_activity_payload(activity)},
            }
        ]
        rows = training_calendar_items(planned, [activity])
        self.assertEqual([row["id"] for row in rows], ["event"])

    def test_completed_activity_without_a_start_is_omitted(self) -> None:
        self.assertEqual(training_calendar_items([], [{"id": "a", "type": "Ride"}]), [])

    def test_matched_activity_without_an_id_is_listed_once(self) -> None:
        # The matched copy keeps the sport, so its fallback identity equals the
        # activity's and the activity is not listed a second time.
        activity = {
            "started_at_local": "2026-05-04T07:00:00",
            "sport": "ride",
            "moving_duration_s": 3_600,
            "distance_m": 30_000,
        }
        enriched, _weekly = planning_compliance_state(
            [_planned(id="event", starts_at_local="2026-05-04")], [activity], TODAY
        )
        self.assertIn("actual_activity", enriched[0]["compliance"])
        rows = training_calendar_items(enriched, [activity])
        self.assertEqual([row["id"] for row in rows], ["event"])

    def test_matched_activity_with_an_id_is_listed_once(self) -> None:
        activity = {
            "id": "act_1",
            "started_at_local": "2026-05-04T07:00:00",
            "sport": "ride",
            "moving_duration_s": 3_600,
            "distance_m": 30_000,
        }
        enriched, _weekly = planning_compliance_state(
            [_planned(id="event", starts_at_local="2026-05-04")], [activity], TODAY
        )
        rows = training_calendar_items(enriched, [activity])
        self.assertEqual([row["id"] for row in rows], ["event"])

    def test_rows_sort_by_start_then_casefolded_name_then_id(self) -> None:
        planned = [
            {"id": "p", "name": "Zeta", "starts_at_local": "2026-05-04T09:00:00"}
        ]
        activities = [
            {
                "id": "a-9",
                "name": "alpha",
                "started_at_local": "2026-05-04T09:00:00",
                "sport": "run",
            },
            {
                "id": "a-1",
                "name": "Beta",
                "started_at_local": "2026-05-04T08:00:00",
                "sport": "run",
            },
        ]
        rows = training_calendar_items(planned, activities)
        self.assertEqual([row["name"] for row in rows], ["Beta", "alpha", "Zeta"])

    def test_identical_start_and_name_tie_breaks_by_id(self) -> None:
        activities = [
            {
                "id": "a-2",
                "name": "Same",
                "started_at_local": "2026-05-04T09:00:00",
                "sport": "run",
            },
            {
                "id": "a-1",
                "name": "same",
                "started_at_local": "2026-05-04T09:00:00",
                "sport": "run",
            },
        ]
        rows = training_calendar_items([], activities)
        self.assertEqual([row["id"] for row in rows], ["a-1", "a-2"])


class PlanningCalendarProjectionCharacterizationTests(unittest.TestCase):
    def test_projection_is_local_only_and_never_adds_provider_calendar_rows(
        self,
    ) -> None:
        # Only local planned rows and provider activities are projected. Remote
        # calendar events are never passed in, so remote_count stays 0 and a
        # remote_event_id on a local row does not mark it as linked.
        unit = _unit(
            "Endurance",
            "2026-05-04",
            remote_event_id="intervals-event-9",
        )
        activity = _activity(id="a-1")

        result = project_planning_calendar(
            [unit],
            [activity],
            {},
            [],
            [],
            today=TODAY,
            default_name="Planned workout",
        )

        self.assertEqual(result["planning_view"]["source"], "local")
        self.assertEqual(result["planning_view"]["local_count"], 1)
        self.assertEqual(result["planning_view"]["remote_count"], 0)
        self.assertEqual(len(result["planned"]), 1)
        planned = result["planned"][0]
        self.assertTrue(planned["is_local"])
        self.assertFalse(planned["is_remote"])
        self.assertEqual(planned["sync_source"], "local")
        self.assertEqual(planned["compliance"]["status"], "completed")
        self.assertEqual(
            [row.get("id") for row in result["training_calendar"]],
            [planned["id"]],
        )
        calendar_ids = [item.get("id") for item in result["calendar"]]
        self.assertIn(planned["id"], calendar_ids)
        self.assertEqual(
            [item for item in result["calendar"] if not item.get("is_local")],
            [],
        )


if __name__ == "__main__":
    unittest.main()
