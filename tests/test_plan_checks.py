"""Rule contracts of the pure plan checks."""

from __future__ import annotations

import unittest
from datetime import date

from backend.planning import plan_checks

TODAY = date(2026, 11, 2)


def unit(local_id, day, sport, minutes=60, **extra):
    return {
        "local_id": local_id,
        "date": day,
        "sport": sport,
        "planned_duration_s": minutes * 60,
        "name": extra.pop("name", "Session"),
        "description": extra.pop("description", "Easy Z2"),
        **extra,
    }


def run_done(day, minutes):
    return {
        "sport": "run",
        "started_at_local": f"{day}T08:00:00",
        "moving_duration_s": minutes * 60,
    }


def check(units, completed=(), competitions=(), illness=""):
    return plan_checks.check_plan(
        today=TODAY,
        units=units,
        completed=list(completed),
        competitions=list(competitions),
        illness=illness,
    )


def codes(findings):
    return [item["code"] for item in findings]


class PlanCheckRuleTests(unittest.TestCase):
    def test_run_spike(self) -> None:
        done = [run_done("2026-10-25", 60)]
        self.assertEqual(
            ["run_spike"], codes(check([unit("a", "2026-11-05", "run", 67)], done))
        )
        self.assertEqual([], check([unit("a", "2026-11-05", "run", 66)], done))

    def test_run_spike_needs_a_run_in_30_days(self) -> None:
        self.assertEqual([], check([unit("a", "2026-11-05", "run", 200)]))
        old = [run_done("2026-09-01", 60)]
        self.assertEqual([], check([unit("a", "2026-11-05", "run", 200)], old))

    def test_back_to_back_hard(self) -> None:
        hard_run = unit("a", "2026-11-04", "run", planned_intensity=0.9)
        hard_ride = unit("b", "2026-11-05", "ride", description="5x4 min Z4")
        found = check([hard_run, hard_ride])
        self.assertEqual(["back_to_back_hard"], codes(found))
        self.assertEqual(["a", "b"], found[0]["local_ids"])

    def test_back_to_back_ignores_unknown_and_gaps(self) -> None:
        first = unit("a", "2026-11-04", "run", planned_intensity=0.9)
        unknown = unit("b", "2026-11-05", "ride", description="Ride")
        gap = unit("c", "2026-11-06", "ride", planned_intensity=88)
        self.assertEqual([], check([first, unknown, gap]))

    def test_strength_hard_same_day(self) -> None:
        heavy = unit("s", "2026-11-04", "strength", description="Heavy 5x5")
        hard = unit("r", "2026-11-04", "run", planned_intensity=0.9)
        self.assertEqual(["strength_hard_same_day"], codes(check([heavy, hard])))
        apart = [
            {**heavy, "starts_at_local": "2026-11-04T07:00:00"},
            {**hard, "starts_at_local": "2026-11-04T17:00:00"},
        ]
        self.assertEqual([], check(apart))
        close = [{**apart[0]}, {**apart[1], "starts_at_local": "2026-11-04T12:00:00"}]
        self.assertEqual(["strength_hard_same_day"], codes(check(close)))

    def test_missing_taper(self) -> None:
        race = {"date": "2026-12-06", "priority": "A", "name": "Race"}
        flat = [
            unit(f"u{i}", day, "ride", 60)
            for i, day in enumerate(
                ["2026-11-10", "2026-11-14", "2026-11-24", "2026-11-28"]
            )
        ]
        self.assertEqual(["missing_taper"], codes(check(flat, competitions=[race])))
        tapered = [*flat[:2], unit("t", "2026-11-28", "ride", 20)]
        self.assertEqual([], check(tapered, competitions=[race]))

    def test_missing_taper_skips_c_races_and_short_plans(self) -> None:
        race = {"date": "2026-12-06", "priority": "C"}
        flat = [unit("a", "2026-11-10", "ride"), unit("b", "2026-11-28", "ride")]
        self.assertEqual([], check(flat, competitions=[race]))
        race["priority"] = "A"
        self.assertEqual([], check(flat[:1], competitions=[race]))

    def test_illness_hard(self) -> None:
        hard = unit("a", "2026-11-04", "run", planned_intensity=0.9)
        long = unit("b", "2026-11-03", "ride", 120)
        easy = unit("c", "2026-11-04", "ride", 45)
        self.assertEqual(
            ["illness_hard"], codes(check([hard, long, easy], illness="Fieber"))
        )
        self.assertNotIn("illness_hard", codes(check([hard, long])))
        self.assertEqual([], check([easy], illness="Fieber"))
        far = unit("d", "2026-11-09", "run", planned_intensity=0.9)
        self.assertEqual([], check([far], illness="Fieber"))

    def test_compliant_mixed_plan_passes(self) -> None:
        done = [run_done("2026-10-28", 60)]
        plan = [
            unit("1", "2026-11-03", "run", 50),
            unit("2", "2026-11-04", "ride", 90, planned_intensity=0.9),
            unit("3", "2026-11-05", "strength", 40, description="Heavy 5x5"),
            unit("4", "2026-11-06", "run", 55),
            unit("5", "2026-11-07", "ride", 120),
        ]
        self.assertEqual([], check(plan, done))


if __name__ == "__main__":
    unittest.main()
