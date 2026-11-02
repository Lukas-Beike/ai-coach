"""Calendar planning uses synthetic events and never sends descriptions."""

import unittest
from datetime import date
from unittest.mock import Mock

from backend.coach.context import CoachPlanningContextReader, coach_context_json_size
from backend.coach.playbooks import playbook_for
from backend.planning.calendar_load import busy_minutes
from backend.planning.plan_checks import check_plan, new_findings
from backend.planning.plan_guard_service import build_planning_brief


class CalendarPlanningTests(unittest.TestCase):
    def test_horizon_projection_and_budget(self):
        reader = Mock()
        reader.list_events_in_window.return_value = [
            {
                "name": f"Event {i}",
                "start_local": "2026-11-03T09:00:00",
                "end_local": "2026-11-03T10:00:00",
                "description": "private description",
            }
            for i in range(300)
        ] + [
            {
                "name": "outside",
                "start_local": "2026-12-09T09:00:00",
                "end_local": "2026-12-09T10:00:00",
            }
        ]
        context = CoachPlanningContextReader(
            Mock(), Mock(), reader, Mock(), Mock(), Mock(), lambda: date(2026, 11, 2)
        )
        result = context.external_calendar(35)
        self.assertGreater(len(result["events"]), 50)
        self.assertEqual(len(result["events"]) + result["omitted_count"], 300)
        self.assertLessEqual(coach_context_json_size(result), 20_000)
        self.assertNotIn("private description", str(result))
        reader.list_events.assert_not_called()
        context.external_calendar()
        reader.list_events.assert_called_once_with(
            limit=50, training_relevant_only=True
        )

    def test_busy_minutes_union_and_midnight(self):
        events = [
            {"start_local": "2026-11-02T09:00:00", "end_local": "2026-11-02T11:00:00"},
            {"start_local": "2026-11-02T10:00:00", "end_local": "2026-11-02T12:00:00"},
            {"start_local": "2026-11-02T23:00:00", "end_local": "2026-11-03T02:00:00"},
        ]
        self.assertEqual(
            busy_minutes(events, date(2026, 11, 2), 2),
            {"2026-11-02": 240, "2026-11-03": 120},
        )
        brief = build_planning_brief(
            progress={},
            completed=[],
            competitions=[],
            training_model="pyramidal",
            today=date(2026, 11, 2),
            calendar_busy=busy_minutes(events, date(2026, 11, 2), 2),
        )
        self.assertEqual(brief["calendar_busy_minutes"]["2026-11-02"], 240)

    def test_calendar_note_for_overlap_or_heavy_day(self):
        unit = {
            "local_id": "a",
            "date": "2026-11-03",
            "starts_at_local": "2026-11-03T09:00:00",
            "sport": "run",
            "planned_duration_s": 3600,
            "planned_intensity": 0.9,
        }
        event = {
            "start_local": "2026-11-03T09:30:00",
            "end_local": "2026-11-03T10:30:00",
        }
        notes = check_plan(
            today=date(2026, 11, 2),
            units=[unit],
            completed=[],
            competitions=[],
            calendar_events=[event],
        )
        note = next(note for note in notes if note["code"] == "calendar_load")
        self.assertFalse(note["blocking"])
        self.assertTrue(note["evidence"]["overlap"])
        event = {
            "start_local": "2026-11-03T10:30:00",
            "end_local": "2026-11-03T18:30:00",
        }
        notes = check_plan(
            today=date(2026, 11, 2),
            units=[unit],
            completed=[],
            competitions=[],
            calendar_events=[event],
        )
        self.assertTrue(any(note["code"] == "calendar_load" for note in notes))

    def test_unknown_time_is_not_claimed_as_overlap_and_increased_risk_is_new(self):
        unit = {
            "local_id": "a",
            "date": "2026-11-03",
            "sport": "run",
            "planned_duration_s": 3600,
            "planned_intensity": 0.9,
        }
        event = {
            "start_local": "2026-11-03T09:00:00",
            "end_local": "2026-11-03T10:00:00",
        }
        args = {
            "today": date(2026, 11, 2),
            "completed": [],
            "competitions": [],
            "calendar_events": [event],
        }
        before = check_plan(units=[unit], **args)
        self.assertFalse(any(note["code"] == "calendar_load" for note in before))
        after = check_plan(
            units=[{**unit, "starts_at_local": "2026-11-03T09:30:00"}], **args
        )
        self.assertTrue(
            any(note["code"] == "calendar_load" for note in new_findings(before, after))
        )

    def test_plan_playbook_requests_clarification(self):
        self.assertIn("whether to train", playbook_for("plan_week"))
        self.assertIn("whether to train", playbook_for("plan_block"))
        self.assertNotIn("whether to train", playbook_for("session_analysis"))


class AllDayEventTests(unittest.TestCase):
    def test_all_day_events_are_not_busy_time(self):
        events = [
            {
                "name": "Holiday",
                "all_day": 1,
                "start_local": "2026-11-03T00:00:00",
                "end_local": "2026-11-04T00:00:00",
            }
        ]
        self.assertEqual(busy_minutes(events, date(2026, 11, 2), 3), {})
