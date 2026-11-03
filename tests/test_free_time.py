"""Free minutes per day, the no_free_window note and the bounded planning brief."""

from __future__ import annotations

import json
import unittest
from datetime import date

from backend.coach.context import (
    COACH_CONTEXT_SECTION_LIMITS,
    coach_context_json_size,
    coach_context_projection_meta,
)
from backend.planning import brief_budget, free_time
from backend.planning.plan_guard_service import build_planning_brief
from tests.test_weekly_plan import MONDAY, codes, plan, unit

TUESDAY = date(2026, 11, 3)


def event(start: str, end: str, **extra) -> dict:
    return {
        "start_local": f"2026-11-03T{start}:00",
        "end_local": f"2026-11-03T{end}:00",
        **extra,
    }


class FreeMinutesTests(unittest.TestCase):
    def test_windows_without_events_are_fully_free(self) -> None:
        self.assertEqual(
            free_time.free_minutes(TUESDAY, ["06:00-08:00", "12:00-13:00"], []), 180
        )

    def test_overlapping_events_count_once_and_clip_to_the_windows(self) -> None:
        events = [
            event("06:30", "07:00"),
            event("06:45", "07:15"),
            event("07:50", "09:00"),
        ]
        self.assertEqual(free_time.free_minutes(TUESDAY, ["06:00-08:00"], events), 65)

    def test_all_day_events_and_other_days_are_ignored(self) -> None:
        events = [
            event("00:00", "23:59", all_day=True),
            {"start_local": "2026-11-04T06:00:00", "end_local": "2026-11-04T08:00:00"},
        ]
        self.assertEqual(free_time.free_minutes(TUESDAY, ["06:00-08:00"], events), 120)

    def test_brief_carries_source_per_date(self) -> None:
        text = plan(tue={"windows": ["06:00-08:00"]})
        result = free_time.free_time_brief(text, [event("06:00", "07:00")], MONDAY, 3)
        self.assertEqual(
            result["2026-11-03"],
            {
                "minutes": 60,
                "longest_block_minutes": 60,
                "source": "profile",
            },
        )
        self.assertEqual(result["2026-11-02"]["source"], "fallback")
        self.assertEqual(result["2026-11-02"]["minutes"], 360 + 60 + 510)


class FreeBlockTests(unittest.TestCase):
    def test_two_short_gaps_give_total_but_a_shorter_longest_block(self) -> None:
        windows = ["06:00-07:00", "12:00-13:00"]
        self.assertEqual(free_time.free_minutes(TUESDAY, windows, []), 120)
        self.assertEqual(free_time.longest_block(TUESDAY, windows, []), 60)
        events = [event("06:30", "06:45")]
        self.assertEqual(free_time.longest_block(TUESDAY, ["06:00-07:00"], events), 30)

    def test_brief_lists_all_day_events_without_subtracting_them(self) -> None:
        text = plan(tue={"windows": ["06:00-08:00"]})
        holiday = event(
            "00:00",
            "23:59",
            all_day=True,
            name="Messe",
            no_training=True,
            training_impact=True,
        )
        result = free_time.free_time_brief(text, [holiday], MONDAY, 3)
        day = result["2026-11-03"]
        self.assertEqual(day["minutes"], 120)
        self.assertEqual(
            day["all_day_events"],
            [
                {
                    "name": "Messe",
                    "training_impact": True,
                    "no_training": True,
                    "all_day": True,
                }
            ],
        )
        self.assertNotIn("all_day_events", result["2026-11-02"])


class NoFreeWindowTests(unittest.TestCase):
    def check(self, text, units, events):
        from backend.planning import plan_checks, weekly_plan_checks

        found = plan_checks.check_plan(
            today=MONDAY,
            units=units,
            completed=[],
            competitions=[],
            weekly_plan=text,
            calendar_events=events,
        )
        return [f for f in found if f["code"] in weekly_plan_checks.CODES]

    def test_unit_longer_than_the_free_time_notes_without_blocking(self) -> None:
        text = plan(tue={"windows": ["06:00-08:00"]})
        found = self.check(
            text, [unit("2026-11-03", "run", minutes=90)], [event("06:00", "07:00")]
        )
        notes = [f for f in found if f["code"] == "no_free_window"]
        self.assertEqual(len(notes), 1)
        self.assertFalse(notes[0]["blocking"])
        self.assertEqual(notes[0]["evidence"]["free_minutes"], 60)

    def test_fixed_session_window_is_checked_against_calendar_events(self) -> None:
        fixed = {"sport": "run", "minutes": 90, "window": "06:00-08:00"}
        text = plan(tue={"fixed": [fixed]})
        found = self.check(
            text, [unit("2026-11-03", "run", minutes=90)], [event("06:00", "07:00")]
        )
        notes = [f for f in found if f["code"] == "no_free_window"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["evidence"]["free_minutes"], 60)
        self.assertEqual(notes[0]["evidence"]["source"], "fixed_session")
        self.assertEqual(
            self.check(text, [unit("2026-11-03", "run", minutes=90)], []), []
        )

    def notes(self, text, units, events):
        return [
            f for f in self.check(text, units, events) if f["code"] == "no_free_window"
        ]

    def test_unit_needs_one_contiguous_block_not_the_total(self) -> None:
        text = plan(tue={"windows": ["06:00-07:00", "12:00-13:00"]})
        found = self.notes(text, [unit("2026-11-03", "run", minutes=90)], [])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["evidence"]["free_minutes"], 120)
        self.assertEqual(found[0]["evidence"]["longest_block_minutes"], 60)
        self.assertEqual(found[0]["evidence"]["reason"], "no_block")
        self.assertFalse(found[0]["blocking"])

    def test_two_units_share_the_free_time_one_is_placed_one_not(self) -> None:
        text = plan(tue={"windows": ["06:00-07:30"]})
        units = [
            unit("2026-11-03", "run", minutes=60, local_id="a"),
            unit("2026-11-03", "ride", minutes=60, local_id="b"),
        ]
        found = self.notes(text, units, [])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["local_ids"], ["b"])
        self.assertEqual(found[0]["evidence"]["reason"], "shared_with_other_units")
        self.assertEqual(self.notes(text, units[:1], []), [])

    def test_longest_unit_goes_first_into_the_best_fitting_block(self) -> None:
        text = plan(tue={"windows": ["06:00-07:00", "12:00-13:30"]})
        units = [
            unit("2026-11-03", "run", minutes=45, local_id="short"),
            unit("2026-11-03", "ride", minutes=90, local_id="long"),
        ]
        self.assertEqual(self.notes(text, units, []), [])

    def test_overlapping_fixed_window_shares_minutes_with_the_day_windows(self) -> None:
        fixed = {"sport": "run", "minutes": 60, "window": "06:30-07:30"}
        text = plan(tue={"windows": ["06:00-08:00"], "fixed": [fixed]})
        units = [
            unit("2026-11-03", "run", minutes=60, local_id="fixed"),
            unit("2026-11-03", "ride", minutes=90, local_id="other"),
        ]
        found = self.notes(text, units, [])
        self.assertEqual([f["local_ids"] for f in found], [["fixed"]])

    def test_malformed_unit_date_does_not_abort_the_check(self) -> None:
        from backend.planning import plan_checks

        bad = unit("2026-13-45", "run", minutes=120, local_id="bad")
        plan_checks.check_plan(today=MONDAY, units=[bad], completed=[], competitions=[])

    def test_timed_easy_unit_overlapping_an_event_notes_overlap(self) -> None:
        text = plan(tue={"windows": ["12:00-13:00"]})
        easy = unit("2026-11-03", "run", time="12:00", minutes=30)
        found = self.notes(text, [easy], [event("12:00", "12:30")])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["evidence"]["reason"], "overlap")
        self.assertEqual(self.notes(text, [easy], [event("12:30", "13:00")]), [])

    def test_hard_overlap_is_named_once_by_calendar_load(self) -> None:
        text = plan(tue={"windows": ["12:00-13:00"]})
        hard = unit(
            "2026-11-03", "run", time="12:00", minutes=30, session_focus="threshold"
        )
        found = self.check(text, [hard], [event("12:00", "12:30")])
        self.assertEqual([f for f in found if f["code"] == "no_free_window"], [])
        from backend.planning import plan_checks

        every = plan_checks.check_plan(
            today=MONDAY,
            units=[hard],
            completed=[],
            competitions=[],
            weekly_plan=text,
            calendar_events=[event("12:00", "12:30")],
        )
        self.assertEqual([f["code"] for f in every].count("calendar_load"), 1)

    def test_all_day_event_is_a_soft_note_for_hard_or_long_units_only(self) -> None:
        from backend.planning import plan_checks

        holiday = event("00:00", "23:59", all_day=True, name="Messe")
        units = [
            unit(
                "2026-11-03", "run", minutes=40, session_focus="threshold", local_id="h"
            ),
            unit("2026-11-03", "run", minutes=30, session_focus="easy", local_id="e"),
            unit("2026-11-03", "ride", minutes=120, local_id="l"),
        ]
        found = plan_checks.check_plan(
            today=MONDAY,
            units=units,
            completed=[],
            competitions=[],
            calendar_events=[holiday],
        )
        notes = [f for f in found if f["code"] == "all_day_event"]
        self.assertEqual(sorted(n["local_ids"][0] for n in notes), ["h", "l"])
        self.assertFalse(notes[0]["blocking"])
        self.assertEqual(notes[0]["evidence"]["events"][0]["name"], "Messe")

    def test_unit_that_fits_or_fallback_windows_give_no_note(self) -> None:
        text = plan(tue={"windows": ["06:00-08:00"]})
        self.assertEqual(
            self.check(text, [unit("2026-11-03", "run", minutes=60)], []), []
        )
        self.assertEqual(
            codes(
                plan(tue={"max_minutes": 600}), [unit("2026-11-03", "run", minutes=900)]
            ).get("no_free_window"),
            None,
        )


class BriefBudgetTests(unittest.TestCase):
    def large_brief(self) -> dict:
        weeks = [
            {
                "week_start": f"2026-0{i}-01",
                "status": "done",
                "run": {"sessions": 3, "pad": "x" * 200},
            }
            for i in range(1, 7)
        ]
        return build_planning_brief(
            progress={"week_list": []},
            completed=[],
            competitions=[],
            training_model="pyramidal",
            today=MONDAY,
            planned_sessions=[
                {"local_id": str(i), "date": "2026-11-05", "note": "x" * 300}
                for i in range(40)
            ],
            calendar_busy={f"2026-11-{d:02d}": 60 for d in range(1, 30)},
            free_time_minutes={
                f"2026-11-{d:02d}": {"minutes": 60, "source": "profile"}
                for d in range(1, 30)
            },
            lessons=[{"code": "c", "text": "t", "evidence_strength": "low"}],
        ) | {"weeks": weeks}

    def test_small_brief_is_unchanged(self) -> None:
        brief = build_planning_brief(
            progress={},
            completed=[],
            competitions=[],
            training_model="pyramidal",
            today=MONDAY,
        )
        self.assertNotIn("omitted", brief)

    def test_trim_order_keeps_completed_weeks_last(self) -> None:
        full = self.large_brief()
        order = []
        for limit in range(brief_budget.brief_size(full), 3_000, -400):
            counts = (
                brief_budget.fit_brief(self.large_brief(), limit)
                .get("omitted", {})
                .get("counts", {})
            )
            for label in counts:
                if label not in order:
                    order.append(label)
        self.assertEqual(
            order,
            [
                "free_time_minutes",
                "calendar_busy_minutes",
                "planned_sessions",
                "weeks",
            ],
        )
        trimmed = brief_budget.fit_brief(self.large_brief(), 9_000)
        self.assertNotIn("2026-11-01", trimmed["free_time_minutes"])
        for key in ("lessons", "season_phase", "weekly_plan"):
            self.assertEqual(trimmed[key], full[key])

    def test_large_brief_is_trimmed_by_entries_with_an_omitted_note(self) -> None:
        full = self.large_brief()
        limit = brief_budget.brief_size(full) - 700
        brief = brief_budget.fit_brief(full, limit)
        self.assertLessEqual(brief_budget.brief_size(brief), limit)
        for key in ("lessons", "season_phase", "weekly_plan"):
            self.assertEqual(brief[key], full[key])
        self.assertEqual(brief["weeks"], full["weeks"])
        counts = brief["omitted"]["counts"]
        self.assertGreater(counts["free_time_minutes"], 0)
        self.assertNotIn("planned_sessions", counts)
        deeper = brief_budget.fit_brief(self.large_brief(), 12_000)
        self.assertLessEqual(brief_budget.brief_size(deeper), 12_000)
        self.assertIn("planned_sessions", deeper["omitted"]["counts"])
        json.dumps(brief)

    def test_diagnostics_report_the_brief_size(self) -> None:
        self.assertIn("planning_brief", COACH_CONTEXT_SECTION_LIMITS)
        brief = self.large_brief()
        meta = coach_context_projection_meta(
            {"planning_brief": brief},
            0,
            0,
            section_limits=COACH_CONTEXT_SECTION_LIMITS,
            total_limit=120_000,
            local_activity_limit=5,
            planned_event_limit=50,
            local_planned_limit=50,
        )
        self.assertEqual(
            meta["section_characters"]["planning_brief"], coach_context_json_size(brief)
        )


if __name__ == "__main__":
    unittest.main()
