"""Weekly plan: normalization, window fallback levels and plan-check notes."""

from __future__ import annotations

import json
import unittest
from datetime import date

from backend.athlete import weekly_plan
from backend.athlete.profile import normalize_profile
from backend.errors import AppError
from backend.planning import plan_checks, weekly_plan_checks
from backend.planning.plan_guard_service import build_planning_brief

MONDAY = date(2026, 11, 2)


def plan(**days: dict) -> str:
    return json.dumps({"days": days})


def week(text: str) -> dict[str, weekly_plan.EffectiveDay]:
    return {item.day: item for item in weekly_plan.effective_week(text)}


class NormalizationTests(unittest.TestCase):
    def test_empty_inputs_mean_nothing_set(self) -> None:
        for value in ("", "  ", "{}", None, '{"days":{"mon":{}}}', "not json"):
            with self.subTest(value=value):
                self.assertEqual(weekly_plan.normalize(value), "")

    def test_windows_are_sorted_and_overlaps_merged(self) -> None:
        text = weekly_plan.normalize(
            plan(mon={"windows": ["12:00-13:00", "05:30-06:30", "06:00-07:00", "x"]})
        )
        self.assertEqual(
            json.loads(text)["days"]["mon"]["windows"], ["05:30-07:00", "12:00-13:00"]
        )

    def test_invalid_times_are_rejected_strictly_and_dropped_leniently(self) -> None:
        bad = plan(tue={"windows": ["18:00-17:00"], "max_minutes": 60})
        with self.assertRaises(AppError):
            weekly_plan.normalize(bad, strict=True)
        self.assertEqual(
            json.loads(weekly_plan.normalize(bad))["days"]["tue"], {"max_minutes": 60}
        )
        for window in ("25:00-26:00", "6-7", "06:00-24:01", "06:00"):
            with self.subTest(window=window), self.assertRaises(AppError):
                weekly_plan.normalize(plan(mon={"windows": [window]}), strict=True)

    def test_fixed_session_works_without_window(self) -> None:
        text = weekly_plan.normalize(
            plan(wed={"fixed": [{"sport": "strength", "focus": "legs"}]}), strict=True
        )
        day = json.loads(text)["days"]["wed"]
        self.assertEqual(day, {"fixed": [{"sport": "strength", "focus": "legs"}]})

    def test_fixed_session_rules(self) -> None:
        with self.assertRaises(AppError):
            weekly_plan.normalize(plan(wed={"fixed": [{"sport": "swim"}]}), strict=True)
        with self.assertRaises(AppError):
            weekly_plan.normalize(
                plan(wed={"fixed": [{"sport": "run", "focus": "legs"}]}), strict=True
            )
        full = {
            "sport": "ride",
            "focus": "long",
            "minutes": 180,
            "window": "08:00-12:00",
        }
        text = weekly_plan.normalize(plan(sat={"fixed": [full]}), strict=True)
        self.assertEqual(json.loads(text)["days"]["sat"]["fixed"], [full])

    def test_rest_day_excludes_windows_and_fixed_sessions(self) -> None:
        text = weekly_plan.normalize(
            plan(fri={"rest_day": True, "windows": ["06:00-07:00"], "max_minutes": 30}),
            strict=True,
        )
        self.assertEqual(json.loads(text)["days"]["fri"], {"rest_day": True})
        with self.assertRaises(AppError):
            weekly_plan.normalize(
                plan(fri={"rest_day": True, "fixed": [{"sport": "run"}]}), strict=True
            )

    def test_max_minutes_is_bounded(self) -> None:
        with self.assertRaises(AppError):
            weekly_plan.normalize(plan(mon={"max_minutes": 5}), strict=True)
        self.assertEqual(weekly_plan.normalize(plan(mon={"max_minutes": 5})), "")

    def test_malformed_containers_are_rejected_strictly(self) -> None:
        for bad in (
            '{"days":{"mon":{"windows":"06:00-07:00"}}}',
            '{"days":{"mon":{"fixed":"run"}}}',
            '{"days":[]}',
            '{"default":{"mon":"06:00-07:00"}}',
            '{"days":{"mon":"rest"}}',
            '{"days":{"mon":["06:00-07:00"]}}',
        ):
            with self.subTest(bad=bad), self.assertRaises(AppError):
                weekly_plan.normalize(bad, strict=True)
            self.assertEqual(weekly_plan.normalize(bad), "")

    def test_non_finite_numbers_are_a_validation_error(self) -> None:
        text = '{"days":{"mon":{"max_minutes":1e999}}}'
        with self.assertRaises(AppError):
            weekly_plan.normalize(text, strict=True)
        self.assertEqual(weekly_plan.normalize(text), "")

    def test_normalization_is_idempotent_and_profile_integrated(self) -> None:
        once = weekly_plan.normalize(plan(sun={"max_minutes": 240}), strict=True)
        self.assertEqual(weekly_plan.normalize(once, strict=True), once)
        profile = normalize_profile({"weekly_plan": once}, validate_timezone=True)
        self.assertEqual(profile["weekly_plan"], once)
        with self.assertRaises(AppError):
            normalize_profile({"weekly_plan": "{broken"}, validate_timezone=True)
        self.assertEqual(normalize_profile({})["weekly_plan"], "")


class FallbackLevelTests(unittest.TestCase):
    def test_nothing_set_uses_builtin_hours_labelled_fallback(self) -> None:
        days = week("")
        self.assertTrue(all(item.source == "fallback" for item in days.values()))
        self.assertEqual(
            days["mon"].windows, ("00:00-06:00", "12:00-13:00", "15:30-24:00")
        )
        self.assertEqual(days["fri"].windows, ("14:00-24:00",))
        self.assertEqual(days["sun"].windows, ("00:00-24:00",))

    def test_day_windows_beat_default_beat_fallback(self) -> None:
        text = json.dumps(
            {
                "default": {"tue": ["17:00-19:00"]},
                "days": {
                    "mon": {"windows": ["07:00-08:00"]},
                    "tue": {"max_minutes": 45},
                },
            }
        )
        days = week(text)
        self.assertEqual(
            (days["mon"].source, days["mon"].windows), ("profile", ("07:00-08:00",))
        )
        self.assertEqual(
            (days["tue"].source, days["tue"].windows), ("default", ("17:00-19:00",))
        )
        self.assertEqual(days["tue"].max_minutes, 45)
        self.assertEqual(days["wed"].source, "fallback")

    def test_rest_day_differs_from_unspecified(self) -> None:
        days = week(plan(thu={"rest_day": True}, fri={"max_minutes": 60}))
        self.assertTrue(days["thu"].rest_day)
        self.assertEqual(days["thu"].windows, ())
        self.assertFalse(days["fri"].rest_day)
        self.assertEqual(days["fri"].source, "fallback")

    def test_fixed_sessions_and_limit_apply_at_every_level(self) -> None:
        fixed = {"sport": "strength", "focus": "legs", "minutes": 60}
        days = week(plan(wed={"fixed": [fixed], "max_minutes": 90}))
        self.assertEqual(days["wed"].source, "fallback")
        self.assertEqual(days["wed"].fixed_sessions, (fixed,))
        self.assertEqual(days["wed"].max_minutes, 90)

    def test_effective_day_for_a_date_and_brief(self) -> None:
        self.assertEqual(weekly_plan.effective_for_date("", MONDAY).day, "mon")
        brief = build_planning_brief(
            progress={},
            completed=[],
            competitions=[],
            training_model="pyramidal",
            today=MONDAY,
            weekly_plan_text=plan(sat={"windows": ["08:00-12:00"]}),
        )["weekly_plan"]
        self.assertEqual([item["day"] for item in brief], list(weekly_plan.DAYS))
        self.assertEqual(brief[5]["source"], "profile")
        self.assertEqual(brief[0]["source"], "fallback")


def unit(day: str, sport: str, *, time: str = "", minutes: int = 60, **extra) -> dict:
    return {
        "local_id": f"{day}-{sport}-{time}",
        "date": day,
        "starts_at_local": f"{day}T{time}:00" if time else day,
        "sport": sport,
        "duration_minutes": minutes,
        **extra,
    }


def codes(text: str, units: list[dict]) -> dict[str, list[dict]]:
    found = plan_checks.check_plan(
        today=MONDAY, units=units, completed=[], competitions=[], weekly_plan=text
    )
    result: dict[str, list[dict]] = {}
    for item in found:
        result.setdefault(item["code"], []).append(item)
    return {
        code: items
        for code, items in result.items()
        if code in weekly_plan_checks.CODES
    }


class PlanCheckTests(unittest.TestCase):
    fixed = plan(wed={"fixed": [{"sport": "strength", "focus": "legs"}]})

    def test_empty_weekly_plan_gives_no_notes(self) -> None:
        self.assertEqual(codes("", [unit("2026-11-04", "run", time="10:00")]), {})

    def test_fixed_session_missing_or_on_another_day(self) -> None:
        units = [
            unit("2026-11-03", "run"),
            unit("2026-11-05", "strength", session_focus="legs"),
        ]
        found = codes(self.fixed, units)["fixed_session_missing"][0]
        self.assertEqual(found["dates"], ["2026-11-04"])
        self.assertFalse(found["blocking"])
        self.assertEqual(found["evidence"]["other_days"], ["2026-11-05"])
        placed = [unit("2026-11-04", "strength", session_focus="legs")]
        self.assertNotIn("fixed_session_missing", codes(self.fixed, placed))

    def test_fixed_session_with_other_focus_counts_as_missing(self) -> None:
        units = [unit("2026-11-04", "strength", session_focus="upper")]
        self.assertIn("fixed_session_missing", codes(self.fixed, units))

    def test_unit_on_rest_day(self) -> None:
        text = plan(tue={"rest_day": True})
        found = codes(text, [unit("2026-11-03", "run")])
        self.assertEqual(found["rest_day_session"][0]["dates"], ["2026-11-03"])
        self.assertFalse(found["rest_day_session"][0]["blocking"])
        self.assertNotIn("rest_day_session", codes(text, [unit("2026-11-04", "run")]))

    def test_unit_outside_explicit_windows_or_over_max(self) -> None:
        text = plan(mon={"windows": ["06:00-08:00"], "max_minutes": 90})
        found = codes(text, [unit("2026-11-02", "run", time="17:00", minutes=120)])
        self.assertIn("outside_windows", found)
        self.assertIn("over_max_minutes", found)
        inside = codes(text, [unit("2026-11-02", "run", time="06:30", minutes=60)])
        self.assertEqual(inside, {})

    def test_default_windows_note_but_fallback_windows_never_do(self) -> None:
        late = unit("2026-11-03", "run", time="10:00")
        default = json.dumps({"default": {"tue": ["17:00-19:00"]}})
        self.assertIn("outside_windows", codes(default, [late]))
        only_limit = plan(tue={"max_minutes": 600})
        self.assertNotIn("outside_windows", codes(only_limit, [late]))

    def test_unknown_start_time_is_not_checked(self) -> None:
        text = plan(mon={"windows": ["06:00-08:00"]})
        self.assertEqual(codes(text, [unit("2026-11-02", "run")]), {})

    def test_first_unit_late_in_the_week_still_checks_earlier_fixed_days(self) -> None:
        text = plan(mon={"fixed": [{"sport": "run"}]})
        found = codes(text, [unit("2026-11-04", "ride")])
        self.assertEqual(found["fixed_session_missing"][0]["dates"], ["2026-11-02"])

    def test_fixed_session_window_is_enforced(self) -> None:
        text = plan(
            tue={"fixed": [{"sport": "run", "window": "06:00-07:00"}]},
            wed={"fixed": [{"sport": "run"}]},
        )
        late = codes(text, [unit("2026-11-03", "run", time="18:00")])
        self.assertEqual(
            late["outside_windows"][0]["evidence"]["windows"], ["06:00-07:00"]
        )
        on_time = codes(text, [unit("2026-11-03", "run", time="06:00", minutes=45)])
        self.assertNotIn("outside_windows", on_time)
        free = codes(text, [unit("2026-11-04", "run", time="18:00")])
        self.assertNotIn("outside_windows", free)

    def test_longer_overrun_is_a_new_note(self) -> None:
        text = plan(mon={"max_minutes": 60})
        before = plan_checks.check_plan(
            today=MONDAY,
            units=[unit("2026-11-02", "run", minutes=90)],
            completed=[],
            competitions=[],
            weekly_plan=text,
        )
        after = plan_checks.check_plan(
            today=MONDAY,
            units=[unit("2026-11-02", "run", minutes=150)],
            completed=[],
            competitions=[],
            weekly_plan=text,
        )
        self.assertEqual(plan_checks.new_findings(before, before), [])
        self.assertEqual(
            [item["code"] for item in plan_checks.new_findings(before, after)],
            ["over_max_minutes"],
        )

    def test_only_illness_blocks(self) -> None:
        self.assertEqual(plan_checks.BLOCKING_CODES, ("illness_hard",))
        for code in weekly_plan_checks.CODES:
            self.assertIn(code, plan_checks.FINDING_CODES)
            self.assertNotIn(code, plan_checks.BLOCKING_CODES)


if __name__ == "__main__":
    unittest.main()
