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
        self.assertEqual(result["2026-11-03"], {"minutes": 60, "source": "profile"})
        self.assertEqual(result["2026-11-02"]["source"], "fallback")
        self.assertEqual(result["2026-11-02"]["minutes"], 360 + 60 + 510)


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

    def test_large_brief_is_trimmed_by_entries_with_an_omitted_note(self) -> None:
        full = self.large_brief()
        limit = brief_budget.brief_size(full) - 700
        brief = brief_budget.fit_brief(full, limit)
        self.assertLessEqual(brief_budget.brief_size(brief), limit)
        for key in ("lessons", "season_phase", "weekly_plan"):
            self.assertEqual(brief[key], full[key])
        self.assertEqual(brief["weeks"][-1]["week_start"], "2026-06-01")
        counts = brief["omitted"]["counts"]
        self.assertGreater(counts["weeks"], 0)
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
