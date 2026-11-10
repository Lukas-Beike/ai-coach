"""Rule contracts of the pure plan checks."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from backend.planning import adaptive, plan_checks

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


def run_done(day, minutes, distance_km=10):
    return {
        "sport": "run",
        "started_at_local": f"{day}T08:00:00",
        "moving_duration_s": minutes * 60,
        "distance_m": distance_km * 1000,
    }


def run_km(local_id, day, km):
    return unit(local_id, day, "run", description=f"- {km}km 70% pace")


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
    def test_run_spike_is_by_distance(self) -> None:
        done = [run_done("2026-10-25", 60)]
        self.assertEqual(
            ["run_spike"], codes(check([run_km("a", "2026-11-05", 11.2)], done))
        )
        self.assertEqual([], check([run_km("a", "2026-11-05", 10.9)], done))

    def test_run_spike_ignores_duration_and_unknown_distance(self) -> None:
        done = [run_done("2026-10-25", 60)]
        self.assertEqual([], check([unit("a", "2026-11-05", "run", 200)], done))

    def test_run_spike_is_graded_and_not_blocking(self) -> None:
        done = [run_done("2026-10-25", 60)]
        notice = check([run_km("a", "2026-11-05", 12)], done)[0]
        warning = check([run_km("a", "2026-11-05", 15)], done)[0]
        self.assertEqual("notice", notice["evidence"]["severity"])
        self.assertEqual("warning", warning["evidence"]["severity"])
        self.assertEqual(50, warning["evidence"]["increase_percent"])
        self.assertFalse(notice["blocking"])
        self.assertIn("observational", notice["evidence_strength"])

    def test_only_illness_blocks(self) -> None:
        self.assertEqual(("illness_hard",), plan_checks.BLOCKING_CODES)
        hard = unit("a", "2026-11-04", "run", planned_intensity=0.9)
        self.assertTrue(check([hard], illness="Fieber")[0]["blocking"])

    def test_run_spike_counts_a_run_completed_today(self) -> None:
        today = [run_done("2026-11-02", 60)]
        self.assertEqual(
            ["run_spike"], codes(check([run_km("a", "2026-11-03", 20)], today))
        )

    def test_run_spike_needs_a_run_in_30_days(self) -> None:
        self.assertEqual([], check([run_km("a", "2026-11-05", 40)]))
        old = [run_done("2026-09-01", 60)]
        self.assertEqual([], check([run_km("a", "2026-11-05", 40)], old))

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
        race = {"event_date": "2026-12-06", "priority": "A", "name": "Race"}
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
            ["illness_hard", "illness_hard"],
            codes(check([hard, long, easy], illness="Fieber")),
        )
        self.assertNotIn("illness_hard", codes(check([hard, long])))
        self.assertEqual([], check([easy], illness="Fieber"))
        far = unit("d", "2026-11-09", "run", planned_intensity=0.9)
        self.assertEqual([], check([far], illness="Fieber"))

    def test_illness_window_is_the_shared_pause_window(self) -> None:
        # TODAY + ILLNESS_DAYS - 1 is the last day of the pause and of the check.
        last = (TODAY + timedelta(days=plan_checks.ILLNESS_DAYS - 1)).isoformat()
        after = (TODAY + timedelta(days=plan_checks.ILLNESS_DAYS)).isoformat()
        end = unit("a", last, "run", planned_intensity=0.9)
        beyond = unit("b", after, "run", planned_intensity=0.9)
        self.assertEqual(["illness_hard"], codes(check([end], illness="Fieber")))
        self.assertEqual([], check([beyond], illness="Fieber"))
        forecast = adaptive.illness_pause_forecast(
            {"illness": "Fieber"},
            TODAY,
            illness_text_limit=1000,
            default_days=adaptive.DEFAULT_ILLNESS_PAUSE_DAYS,
        )
        assert forecast is not None
        self.assertEqual(last, forecast["end_date"])

    def test_taper_finding_keeps_its_identity_when_units_change(self) -> None:
        race = {"event_date": "2026-12-06", "priority": "A"}
        flat = [
            unit(f"u{i}", day, "ride", 60)
            for i, day in enumerate(
                ["2026-11-10", "2026-11-14", "2026-11-24", "2026-11-28"]
            )
        ]
        before = check(flat, competitions=[race])
        after = check([*flat, unit("x", "2026-11-25", "run", 20)], competitions=[race])
        self.assertEqual(
            [plan_checks.finding_key(item) for item in before],
            [plan_checks.finding_key(item) for item in after],
        )

    def test_negated_zone_and_at_most_are_not_hard_or_heavy(self) -> None:
        easy = unit("a", "2026-11-04", "run", description="Locker, bleib unter Z4")
        no_z5 = unit("b", "2026-11-05", "ride", description="kein Z5, nur Z2")
        light = unit("s", "2026-11-04", "strength", description="Rumpf, maximal 30 min")
        self.assertFalse(plan_checks.is_hard(easy))
        self.assertFalse(plan_checks.is_hard(no_z5))
        self.assertFalse(plan_checks.is_heavy_strength(light))
        self.assertTrue(
            plan_checks.is_hard(
                unit("c", "2026-11-06", "run", description="3x8 min Z4")
            )
        )

    def test_aware_and_naive_starts_compare_as_local_times(self) -> None:
        heavy = unit(
            "s",
            "2026-11-04",
            "strength",
            description="Heavy 5x5",
            starts_at_local="2026-11-04T07:00:00+01:00",
        )
        hard = unit(
            "r",
            "2026-11-04",
            "run",
            planned_intensity=0.9,
            starts_at_local="2026-11-04T18:00:00",
        )
        self.assertEqual([], check([heavy, hard]))

    def test_negative_illness_answers_are_not_illness(self) -> None:
        hard = unit("a", "2026-11-04", "run", planned_intensity=0.9)
        for answer in ("keine", "Nein", "-", "gesund", "none"):
            with self.subTest(answer=answer):
                self.assertEqual([], check([hard], illness=answer))

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


class AdjustWeekMoveTests(unittest.TestCase):
    """A missed key session moved to a free day, as the adjust_week playbook asks."""

    week = (
        unit("easy", "2026-11-03", "run", session_focus="easy"),
        unit("long", "2026-11-04", "ride", session_focus="long"),
        unit("legs", "2026-11-06", "strength", session_focus="legs"),
    )

    def test_move_next_to_a_hard_day_is_flagged(self) -> None:
        other = unit("tempo", "2026-11-05", "run", session_focus="threshold")
        moved = unit("key", "2026-11-04", "ride", session_focus="vo2max")
        found = check([*self.week[:1], other, moved])
        self.assertIn("back_to_back_hard", codes(found))

    def test_move_to_a_free_day_is_clean(self) -> None:
        moved = unit("key", "2026-11-05", "ride", session_focus="vo2max")
        legs = unit("legs", "2026-11-06", "strength", session_focus="legs")
        found = check([*self.week[:2], moved, legs])
        self.assertNotIn("back_to_back_hard", codes(found))
        self.assertEqual([], found)

    def test_leg_strength_right_before_the_moved_key_session_is_flagged(self) -> None:
        moved = unit("key", "2026-11-05", "ride", session_focus="vo2max")
        legs = unit(
            "legs",
            "2026-11-04",
            "strength",
            session_focus="legs",
            strength_intensity="heavy",
        )
        found = check([legs, moved])
        self.assertTrue(found)
        self.assertNotIn("back_to_back_hard", codes(found))


class UnknownStartTests(unittest.TestCase):
    def test_synthetic_midnight_start_is_unknown_like_an_unset_start(self) -> None:
        heavy = unit(
            "s",
            "2026-11-04",
            "strength",
            description="Heavy 5x5",
            starts_at_local="2026-11-04T07:00:00",
        )
        hard = unit("r", "2026-11-04", "run", planned_intensity=0.9)
        unset = codes(check([heavy, hard]))
        midnight = {**hard, "starts_at_local": "2026-11-04T00:00:00"}
        self.assertEqual(["strength_hard_same_day"], unset)
        self.assertEqual(unset, codes(check([heavy, midnight])))


if __name__ == "__main__":
    unittest.main()
