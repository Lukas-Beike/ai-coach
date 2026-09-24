"""Tests for the pure planning calendar read-model projection."""

from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta

from backend.planning.calendar_read_model import project_planning_calendar


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


if __name__ == "__main__":
    unittest.main()
