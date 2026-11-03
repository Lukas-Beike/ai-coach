"""Leg strength classification, weekly counts and plan notes."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from backend.planning import leg_strength, plan_checks
from backend.planning.plan_guard_service import build_planning_brief

TODAY = date(2026, 11, 2)  # Monday


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


def legs(local_id, day, **extra):
    return unit(local_id, day, "strength", session_focus="legs", **extra)


def intervals(local_id, day, **extra):
    return unit(local_id, day, "run", session_focus="vo2max", **extra)


def check(units, expects_strength=False):
    return plan_checks.check_plan(
        today=TODAY,
        units=units,
        completed=[],
        competitions=[],
        expects_strength=expects_strength,
    )


def codes(findings):
    return [item["code"] for item in findings]


class ClassificationTests(unittest.TestCase):
    def test_leg_vs_upper_body_vs_unknown(self) -> None:
        def classify(item):
            found = leg_strength.classify(item)
            assert found is not None
            return found

        self.assertTrue(classify(legs("a", "2026-11-03")).leg)
        for focus in ("full_body", "plyometrics"):
            self.assertTrue(
                classify(unit("a", "2026-11-03", "strength", session_focus=focus)).leg
            )
        for focus in ("upper", "core", "mobility"):
            self.assertIs(
                False,
                classify(unit("a", "2026-11-03", "strength", session_focus=focus)).leg,
            )
        keyword = unit("a", "2026-11-03", "strength", name="Beintag", description="")
        self.assertTrue(classify(keyword).leg)
        unknown = unit("a", "2026-11-03", "strength", name="Kraft", description="")
        self.assertIsNone(classify(unknown).leg)
        self.assertIsNone(leg_strength.classify(unit("a", "2026-11-03", "run")))

    def test_intensity_sources(self) -> None:
        def graded(**extra):
            return leg_strength.classify(
                unit(
                    "a",
                    "2026-11-03",
                    "strength",
                    **{"name": "Squats", "description": "", **extra},
                )
            ).intensity

        self.assertEqual("heavy", graded(strength_intensity="heavy", rpe=5))
        self.assertEqual("heavy", graded(planned_intensity=0.9))
        self.assertEqual("moderate", graded(planned_intensity=75))
        self.assertEqual("light", graded(planned_intensity=0.5))
        self.assertEqual("heavy", graded(rpe=8))
        self.assertEqual("moderate", graded(rpe=6))
        self.assertEqual("light", graded(rpe=4))
        self.assertEqual("heavy", graded(description="schwer 5x3"))
        self.assertEqual("moderate", graded(description="moderate Last"))
        self.assertIsNone(graded(description="3x10"))


class BriefTests(unittest.TestCase):
    def test_mixed_week_counts(self) -> None:
        units = [
            unit("r", "2026-11-03", "run"),
            unit("b", "2026-11-04", "ride"),
            legs("l1", "2026-11-04", strength_intensity="heavy"),
            legs("l2", "2026-11-06", planned_intensity=0.75),
            legs("l3", "2026-11-07"),
            unit("u", "2026-11-05", "strength", session_focus="upper"),
            unit("k", "2026-11-08", "strength", name="Kraft", description=""),
            legs("n", "2026-11-10"),
        ]
        weeks = leg_strength.planned_weeks(units, TODAY)
        first = weeks[0]
        self.assertEqual("2026-11-02", first["week_start"])
        self.assertEqual(5, first["sessions"])
        self.assertEqual(3, first["leg_sessions"])
        self.assertEqual(1, first["leg_unknown_sessions"])
        self.assertEqual(
            {"light": 0, "moderate": 1, "heavy": 1, "unknown": 1},
            first["leg_by_intensity"],
        )
        self.assertEqual(1, weeks[1]["leg_sessions"])
        brief = build_planning_brief(
            progress={"week_list": []},
            completed=[],
            competitions=[],
            training_model="pyramidal",
            today=TODAY,
            planned_strength=weeks,
        )
        self.assertEqual(2, len(brief["strength"]["weeks"]))
        self.assertNotIn("load", str(brief["strength"]["weeks"][0]))

    def test_completed_week_carries_leg_counts(self) -> None:
        week = {
            "week_start": "2026-10-26",
            "week_end": "2026-11-01",
            "status": "recorded",
            "sports": {
                "strength": {
                    "sessions": 2,
                    "duration_s": {"value": 3600},
                    "training_load": {"value": None},
                    "intensity_3zone": {"seconds": {}},
                }
            },
        }
        done: list[dict[str, object]] = [
            {
                "sport": "strength",
                "name": "Kniebeugen",
                "started_at_local": "2026-10-28T08:00:00",
                "rpe": 8,
            },
            {
                "sport": "strength",
                "name": "Oberkoerper",
                "started_at_local": "2026-10-30T08:00:00",
            },
        ]
        brief = build_planning_brief(
            progress={"week_list": [week]},
            completed=done,
            competitions=[],
            training_model="pyramidal",
            today=TODAY,
        )
        strength = brief["weeks"][0]["strength"]
        self.assertEqual(2, strength["sessions"])
        self.assertEqual(1, strength["leg_sessions"])
        self.assertEqual(1, strength["leg_by_intensity"]["heavy"])


class NoteTests(unittest.TestCase):
    def test_heavy_legs_the_day_before_intervals(self) -> None:
        found = check(
            [
                legs("l", "2026-11-03", strength_intensity="heavy"),
                intervals("i", "2026-11-04"),
            ]
        )
        self.assertEqual([leg_strength.BEFORE_KEY], codes(found))
        self.assertFalse(found[0]["blocking"])
        self.assertIn("limited", found[0]["evidence_strength"])

    def test_moderate_legs_30_hours_before_gives_no_note(self) -> None:
        found = check(
            [
                legs(
                    "l",
                    "2026-11-03",
                    strength_intensity="moderate",
                    starts_at_local="2026-11-03T08:00:00",
                ),
                intervals("i", "2026-11-04", starts_at_local="2026-11-04T14:00:00"),
            ]
        )
        self.assertEqual([], found)

    def test_moderate_legs_20_hours_before_notes(self) -> None:
        found = check(
            [
                legs(
                    "l",
                    "2026-11-03",
                    strength_intensity="moderate",
                    starts_at_local="2026-11-03T08:00:00",
                ),
                intervals("i", "2026-11-04", starts_at_local="2026-11-04T04:00:00"),
            ]
        )
        self.assertEqual([leg_strength.BEFORE_KEY], codes(found))

    def test_long_ride_counts_as_key_session(self) -> None:
        found = check(
            [
                legs("l", "2026-11-06", strength_intensity="heavy"),
                unit("long", "2026-11-07", "ride", minutes=180, session_focus="long"),
            ]
        )
        self.assertEqual([leg_strength.BEFORE_KEY], codes(found))

    def test_light_legs_and_upper_body_give_no_note(self) -> None:
        for strength in (
            legs("l", "2026-11-03", strength_intensity="light"),
            unit(
                "u",
                "2026-11-03",
                "strength",
                session_focus="upper",
                strength_intensity="heavy",
            ),
        ):
            self.assertEqual([], check([strength, intervals("i", "2026-11-04")]))

    def test_heavy_same_day_stays_with_the_existing_rule(self) -> None:
        found = check(
            [
                legs(
                    "l",
                    "2026-11-03",
                    strength_intensity="heavy",
                    starts_at_local="2026-11-03T08:00:00",
                ),
                intervals("i", "2026-11-03", starts_at_local="2026-11-03T10:00:00"),
            ]
        )
        self.assertEqual(["strength_hard_same_day"], codes(found))

    def test_heavy_text_same_day_is_left_to_the_existing_rule(self) -> None:
        found = check(
            [
                legs(
                    "l",
                    "2026-11-03",
                    name="Heavy squats",
                    planned_intensity=0.75,
                    starts_at_local="2026-11-03T08:00:00",
                ),
                intervals("i", "2026-11-03", starts_at_local="2026-11-03T11:00:00"),
            ]
        )
        self.assertEqual(["strength_hard_same_day"], codes(found))

    def test_synthetic_midnight_start_is_unknown(self) -> None:
        found = check(
            [
                legs(
                    "l",
                    "2026-11-03",
                    strength_intensity="heavy",
                    starts_at_local="2026-11-03T00:00:00",
                ),
                intervals("i", "2026-11-04", starts_at_local="2026-11-04T00:00:00"),
            ]
        )
        self.assertEqual([leg_strength.BEFORE_KEY], codes(found))
        self.assertFalse(found[0]["evidence"]["time_known"])

    def test_too_many_leg_sessions(self) -> None:
        four = [legs(f"l{n}", f"2026-11-0{n + 2}") for n in range(4)]
        found = check(four)
        self.assertEqual([leg_strength.FREQUENCY], codes(found))
        self.assertEqual("too_many", found[0]["evidence"]["reason"])
        three_heavy = [
            legs(f"h{n}", f"2026-11-0{n + 2}", strength_intensity="heavy")
            for n in range(3)
        ]
        self.assertEqual("too_many", check(three_heavy)[0]["evidence"]["reason"])
        self.assertEqual([], check(four[:3]))

    def test_block_without_legs(self) -> None:
        block = [
            unit("a", "2026-11-03", "run"),
            unit("b", "2026-11-10", "run"),
            unit("u", "2026-11-11", "strength", session_focus="upper"),
        ]
        found = check(block, expects_strength=True)
        self.assertEqual([leg_strength.FREQUENCY], codes(found))
        self.assertEqual("no_leg_session", found[0]["evidence"]["reason"])
        self.assertEqual([], check(block, expects_strength=False))
        self.assertEqual([], check(block[:1], expects_strength=True))
        self.assertEqual([], check([*block, legs("l", "2026-11-12")], True))
        unknown = unit("k", "2026-11-12", "strength", name="Kraft", description="")
        self.assertEqual([], check([*block, unknown], True))

    def test_sparse_weeks_are_not_a_plan_of_two_weeks(self) -> None:
        sparse = [unit("a", "2026-11-03", "run"), unit("b", "2026-12-14", "run")]
        self.assertEqual([], check(sparse, True))

    def test_more_leg_sessions_in_a_flagged_week_is_a_new_note(self) -> None:
        four = [legs(f"l{n}", f"2026-11-0{n + 2}") for n in range(4)]
        five = [*four, legs("l5", "2026-11-07")]
        self.assertEqual(
            [leg_strength.FREQUENCY],
            codes(plan_checks.new_findings(check(four), check(five))),
        )

    def test_finding_identity_is_stable(self) -> None:
        block = [unit("a", "2026-11-03", "run"), unit("b", "2026-11-10", "run")]
        before = check(block, True)
        after = check([*block, unit("c", "2026-11-11", "run")], True)
        self.assertEqual([], plan_checks.new_findings(before, after))

    def test_expectation_from_profile_or_phase(self) -> None:
        race = [{"event_date": "2027-01-10", "priority": "A", "name": "R"}]
        expected = leg_strength.strength_expected
        self.assertTrue(expected("Zweimal pro Woche", [], TODAY))
        self.assertFalse(expected("keine Kraft", [], TODAY))
        self.assertFalse(expected("-", [], TODAY))
        self.assertFalse(expected("", [], TODAY))
        self.assertTrue(expected("", race, TODAY))
        peak = [{"event_date": "2026-11-20", "priority": "A", "name": "R"}]
        self.assertFalse(expected("", peak, TODAY))


def done_legs(day, **extra):
    return {
        "sport": "strength",
        "started_at_local": f"{day}T08:00:00",
        "name": "Leg day squats",
        **extra,
    }


class RunningWeekTests(unittest.TestCase):
    """Monday-Tuesday completed plus the planned rest of the week."""

    COMPLETED = (done_legs("2026-11-02"), done_legs("2026-11-03"))
    TODAY = date(2026, 11, 4)

    def test_completed_leg_days_count_toward_the_weekly_limit(self) -> None:
        planned = [legs("p1", "2026-11-05"), legs("p2", "2026-11-07")]
        alone = leg_strength.frequency(planned, self.TODAY, False)
        self.assertEqual([], alone)
        drafts = leg_strength.frequency(planned, self.TODAY, False, self.COMPLETED)
        self.assertEqual(1, len(drafts))
        evidence = drafts[0][3]
        self.assertEqual(4, evidence["leg_sessions"])
        self.assertEqual("running week: completed + planned", evidence["basis"])
        self.assertEqual(["p1", "p2"], [u["local_id"] for u in drafts[0][1]])

    def test_planned_weeks_label_the_combined_running_week(self) -> None:
        planned = [legs("p1", "2026-11-05")]
        week = leg_strength.planned_weeks(planned, self.TODAY, self.COMPLETED)[0]
        self.assertEqual(3, week["leg_sessions"])
        self.assertFalse(week["partial"])
        self.assertEqual("running week: completed + planned", week["basis"])
        without = leg_strength.planned_weeks(planned, self.TODAY)[0]
        self.assertTrue(without["partial"])
        self.assertEqual(1, without["leg_sessions"])

    def test_completed_days_of_other_weeks_do_not_count(self) -> None:
        old = [done_legs("2026-10-30"), done_legs("2026-10-31")]
        planned = [legs("p1", "2026-11-05"), legs("p2", "2026-11-07")]
        self.assertEqual([], leg_strength.frequency(planned, self.TODAY, False, old))


class RunningWeekDedupTests(unittest.TestCase):
    def test_leg_session_done_today_is_not_counted_twice(self) -> None:
        today = date(2026, 11, 4)
        completed = [done_legs("2026-11-02"), done_legs("2026-11-04")]
        planned = [legs("today", "2026-11-04"), legs("later", "2026-11-06")]
        self.assertEqual([], leg_strength.frequency(planned, today, False, completed))
        week = leg_strength.planned_weeks(planned, today, completed)[0]
        self.assertEqual(3, week["leg_sessions"])


class StrengthBeforeTests(unittest.TestCase):
    START = datetime.fromisoformat("2026-11-03T18:00:00")

    @staticmethod
    def done(started, **extra):
        return {
            "sport": "strength",
            "started_at_local": started,
            "name": "Gym",
            **extra,
        }

    def test_heavy_leg_session_20_hours_before(self):
        done = self.done("2026-11-02T22:00:00", description="legs heavy")
        result = leg_strength.strength_before(self.START, [done], list)
        self.assertEqual("completed", result["origin"])
        self.assertEqual(
            [{"hours_before": 20.0, "legs": True, "intensity": "heavy"}],
            result["sessions"],
        )

    def test_upper_body_planned_session_is_listed_as_not_legs(self):
        planned = unit(
            "u",
            "2026-11-02",
            "strength",
            session_focus="upper",
            starts_at_local="2026-11-02T10:00:00",
        )
        result = leg_strength.strength_before(self.START, [], lambda: [planned])
        self.assertEqual("planned_not_confirmed", result["origin"])
        self.assertIs(False, result["sessions"][0]["legs"])
        self.assertEqual(32.0, result["sessions"][0]["hours_before"])

    def test_date_only_plan_counts_only_for_the_day_before(self):
        def plan(day):
            return unit("u", day, "strength", session_focus="legs")

        for day, expected in (("2026-11-02", 1), ("2026-11-01", 0), ("2026-11-03", 0)):
            with self.subTest(day=day):
                result = leg_strength.strength_before(
                    self.START, [], lambda day=day: [plan(day)]
                )
                self.assertEqual(expected, len(result["sessions"]))
        self.assertEqual(
            "planned_not_confirmed",
            leg_strength.strength_before(self.START, [], lambda: [plan("2026-11-02")])[
                "origin"
            ],
        )

    def test_completed_midnight_start_and_the_48_hour_edge(self):
        midnight = self.done("2026-11-03T00:00:00", description="legs")
        edge = self.done("2026-11-01T18:00:00", description="legs")
        late = self.done("2026-11-01T17:59:00", description="legs")
        result = leg_strength.strength_before(self.START, [midnight, edge, late], list)
        self.assertEqual([18.0, 48.0], [r["hours_before"] for r in result["sessions"]])

    def test_none_and_older_sessions_are_none_found(self):
        old = self.done("2026-10-30T10:00:00")
        run = {"sport": "run", "started_at_local": "2026-11-03T08:00:00"}
        result = leg_strength.strength_before(self.START, [old, run], lambda: None)
        self.assertEqual("none_found", result["origin"])
        self.assertEqual([], result["sessions"])
        self.assertFalse(result["planned_checked"])

    def test_unreadable_activities_are_not_covered_and_carry_no_load(self):
        result = leg_strength.strength_before(self.START, None, list)
        self.assertEqual("not_covered", result["status"])
        done = self.done("2026-11-03T08:00:00", rpe=9, training_load=80)
        row = leg_strength.strength_before(self.START, [done], list)["sessions"][0]
        self.assertEqual({"hours_before", "legs", "intensity"}, set(row))


if __name__ == "__main__":
    unittest.main()
