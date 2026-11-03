"""Per-task Coach context: exact section sets and size budgets (#1627).

One rich synthetic fixture runs through the real context service and the
selection projection. Sizes are deterministic, so growth is a deliberate change.
Set BUDGET_TABLE=1 to print the table.
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import date, timedelta
from typing import Any, ClassVar
from unittest.mock import Mock

from activity_row_support import FixedActivityRows, ReadOnlyManager, StoredCoverage
from server_test_support import server

from backend.coach.context import (
    COACH_CONTEXT_SECTION_LIMITS,
    CoachPerformanceContextReader,
    CoachPlanningContextReader,
    CoachStructuredContextService,
    CoachTrainingContextService,
)
from backend.coach.context_selection import (
    CONTEXT_SECTIONS,
    select_coach_context,
)
from backend.coach.playbooks import playbook_for
from backend.performance.freshness import GarminSyncStatus
from backend.planning.compact_activities import ActivitySummarySource
from backend.planning.context import build_daily_planning_context

TODAY = date(2026, 10, 7)
MARKER = "LOCAL PLANNED WORKOUTS (compact projection, included once below):\n"
MORNING_MESSAGE = (
    "Gib mir den heutigen Morgen-Check-in. Lade dafür die aktuellen "
    "Garmin-/Intervals.icu-Daten, bewerte Erholung, Trainingsbelastung und "
    "die geplante Einheit und sag mir, was heute sinnvoll ist."
)
# message, request kind. Sections are listed without the always-present ones.
CASES: dict[str, tuple[str, str | None]] = {
    "session_analysis": ("Analysiere meine letzte Einheit", "session_analysis"),
    "progress_review": ("Wie läuft mein Training?", "progress_review"),
    "block_review": ("Bewerte meinen letzten Block", "block_review"),
    "plan_week": ("Plane die nächste Woche", "plan_week"),
    "plan_block": ("Plane die nächsten 4 Wochen", "plan_block"),
    "adjust_week": ("Passe die Woche an", "adjust_week"),
    "morning_checkin": (MORNING_MESSAGE, "morning_checkin"),
    "free_text_planning": ("Plane meine nächste Woche", None),
    "general_question": ("Wie geht es meiner Erholung?", None),
    "nutrition_message": ("Ich habe 60g Whey getrunken", None),
}


def _planned_units() -> list[dict[str, Any]]:
    units = []
    for offset in range(36):
        day = TODAY + timedelta(days=offset)
        for slot, name in enumerate(("Easy run", "Strength")):
            if slot and offset % 2:
                continue
            units.append(
                {
                    "id": f"unit-{offset}-{slot}",
                    "date": day.isoformat(),
                    "starts_at_local": f"{day.isoformat()}T0{7 + slot}:00:00",
                    "name": f"{name} {offset}",
                    "type": "Run" if not slot else "WeightTraining",
                    "target": "Synthetic target description. " * 6,
                    "status": "planned",
                    "sync_status": "local",
                }
            )
    return units


def _activities() -> list[dict[str, Any]]:
    rows = []
    for index in range(30):
        day = TODAY - timedelta(days=index + 1)
        rows.append(
            {
                "id": f"activity-{index}",
                "started_at_local": f"{day.isoformat()}T07:00:00",
                "name": f"Synthetic session {index}",
                "sport": "run" if index % 3 else "ride",
                "moving_duration_s": 3000 + index,
                "distance_m": 9000 + index,
                "training_load": 40 + index,
            }
        )
    return rows


def _calendar_events() -> list[dict[str, Any]]:
    events = []
    for index in range(28):
        day = (TODAY + timedelta(days=index * 2)).isoformat()
        events.append(
            {
                "id": f"event-{index}",
                "name": f"Synthetic appointment {index}",
                "event_date": day,
                "start_local": f"{day}T17:00:00",
                "end_local": f"{day}T18:30:00",
                "all_day": False,
                "no_training": index % 9 == 0,
                "no_intensity": False,
                "short_only": False,
                "training_relevant": 1,
            }
        )
    return events


def _build_service() -> CoachTrainingContextService:
    events = _calendar_events()
    planned = _planned_units()
    planned_service = Mock()
    planned_service.list.side_effect = lambda limit, future_only=True, since=None: [
        item for item in planned if since is None or item["date"] >= since.isoformat()
    ][:limit]
    weather_service = Mock()
    weather_service.state.return_value = {
        "days": [
            {"date": (TODAY + timedelta(days=n)).isoformat(), "rain_probability": n}
            for n in range(14)
        ]
    }
    daily_service = Mock()
    daily_service.build.side_effect = (
        lambda planned, weather, checkins, calendar_events: (
            build_daily_planning_context(
                planned=planned,
                checkins=checkins,
                calendar_events=calendar_events,
                weather_days=weather.get("days", []),
                recovery_by_date={},
                health_by_date={},
                activity_feedback=[],
                today=TODAY,
                calendar_window_days=56,
            )
        )
    )
    calendar_reader = Mock()
    calendar_reader.list_events.return_value = events
    calendar_reader.list_events_in_window.side_effect = lambda days: [
        event
        for event in events
        if event["event_date"] <= (TODAY + timedelta(days=days)).isoformat()
    ]
    checkins = Mock()
    checkins.context.return_value = {
        "recent": [
            {
                "checkin_date": (TODAY - timedelta(days=n)).isoformat(),
                "mood": "good",
                "notes": "synthetic note",
            }
            for n in range(14)
        ]
    }
    competitions = Mock()
    competitions.list.return_value = [
        {"id": n, "name": f"Race {n}", "event_date": "2026-12-01", "priority": 1}
        for n in range(3)
    ]
    plans = Mock()
    plans.list.return_value = [
        {"id": f"plan-{n}", "name": f"Plan {n}", "start": "2026-09-01"}
        for n in range(100)
    ]
    previews = Mock()
    previews.latest_preview.return_value = {"status": "none"}
    previews.status.return_value = {"available": False}
    profile = Mock()
    profile.get.return_value = {"name": "Athlete", "source": "local"}
    payload = Mock()
    payload.sync_status.return_value = GarminSyncStatus()
    projection = Mock()
    projection.coach_context.return_value = {"recovery": {"sleep": "synthetic"}}
    feedback = Mock()
    feedback.context.return_value = {"recent": []}
    structured = CoachStructuredContextService(
        checkins,
        weather_service,
        feedback,
        CoachPlanningContextReader(
            planned_service,
            daily_service,
            calendar_reader,
            competitions,
            plans,
            previews,
            lambda: TODAY,
        ),
        CoachPerformanceContextReader(
            profile,
            payload,
            projection,
            lambda: TODAY,
            activity_rows=ActivitySummarySource(
                ReadOnlyManager,
                lambda: FixedActivityRows(_activities()),
                coverage=lambda: StoredCoverage("2026-10-07T06:00:00+00:00"),
            ),
        ),
        planning_brief=lambda: {"weeks": "synthetic brief " * 400},
        today=lambda: TODAY,
    )
    library = Mock()
    library.list.return_value = []
    return CoachTrainingContextService(
        structured,
        library,
        local_planned_limit=50,
        library_limit=12,
        library_description_limit=1500,
        section_limits=COACH_CONTEXT_SECTION_LIMITS,
        total_char_limit=120_000,
        activity_limit_per_sport=5,
        planned_event_limit=50,
    )


def measure() -> dict[str, dict[str, Any]]:
    service = _build_service()
    result = {}
    for label, (message, kind) in CASES.items():
        selection = select_coach_context(message, {}, request_kind=kind)
        text = service.build(selection=selection, local_date=TODAY.isoformat())
        start = text.index(MARKER) + len(MARKER)
        context = json.loads(
            text[start : text.index("\nLOCAL TRAINING LIBRARY", start)]
        )
        sizes = {
            key: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            for key, value in context.items()
            if key != "projection"
        }
        result[label] = {
            "selection": selection.name,
            "sections": sorted(sizes),
            "sizes": sizes,
            "total": len(text),
            "context": context,
        }
    return result


COMMON = {
    "activities",
    "activity_feedback",
    "current_performance",
    "durable_profile",
    "local_feedback",
    "local_planned_workouts",
    "source_policy",
    "target_competitions",
}
PLAN = COMMON | {
    "daily_planning_context",
    "external_calendar",
    "planning",
    "planning_brief",
    "recovery",
    "training_plans",
    "weather",
}
# Exact present sections and a character ceiling (whole prompt context) per case.
EXPECTED: dict[str, tuple[set[str], int]] = {
    "session_analysis": (COMMON | {"recovery"}, 26_000),
    "progress_review": (COMMON | {"planning", "recovery"}, 25_500),
    "block_review": (COMMON | {"planning", "recovery", "training_plans"}, 31_000),
    "plan_week": (PLAN, 49_500),
    "plan_block": (PLAN, 63_500),
    "adjust_week": (PLAN, 45_500),
    "morning_checkin": (COMMON | {"daily_planning_context", "recovery"}, 26_000),
    "free_text_planning": (PLAN, 49_500),
    "general_question": (COMMON | {"recovery"}, 25_000),
    "nutrition_message": (COMMON | {"nutrition_products"}, 25_000),
}


def present(row: dict[str, Any]) -> set[str]:
    return {key for key, value in row["context"].items() if value is not None} - {
        "projection"
    }


class CoachContextBudgetTests(unittest.TestCase):
    measured: ClassVar[dict[str, dict[str, Any]]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.measured = measure()
        if os.environ.get("BUDGET_TABLE"):
            for label, row in cls.measured.items():
                print(f"\n{label} [{row['selection']}] total={row['total']}")
                for key, size in sorted(row["sizes"].items()):
                    print(f"  {key}: {size}")

    def test_sections_and_budget_per_kind(self) -> None:
        self.assertEqual(set(CASES), set(EXPECTED))
        for label, (sections, ceiling) in EXPECTED.items():
            with self.subTest(case=label):
                row = self.measured[label]
                self.assertEqual(sections, present(row))
                self.assertLessEqual(row["total"], ceiling)

    def test_free_text_planning_gets_the_brief_and_playbook(self) -> None:
        selection = select_coach_context("Plane meine nächste Woche", {})
        self.assertEqual(("plan_week", "plan_week"), (selection.name, selection.kind))
        self.assertIn("planning_brief", selection.sections)
        self.assertIn(
            "Task: plan the requested next week", playbook_for(selection.kind)
        )

    def test_typed_planning_maps_to_the_fixed_kinds(self) -> None:
        cases = {
            "Plane meine nächste Woche": "plan_week",
            "Plan next week": "plan_week",
            "Erstelle mir einen Trainingsplan für die Woche": "plan_week",
            "Kannst du das Training fuer naechste Woche planen?": "plan_week",
            "Plane die nächsten 4 Wochen": "plan_block",
            "Please schedule my next 3 weeks": "plan_block",
            "Plane einen Aufbau-Block": "plan_block",
            "Passe die Woche an": "adjust_week",
            "Passe die nächste Woche an": "plan_week",
            "Adjust next week": "plan_week",
            "Adjust this week": "adjust_week",
        }
        for message, kind in cases.items():
            with self.subTest(message=message):
                self.assertEqual(kind, select_coach_context(message, {}).kind)

    def test_ordinary_questions_mentioning_a_week_stay_unplanned(self) -> None:
        for message in (
            "What do I have scheduled this week?",
            "Erstelle mir eine Zusammenfassung der letzten Woche",
            "Hab ich erledigt, was für diese Woche anstand?",
            "Wie war meine Woche?",
            "Wie sieht mein Plan für diese Woche aus?",
            "Wie viele Kilometer bin ich diese Woche gelaufen?",
            "Wie war meine letzte Woche?",
            "Was ist ein Trainingsblock?",
            "Passe meinen Lauf am Freitag an",
            "Verschiebe den Lauf auf Freitag",
            "Wie geht es meiner Erholung?",
        ):
            with self.subTest(message=message):
                selection = select_coach_context(message, {})
                self.assertIsNone(selection.kind)
                self.assertNotIn("planning_brief", selection.sections)

    def test_readiness_wording_loads_recovery(self) -> None:
        for message in ("Bin ich bereit fürs Training?", "How is my readiness?"):
            with self.subTest(message=message):
                sections = select_coach_context(message, {}).sections
                self.assertIn("recovery", sections)

    def test_blocks_beyond_the_window_keep_complete_context(self) -> None:
        near = select_coach_context("Plane die nächsten 4 Wochen", {})
        self.assertEqual(("plan_block", 35), (near.name, near.horizon_days))
        far = select_coach_context("Plane die nächsten 5 Wochen", {})
        self.assertEqual("plan_block", far.kind)
        self.assertIsNone(far.horizon_days)

    def test_typed_planning_with_explicit_dates_keeps_complete_context(self) -> None:
        selection = select_coach_context("Plane die Woche ab 2026-12-01", {})
        self.assertEqual("plan_week", selection.kind)
        self.assertIsNone(selection.horizon_days)
        self.assertIn("planning_brief", selection.sections)
        self.assertNotIn("calendar", selection.sections)
        self.assertIn("external_calendar", selection.sections)

    def test_typed_planning_keeps_dialogue_and_pending_retention(self) -> None:
        pending = {"pending_request": {"status": "failed", "source_message_ids": [1]}}
        # message, dialogue, receipts, retain_dialogue, retain_pending_request
        for message, dialogue, receipts, dialogue_kept, pending_kept in (
            ("Kannst du das für die Woche planen?", {}, False, True, False),
            ("Plane meine nächste Woche", {}, False, False, False),
            ("Plane meine nächste Woche", {}, True, True, False),
            ("Plane meine nächste Woche", pending, False, False, False),
        ):
            with self.subTest(message=message, receipts=receipts):
                typed = select_coach_context(message, dialogue, has_receipts=receipts)
                self.assertEqual("plan_week", typed.kind)
                self.assertEqual(dialogue_kept, typed.retain_dialogue)
                self.assertEqual(pending_kept, typed.retain_pending_request)

    def test_system_quick_actions_never_take_a_typed_planning_kind(self) -> None:
        selection = select_coach_context(
            "Plane meine nächste Woche", {}, request_kind="morning_checkin"
        )
        self.assertEqual("morning_checkin", selection.kind)
        self.assertNotIn("planning_brief", selection.sections)

    def test_daily_context_rides_only_on_planning_morning_and_today_turns(
        self,
    ) -> None:
        daily = {
            label
            for label, row in self.measured.items()
            if "daily_planning_context" in present(row)
        }
        self.assertEqual(
            {
                "plan_week",
                "plan_block",
                "adjust_week",
                "morning_checkin",
                "free_text_planning",
            },
            daily,
        )
        self.assertIn(
            "daily_planning_context",
            select_coach_context("Was trainiere ich heute?", {}).sections,
        )
        self.assertNotIn(
            "daily_planning_context",
            select_coach_context("Analysiere meine letzte Einheit", {}).sections,
        )

    def test_planning_turns_carry_each_calendar_event_once(self) -> None:
        for label in ("plan_week", "plan_block", "adjust_week", "free_text_planning"):
            with self.subTest(case=label):
                row = self.measured[label]
                self.assertNotIn("calendar", present(row))
                events = row["context"]["external_calendar"]["events"]
                self.assertTrue(events)
                text = json.dumps(row["context"], ensure_ascii=False)
                for event in events:
                    self.assertEqual(1, text.count(f'"{event["name"]}"'))
                self.assertIn("omitted_count", row["context"]["external_calendar"])

    def test_review_turns_have_no_future_and_analysis_at_most_two_days(self) -> None:
        for label, ahead in (
            ("progress_review", 0),
            ("block_review", 0),
            ("session_analysis", 2),
        ):
            with self.subTest(case=label):
                last = (TODAY + timedelta(days=ahead)).isoformat()
                planned = self.measured[label]["context"]["local_planned_workouts"]
                self.assertTrue(planned)
                latest = max(item["date"] for item in planned)
                self.assertLessEqual(latest, last)

    def test_progress_review_drops_training_plans_block_review_keeps_them(
        self,
    ) -> None:
        self.assertNotIn("training_plans", present(self.measured["progress_review"]))
        self.assertIn("training_plans", present(self.measured["block_review"]))

    def test_every_removed_section_stays_loadable_by_the_read_tool(self) -> None:
        tool = next(
            item
            for item in server.COACH_DIALOGUE_TOOLS
            if item["name"] == "read_coach_context"
        )
        offered = set(tool["parameters"]["properties"]["sections"]["items"]["enum"])
        self.assertEqual(CONTEXT_SECTIONS, offered)
        for label, (message, kind) in CASES.items():
            with self.subTest(case=label):
                selection = select_coach_context(message, {}, request_kind=kind)
                self.assertLessEqual(CONTEXT_SECTIONS - selection.sections, offered)

    def test_size_diagnostics_name_the_selection_and_sections_for_every_kind(
        self,
    ) -> None:
        service = _build_service()
        for label, (message, kind) in CASES.items():
            with self.subTest(case=label):
                selection = select_coach_context(message, {}, request_kind=kind)
                with self.assertLogs("intervals_coach", level="INFO") as captured:
                    service.build(selection=selection, local_date=TODAY.isoformat())
                record = next(
                    entry
                    for entry in captured.records
                    if getattr(entry, "event", None) == "coach_context_projection"
                )
                fields = vars(record)
                self.assertEqual(selection.name, fields["context_profile"])
                self.assertEqual(selection.kind, fields["request_kind"])
                sizes = fields["section_characters"]
                self.assertEqual(
                    present(self.measured[label]) | {"projection"}, set(sizes)
                )
                self.assertTrue(all(size > 0 for size in sizes.values()))


if __name__ == "__main__":
    unittest.main()
