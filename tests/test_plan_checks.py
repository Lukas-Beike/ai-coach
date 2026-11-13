"""Rule contracts of the pure plan checks."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from typing import Any

from backend.planning import (
    adaptive,
    adaptive_preview_service,
    intensity_distribution,
    leg_strength,
    load_checks,
    plan_checks,
    plan_guard_service,
    run_lthr,
    season_preparation,
)

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


# The planning day, week, duration and number helpers, recorded before #2110
# merged the identical copies: every copy must give these values.
_DAY_TEXT = (
    load_checks._day,
    plan_checks._day,
    leg_strength._day,
    plan_guard_service._unit_day,
)
_DAY_DATE = (load_checks._unit_date, run_lthr._unit_day)
_MONDAY = (leg_strength._monday, intensity_distribution._monday)
_SECONDS = (leg_strength._seconds, plan_checks._duration_s)
_DAYS: tuple[tuple[dict[str, Any], str], ...] = (
    ({"date": "2026-11-12", "starts_at_local": "2026-11-13T07:00:00"}, "2026-11-12"),
    ({"starts_at_local": "2026-11-13T07:00:00+01:00"}, "2026-11-13"),
    ({"date": "2026-11-15T18:30:00"}, "2026-11-15"),
    ({"date": date(2026, 11, 16)}, "2026-11-16"),
    ({"date": ""}, ""),
    ({}, ""),
    ({"date": "kein Datum"}, "kein Datum"),
)
_SECONDS_CASES: tuple[tuple[dict[str, Any], float], ...] = (
    ({"planned_duration_s": 1800, "duration_minutes": 45}, 1800.0),
    ({"duration_minutes": 45}, 2700.0),
    ({"planned_duration_s": "x", "duration_minutes": "45"}, 0.0),
    ({"duration_minutes": 0}, 0.0),
    ({}, 0.0),
)
_NUMBERS = (
    ("4,5", 4.5),
    ("12", 12),
    (3.333, 3.33),
    ("inf", None),
    (None, None),
    (True, None),
    ("x", None),
    (7.0, 7),
)


class PlanningHelperTests(unittest.TestCase):
    def test_day_week_duration_and_number_helpers_keep_their_values(self) -> None:
        for unit, text in _DAYS:
            day = date.fromisoformat(text) if text[:4].isdigit() else None
            monday = None if day is None else day - timedelta(days=day.weekday())
            checks: tuple[tuple[tuple[Any, ...], Any], ...] = (
                (_DAY_TEXT, text),
                (_DAY_DATE, day),
                (_MONDAY, monday),
            )
            for helpers, expected in checks:
                for helper in helpers:
                    with self.subTest(helper=helper.__qualname__, unit=unit):
                        self.assertEqual(expected, helper(unit))
        for unit, seconds in _SECONDS_CASES:
            for helper in _SECONDS:
                with self.subTest(helper=helper.__qualname__, unit=unit):
                    self.assertEqual(seconds, helper(unit))
        for value, number in _NUMBERS:
            with self.subTest(value=value):
                self.assertEqual(number, adaptive_preview_service._as_number(value))
        self.assertEqual(
            date(2026, 11, 9), season_preparation._week_start(date(2026, 11, 15))
        )
        self.assertEqual(
            date(2026, 11, 16), season_preparation._week_start(date(2026, 11, 16))
        )


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

    def test_a_unit_keeps_its_library_template_and_only_scales_load(self):
        # Athlete rule (#2379): units come only from the library, variants only
        # scale load and intensity; exercise or step changes are new templates.
        press = {"name": "Bankdrücken", "sets": 3, "reps": 8, "kg": 50}
        row = {"name": "Rudern", "sets": 3, "reps": 10, "kg": 40}
        upper = {
            "sport": "strength",
            "name": "Oberkörper",
            "strength_structure": [press, row],
        }
        intervals = {
            "sport": "run",
            "name": "Intervalle",
            "description": "- 10m Z1 HR\n\n4x\n- 4m Z4 HR\n- 2m Z1 HR\n\n- 10m Z1 HR",
        }
        easy = {"sport": "run", "name": "Lockerer Lauf", "description": "- 45m Z2 Pace"}
        templates = {"T-upper": upper, "T-run": intervals, "T-easy": easy}

        def strength(**extra):
            fields = {
                "template_id": "T-upper",
                "strength_structure": [press, row],
                **extra,
            }
            return unit("1", "2026-11-04", "strength", 45, **fields)

        cases = (
            (
                "no template",
                unit("1", "2026-11-04", "strength", 45, strength_structure=[press]),
                "template_missing",
            ),
            ("unknown template", strength(template_id="T-gone"), "template_missing"),
            ("from the template", strength(), None),
            (
                "lighter kg",
                strength(strength_structure=[{**press, "kg": 40}, row]),
                "template_scaled",
            ),
            (
                "fewer sets",
                strength(strength_structure=[press, {**row, "sets": 2}]),
                "template_scaled",
            ),
            (
                "dropped exercise",
                strength(strength_structure=[press]),
                "template_mismatch",
            ),
            (
                "swapped exercise",
                strength(strength_structure=[press, {**row, "name": "Klimmzug"}]),
                "template_mismatch",
            ),
            (
                "reordered",
                strength(strength_structure=[row, press]),
                "template_mismatch",
            ),
            (
                "Garmin pairing only",
                strength(
                    strength_structure=[
                        {**press, "garmin_exercise": "Barbell Bench Press"},
                        row,
                    ]
                ),
                None,
            ),
            (
                "intervals from the template",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    50,
                    template_id="T-run",
                    description=intervals["description"],
                ),
                None,
            ),
            (
                "one more repeat",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    54,
                    template_id="T-run",
                    description=intervals["description"].replace("4x", "5x"),
                ),
                "template_scaled",
            ),
            (
                "other step kind",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    50,
                    template_id="T-run",
                    description="- 50m 70% pace",
                ),
                "template_mismatch",
            ),
            # Athlete decision 2026-11-13 (#2513): time or distance and the
            # target kind are load and intensity; the sections are the structure.
            (
                "8 km by heart rate from a 45 min pace template",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    50,
                    template_id="T-easy",
                    description="- 8km Z2 HR",
                ),
                "template_scaled",
            ),
            (
                "intervals by distance with other targets",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    50,
                    template_id="T-run",
                    description="- 2km Z1 HR\n\n5x\n- 1km Z4 Pace\n- 400m Z1 HR"
                    "\n\n- 2km Z1 Pace",
                ),
                "template_scaled",
            ),
            (
                "warm-up and cool-down inside a steady run",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    45,
                    template_id="T-easy",
                    description="- 1km Z1 HR\n- 6km Z2 HR\n- 1km Z1 HR",
                ),
                "template_scaled",
            ),
            (
                "a repeat block instead of a steady run",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    45,
                    template_id="T-easy",
                    description="- 10m Z1 HR\n\n4x\n- 4m Z4 HR\n- 2m Z1 HR",
                ),
                "template_mismatch",
            ),
            (
                "other sport",
                unit(
                    "2",
                    "2026-11-05",
                    "ride",
                    50,
                    template_id="T-run",
                    description=intervals["description"],
                ),
                "template_mismatch",
            ),
            (
                "adaptive easy swim",
                unit(
                    "2",
                    "2026-11-05",
                    "swim",
                    30,
                    source="adaptive",
                    template_id="T-run",
                ),
                None,
            ),
            (
                "adaptive easy run",
                unit(
                    "2",
                    "2026-11-05",
                    "run",
                    30,
                    source="adaptive",
                    description="- 30m Z1 HR",
                ),
                None,
            ),
        )
        for label, planned, expected in cases:
            with self.subTest(label):
                found = plan_checks.template_conformance([planned], templates)
                self.assertEqual(codes(found), [expected] if expected else [])
                if expected in plan_checks.REQUIRED_CODES:
                    self.assertTrue(found[0]["blocking"])
        # Athlete decision 2026-11-13 (#2512): a clearly described unit gets its
        # template in the same turn; asking is only for an unclear request.
        missing = plan_checks.template_conformance(
            [unit("1", "2026-11-04", "strength", 45, strength_structure=[press])],
            templates,
        )[0]["message"]
        self.assertIn("in the same turn", missing)
        self.assertIn("only when the request leaves the unit unclear", missing)
        # A mismatch shows the Coach what the template keeps and what it wrote.
        dropped = plan_checks.template_conformance(
            [strength(strength_structure=[press])], templates
        )[0]["evidence"]
        self.assertEqual(dropped["template_structure"], ["bankdrücken", "rudern"])
        self.assertEqual(dropped["unit_structure"], ["bankdrücken"])
        # A sport-only mismatch names both sports, the steps being equal.
        ride = unit(
            "2",
            "2026-11-05",
            "ride",
            40,
            template_id="T-run",
            description=intervals["description"],
        )
        sport_only = plan_checks.template_conformance([ride], templates)[0]
        self.assertEqual(sport_only["code"], "template_mismatch")
        self.assertEqual(
            (
                sport_only["evidence"]["template_sport"],
                sport_only["evidence"]["unit_sport"],
            ),
            ("run", "ride"),
        )
        # Moving an older unit keeps its finding, so it never blocks the move.
        older = unit("3", "2026-11-04", "run", 30, description="- 30m Z2 HR")
        moved = {**older, "date": "2026-11-06"}
        keys = [
            plan_checks.finding_key(item)
            for item in plan_checks.template_conformance([older, moved], templates)
        ]
        self.assertEqual(keys[0], keys[1])


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
