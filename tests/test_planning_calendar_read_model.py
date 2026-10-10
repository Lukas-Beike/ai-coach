"""Tests for the pure planning calendar read-model projection."""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta

from backend.planning.calendar_read_model import (
    planned_unit_conflicts,
    project_planning_calendar,
)


def _unit(name, moving_time=3600, *, day="2026-10-12", **extra):
    return {
        "id": f"unit-{name}-{day}",
        "date": day,
        "start_date_local": f"{day}T09:00:00",
        "name": name,
        "type": "Ride",
        "moving_time": moving_time,
        **extra,
    }


def _marker(day="2026-10-12", **flags):
    return {
        "id": f"marker-{day}-{sorted(flags)}",
        "name": "Calendar marker",
        "event_date": day,
        "start_local": f"{day}T00:00:00",
        "end_local": f"{date.fromisoformat(day) + timedelta(days=1)}T00:00:00",
        "training_relevant": 0,
        "no_training": 0,
        "no_intensity": 0,
        "short_only": 0,
        **flags,
    }


def _race(day, priority):
    return {
        "id": f"race-{priority}",
        "name": "Race",
        "event_date": day,
        "priority": priority,
        "category": f"RACE_{priority}",
    }


_REST_UNIT = {
    "id": "rest-unit",
    "date": "2026-10-12",
    "name": "Rest day",
    "duration_minutes": 0,
}


class PlanningCalendarReadModelTests(unittest.TestCase):
    def test_projects_all_calendar_views_without_mutating_inputs(self) -> None:
        today = date(2026, 9, 20)
        today_text = today.isoformat()
        local_planned = [
            {
                "id": "ride-a",
                "date": today_text,
                "start_date_local": f"{today_text}T06:00:00",
                "name": "First ride",
                "type": "Ride",
                "moving_time": 3600,
                "icu_training_load": 100,
            },
            {
                "id": "ride-b",
                "date": today_text,
                "start_date_local": f"{today_text}T06:30:00",
                "name": "Second ride",
                "type": "Ride",
                "moving_time": 3600,
            },
        ]
        activities = [
            {
                "id": "activity-a",
                "paired_event_id": "ride-a",
                "start_date_local": f"{today_text}T06:05:00",
                "name": "Morning ride",
                "type": "Ride",
                "moving_time": 3600,
                "icu_training_load": 120,
            },
            {
                "id": "activity-unmatched",
                "start_date_local": (today + timedelta(days=2)).isoformat()
                + "T07:00:00",
                "name": "Unplanned run",
                "type": "Run",
                "moving_time": 1800,
            },
        ]
        weather = {
            "recommendations": [
                {"event_id": "ride-a", "advice": "Rain jacket"},
                {
                    "date": today_text,
                    "event_name": "Second ride",
                    "advice": "Windy route",
                },
            ]
        }
        competitions = [
            {"id": "race-1", "name": "Local race", "event_date": "2026-09-27"}
        ]
        external_events = [
            {
                "id": "appointment-1",
                "name": "Training relevant appointment",
                "event_date": "2026-09-22",
                "training_relevant": 1,
            },
            {
                "id": "appointment-2",
                "name": "Personal appointment",
                "event_date": "2026-09-23",
                "training_relevant": 0,
            },
        ]
        provider_window = {"start": "2026-09-01", "end": "2026-10-01"}
        originals = copy.deepcopy(
            (local_planned, activities, weather, competitions, external_events)
        )

        result = project_planning_calendar(
            local_planned,
            activities,
            weather,
            competitions,
            external_events,
            today=today,
            provider_window=provider_window,
            default_name="Planned workout",
        )

        self.assertEqual(
            set(result),
            {
                "planned",
                "training_calendar",
                "calendar",
                "planning_view",
                "planning_compliance",
                "parallel_cycling",
            },
        )

        planned_by_id = {item["id"]: item for item in result["planned"]}
        self.assertEqual(set(planned_by_id), {"ride-a", "ride-b"})
        self.assertTrue(all(item["is_local"] for item in planned_by_id.values()))
        self.assertEqual(planned_by_id["ride-a"]["compliance"]["status"], "completed")
        self.assertEqual(planned_by_id["ride-a"]["compliance"]["percentage"], 120)
        self.assertEqual(
            planned_by_id["ride-a"]["weather_recommendation"]["advice"],
            "Rain jacket",
        )
        self.assertEqual(
            planned_by_id["ride-b"]["weather_recommendation"]["advice"],
            "Windy route",
        )

        training_by_id = {item["id"]: item for item in result["training_calendar"]}
        self.assertEqual(
            set(training_by_id), {"ride-a", "ride-b", "activity-unmatched"}
        )
        self.assertEqual(
            training_by_id["activity-unmatched"]["calendar_entry_type"],
            "completed_activity",
        )
        self.assertIn("weather_recommendation", training_by_id["ride-a"])

        calendar_by_id = {item["id"]: item for item in result["calendar"]}
        self.assertEqual(
            set(calendar_by_id),
            {"ride-a", "ride-b", "race-1", "appointment-1"},
        )
        self.assertIn("compliance", calendar_by_id["ride-a"])
        self.assertNotIn("weather_recommendation", calendar_by_id["ride-a"])
        self.assertTrue(calendar_by_id["race-1"]["is_competition"])
        self.assertTrue(calendar_by_id["appointment-1"]["is_external_calendar"])

        planning_view = result["planning_view"]
        self.assertEqual(planning_view["source"], "local")
        self.assertEqual(planning_view["local_count"], 2)
        self.assertEqual(planning_view["remote_count"], 0)
        self.assertIs(planning_view["provider_window"], provider_window)
        self.assertEqual(planning_view["provider_window"], provider_window)
        self.assertIs(planning_view["items"], result["planned"])
        self.assertEqual(result["planning_compliance"][0]["completed_units"], 1)
        self.assertEqual(
            {item["id"] for item in result["parallel_cycling"][0]},
            {"ride-a", "ride-b"},
        )

        self.assertEqual(
            (local_planned, activities, weather, competitions, external_events),
            originals,
        )


class PlannedUnitCalendarConflictTests(unittest.TestCase):
    def test_conflict_rules_follow_marker_and_race_priority_table(self):
        short = _marker(short_only=1)
        cases = [
            (
                "no_training blocks a training unit",
                _unit("Recovery spin"),
                [_marker(no_training=1)],
                [],
                ["no_training"],
            ),
            (
                "no_training allows a rest unit",
                _REST_UNIT,
                [_marker(no_training=1)],
                [],
                [],
            ),
            (
                "no_intensity blocks a hard unit",
                _unit("VO2 intervals"),
                [_marker(no_intensity=1)],
                [],
                ["no_intensity"],
            ),
            (
                "no_intensity allows an explicitly easy unit",
                _unit("Recovery spin"),
                [_marker(no_intensity=1)],
                [],
                [],
            ),
            (
                "short_only blocks a unit above 60 minutes",
                _unit("Recovery spin", 5400),
                [short],
                [],
                ["short_only"],
            ),
            (
                "short_only allows a unit at the 60 minute limit",
                _unit("Recovery spin", 3600),
                [short],
                [],
                [],
            ),
            (
                "A race blocks a hard unit on the day before",
                _unit("VO2 intervals", day="2026-10-13"),
                [],
                [_race("2026-10-14", "A")],
                ["competition_ab"],
            ),
            (
                "B race blocks a hard unit on race day",
                _unit("VO2 intervals", day="2026-10-14"),
                [],
                [_race("2026-10-14", "B")],
                ["competition_ab"],
            ),
            (
                "A race allows a hard unit two days before",
                _unit("VO2 intervals", day="2026-10-12"),
                [],
                [_race("2026-10-14", "A")],
                [],
            ),
            (
                "A race allows an easy unit on the day before",
                _unit("Recovery spin", day="2026-10-13"),
                [],
                [_race("2026-10-14", "A")],
                [],
            ),
            (
                "C race blocks a hard unit on race day",
                _unit("VO2 intervals", day="2026-10-14"),
                [],
                [_race("2026-10-14", "C")],
                ["competition_c"],
            ),
            (
                "C race allows a hard unit on the day before",
                _unit("VO2 intervals", day="2026-10-13"),
                [],
                [_race("2026-10-14", "C")],
                [],
            ),
            (
                "zone 5 in the description makes a generic unit hard",
                _unit("Generic session", 300, day="2026-10-13", description="- 5m Z5"),
                [],
                [_race("2026-10-14", "A")],
                ["competition_ab"],
            ),
            (
                "percentage above 100 in the description makes a generic unit hard",
                _unit(
                    "Generic session", 600, day="2026-10-14", description="- 10m 105%"
                ),
                [],
                [_race("2026-10-14", "B")],
                ["competition_ab"],
            ),
            (
                "zone 2 endurance is not hard and has no race conflict",
                _unit(
                    "Generic session", 3600, day="2026-10-13", description="- 60m Z2"
                ),
                [],
                [_race("2026-10-14", "A")],
                [],
            ),
            (
                "no_intensity stays conservative for a zone 2 unit",
                _unit("Generic session", 3600, description="- 60m Z2 Easy"),
                [_marker(no_intensity=1)],
                [],
                ["no_intensity"],
            ),
            (
                "hard unit without markers or races has no conflict",
                _unit("VO2 intervals"),
                [],
                [],
                [],
            ),
            (
                "marker and race conflicts are reported in source order",
                _unit("VO2 intervals", day="2026-10-14"),
                [_marker(day="2026-10-14", no_intensity=1)],
                [_race("2026-10-14", "A")],
                ["no_intensity", "competition_ab"],
            ),
        ]
        for name, unit, events, competitions, expected in cases:
            with self.subTest(name):
                conflicts = planned_unit_conflicts(unit, events, competitions)
                self.assertEqual([item["code"] for item in conflicts], expected)
                self.assertTrue(all(item["label"] for item in conflicts))

    def test_conflict_labels_are_german_marker_and_race_texts(self):
        conflicts = planned_unit_conflicts(
            _unit("VO2 intervals", 5400, day="2026-10-14"),
            [
                _marker(day="2026-10-14", no_intensity=1),
                _marker(day="2026-10-14", short_only=1),
            ],
            [_race("2026-10-14", "C")],
        )

        self.assertEqual(
            conflicts,
            [
                {"code": "no_intensity", "label": "Keine Intensität"},
                {"code": "short_only", "label": "Nur kurze Einheiten"},
                {
                    "code": "competition_c",
                    "label": "Hartes Training am Tag eines C-Wettkampfs",
                },
            ],
        )

    def test_archived_or_deleted_units_have_no_conflicts(self):
        marked = [_marker(no_training=1)]

        for flag in ("archived", "local_deleted"):
            with self.subTest(flag):
                unit = _unit("Recovery spin", **{flag: True})
                self.assertEqual(planned_unit_conflicts(unit, marked, []), [])

    def test_project_planning_calendar_attaches_conflicts_to_planned_units(self):
        result = project_planning_calendar(
            [_unit("Recovery spin"), _unit("VO2 intervals", day="2026-10-13")],
            [],
            {},
            [_race("2026-10-14", "A")],
            [_marker(no_training=1)],
            today=date(2026, 10, 10),
            provider_window={},
            default_name="Planned workout",
        )

        by_id = {item["id"]: item for item in result["planned"]}
        self.assertEqual(
            by_id["unit-Recovery spin-2026-10-12"]["conflicts"],
            [{"code": "no_training", "label": "Kein Training"}],
        )
        self.assertEqual(
            by_id["unit-VO2 intervals-2026-10-13"]["conflicts"],
            [
                {
                    "code": "competition_ab",
                    "label": "Hartes Training am Vortag oder am Tag eines A/B-Wettkampfs",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
