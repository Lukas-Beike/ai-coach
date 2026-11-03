"""Tests for pure season planning projections."""

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import date, timedelta

from backend.planning.season import planning_state, season_plan_summary, target_phase


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


class TargetPhaseTests(unittest.TestCase):
    today = date(2026, 9, 20)

    def race(self, weeks, priority="A", extra=0):
        day = self.today + timedelta(weeks=weeks, days=extra)
        return {"name": "R", "priority": priority, "event_date": day.isoformat()}

    def test_no_race_is_unknown(self):
        self.assertEqual({"phase": "unknown"}, target_phase([], self.today))
        self.assertEqual(
            "unknown", target_phase([self.race(4, "C")], self.today)["phase"]
        )

    def test_a_race_phases_and_weeks(self):
        for weeks, phase in ((12, "build"), (4, "peak"), (1, "taper")):
            with self.subTest(weeks=weeks):
                result = target_phase([self.race(weeks)], self.today)
                self.assertEqual(phase, result["phase"])
                self.assertEqual(weeks, result["weeks_to_race"])
                self.assertEqual("A", result["race"]["priority"])

    def test_far_race_is_base(self):
        self.assertEqual("base", target_phase([self.race(20)], self.today)["phase"])

    def test_b_race_only_counts_and_c_is_ignored(self):
        result = target_phase([self.race(2, "C"), self.race(5, "B")], self.today)
        self.assertEqual(("peak", 5), (result["phase"], result["weeks_to_race"]))

    def test_sparse_rows_and_timestamps_are_normalized(self):
        rows = [
            {"event_date": "2026-10-20T09:00:00", "priority": None},
            {"event_date": "2026-10-20", "priority": "A"},
        ]
        result = target_phase(rows, self.today)
        self.assertEqual("peak", result["phase"])
        self.assertEqual("2026-10-20", result["race"]["date"])

    def test_transition_after_recent_race_only(self):
        recent = {"name": "R", "priority": "A", "event_date": "2026-09-01"}
        old = {"name": "R", "priority": "A", "event_date": "2026-06-01"}
        self.assertEqual("transition", target_phase([recent], self.today)["phase"])
        self.assertEqual("unknown", target_phase([old], self.today)["phase"])
        self.assertEqual(
            "peak", target_phase([recent, self.race(5)], self.today)["phase"]
        )


if __name__ == "__main__":
    unittest.main()
