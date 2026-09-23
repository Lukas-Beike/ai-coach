"""Tests for pure season planning projections."""

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import date, timedelta

from backend.planning.season import planning_state, season_plan_summary


class SeasonPlanningTests(unittest.TestCase):
    def test_phase_boundaries(self):
        today = date(2026, 9, 20)
        cases = (
            (-1, "completed"),
            (0, "taper"),
            (14, "taper"),
            (15, "peak"),
            (42, "peak"),
            (43, "build"),
            (84, "build"),
            (85, "base"),
        )
        competitions = [
            {
                "name": str(days),
                "priority": "A",
                "event_date": (today + timedelta(days=days)).isoformat(),
            }
            for days, _ in cases
        ]

        result = season_plan_summary(competitions, today)

        self.assertEqual(
            {int(event["name"]): event["phase"] for event in result["events"]},
            dict(cases),
        )

    def test_ignores_missing_or_invalid_event_dates(self):
        today = date(2026, 9, 20)
        competitions = [
            {"name": "Missing", "priority": "A"},
            {"name": "Invalid", "priority": "A", "event_date": "2026-99-99"},
            {"name": "Wrong type", "priority": "A", "event_date": None},
        ]

        result = season_plan_summary(competitions, today)

        self.assertEqual(result["events"], [])
        self.assertIsNone(result["next_event"])

    def test_sorts_by_event_date_priority_name_and_selects_next_event(self):
        today = date(2026, 9, 20)
        competitions = [
            {"name": "B", "priority": "A", "event_date": "2026-09-22"},
            {"name": "A", "priority": "B", "event_date": "2026-09-22"},
            {"name": "Z", "priority": "A", "event_date": "2026-09-19"},
            {"name": "A", "priority": "A", "event_date": "2026-09-22"},
        ]

        result = season_plan_summary(competitions, today)

        self.assertEqual(
            [
                (event["event_date"], event["priority"], event["name"])
                for event in result["events"]
            ],
            [
                ("2026-09-19", "A", "Z"),
                ("2026-09-22", "A", "A"),
                ("2026-09-22", "A", "B"),
                ("2026-09-22", "B", "A"),
            ],
        )
        self.assertEqual(result["next_event"]["name"], "A")

    def test_empty_competitions(self):
        self.assertEqual(
            season_plan_summary([], date(2026, 9, 20)),
            {"as_of": "2026-09-20", "events": [], "next_event": None},
        )

    def test_planning_state_assembles_values_without_mutating_inputs(self):
        competitions = [{"name": "Race", "priority": "A", "event_date": "2026-09-20"}]
        latest_replan = {"status": "preview", "changes": []}
        adaptive_status = {"needs_replan": True, "replan_changes": 2}
        originals = deepcopy((competitions, latest_replan, adaptive_status))

        result = planning_state(
            competitions,
            date(2026, 9, 20),
            latest_replan,
            adaptive_status,
        )

        self.assertEqual(
            result,
            {
                "season": season_plan_summary(competitions, date(2026, 9, 20)),
                "latest_replan": latest_replan,
                **adaptive_status,
            },
        )
        self.assertEqual((competitions, latest_replan, adaptive_status), originals)


if __name__ == "__main__":
    unittest.main()
