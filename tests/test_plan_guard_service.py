"""Plan guard: write rollback with findings, acknowledgement, brief, schemas."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from backend.activities.hr_cap import effective_caps
from backend.activities.workout_load import AthleteThresholds
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.vocabulary import Sport
from backend.coach.context_selection import select_coach_context
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.coach.tool_schemas import ACCEPT_PLAN_FINDINGS
from backend.db.manager import DatabaseManager
from backend.planning import calendar_load, plan_checks
from backend.planning.load_checks import LoadThresholds
from backend.planning.plan_guard_service import (
    IllnessNotConfirmedError,
    PlanCheckError,
    PlanGuardService,
    build_planning_brief,
    illness_confirmation,
    last_tests,
    read_progress,
    recent_illness,
)
from backend.planning.planned_unit_load import estimate_planned_unit
from backend.planning.sport import planned_sport_environment

TODAY = date(2026, 11, 2)


def _easy_run_cap(unit: dict[str, Any]) -> dict[str, Any]:
    """The heart-rate cap an easy run unit needs (percentages from the cap table)."""
    easy_run = planned_sport_environment(unit)[
        0
    ] is Sport.RUN and not plan_checks.is_hard(unit)
    return {"hr_cap": effective_caps(None)["easy"]} if easy_run else {}


def hard_pair() -> list[dict[str, Any]]:
    return [
        {
            "local_id": "a",
            "date": "2026-11-04",
            "sport": "run",
            "planned_duration_s": 3600,
            "planned_intensity": 0.9,
        },
        {
            "local_id": "b",
            "date": "2026-11-05",
            "sport": "ride",
            "planned_duration_s": 3600,
            "description": "Z5 intervals",
        },
    ]


class PlanGuardWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="plan-guard-")
        self.addCleanup(self.temporary.cleanup)
        path = Path(self.temporary.name) / "guard.sqlite3"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE synthetic_writes (value TEXT NOT NULL)")
        self.manager = DatabaseManager(
            path, sqlite3, row_factory=sqlite3.Row, persist_connections=False
        )
        self.addCleanup(self.manager.close)
        self.units: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []
        self.published: list[str] = []
        self.write_units: list[dict[str, Any]] | None = None
        self.default_focus = True
        # A reported illness makes the hard pair a blocking finding.
        self.illness = "Fieber"
        self.guard = PlanGuardService(
            planned_units=lambda: list(self.units),
            completed_activities=lambda: list(self.completed),
            competitions=list,
            illness=lambda: self.illness,
            progress=lambda: {"week_list": []},
            training_model=lambda: "pyramidal",
            today=lambda: TODAY,
            estimate_unit=lambda unit: estimate_planned_unit(unit, AthleteThresholds()),
        )
        self.dispatch = Mock()
        self.dispatch.execute.side_effect = self.write
        self.service = CoachStructuredToolExecutionService(
            self.manager,
            threading.RLock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            self.dispatch,
            threading.RLock(),
            lambda: self.guard,
        )

    def write(self, name: str, arguments: dict[str, Any], **_: Any) -> dict[str, Any]:
        with self.manager.unit_of_work() as db:
            db.execute("INSERT INTO synthetic_writes VALUES (?)", (name,))
        self.manager.after_commit(lambda: self.published.append(name))
        written = self.write_units if self.write_units is not None else hard_pair()
        # Run and ride units carry the focus a Coach write now has to name.
        self.units = [
            {
                **unit,
                "session_focus": "threshold" if plan_checks.is_hard(unit) else "easy",
                **_easy_run_cap(unit),
            }
            if self.default_focus
            and planned_sport_environment(unit)[0] in {Sport.RUN, Sport.RIDE}
            and "session_focus" not in unit
            else unit
            for unit in written
        ]
        self.seen_arguments = arguments
        return {"ok": True, "status": "applied"}

    def run_tool(self, name: str, **arguments: Any) -> dict[str, Any]:
        metadata = {"name": name, "arguments": arguments}
        with self.manager.unit_of_work():
            return self.service.execute(
                metadata,
                action={},
                context={},
                conversation_id="c",
                client_turn_id="t",
                session_csrf_hash="h",
                sync_job_ids=[],
                cancel_event=None,
            )

    def stored(self) -> int:
        with self.manager.reader() as db:
            return db.execute("SELECT COUNT(*) FROM synthetic_writes").fetchone()[0]

    def test_violation_rolls_back_and_returns_findings(self) -> None:
        with self.assertRaises(PlanCheckError) as raised:
            self.run_tool("replace_training_plan", workouts=[{}])
        self.assertEqual(
            ["illness_hard", "illness_hard"],
            [f["code"] for f in raised.exception.findings],
        )
        self.assertEqual(0, self.stored())

    def test_rolled_back_write_publishes_nothing_and_committed_write_does(self) -> None:
        with self.assertRaises(PlanCheckError):
            self.run_tool("replace_training_plan", workouts=[{}])
        self.assertEqual([], self.published)
        self.illness = ""
        self.run_tool("replace_training_plan", workouts=[{}])
        self.assertEqual(["replace_training_plan"], self.published)

    def test_distribution_note_in_write_result(self) -> None:
        self.illness = ""
        self.guard = PlanGuardService(
            planned_units=lambda: list(self.units),
            completed_activities=list,
            competitions=list,
            illness=lambda: "",
            progress=lambda: {"week_list": []},
            training_model=lambda: "polarized",
            today=lambda: TODAY,
            estimate_unit=lambda unit: estimate_planned_unit(unit, AthleteThresholds()),
        )
        self.write_units = [
            {
                "local_id": "r",
                "date": "2026-11-04",
                "sport": "Ride",
                "description": "- 240m Z2\n- 120m Z3\n- 20m Z6\n",
            }
        ]
        result = self.run_tool("replace_training_plan", workouts=[{}])
        self.assertEqual(
            ["intensity_distribution"],
            [note["code"] for note in result["plan_check_notes"]],
        )
        self.assertFalse(result["plan_check_notes"][0]["blocking"])

    def test_load_findings_save_with_notes(self) -> None:
        self.illness = ""
        result = self.run_tool("replace_training_plan", workouts=[{}])
        self.assertEqual(1, self.stored())
        note = result["plan_check_notes"][0]
        self.assertEqual("back_to_back_hard", note["code"])
        self.assertIn("practice-based", note["evidence_strength"])

    def test_calendar_conflict_is_saved_as_note(self) -> None:
        self.illness = ""
        self.guard = PlanGuardService(
            planned_units=lambda: list(self.units),
            completed_activities=list,
            competitions=list,
            illness=lambda: "",
            progress=lambda: {"week_list": []},
            training_model=lambda: "pyramidal",
            today=lambda: TODAY,
            estimate_unit=lambda unit: estimate_planned_unit(unit, AthleteThresholds()),
            calendar_events=lambda: [
                {
                    "start_local": "2026-11-04T09:00:00",
                    "end_local": "2026-11-04T10:00:00",
                }
            ],
        )
        self.write_units = [
            {**hard_pair()[0], "starts_at_local": "2026-11-04T09:30:00"}
        ]
        result = self.run_tool("replace_training_plan", workouts=[{}])
        note = next(
            item
            for item in result["plan_check_notes"]
            if item["code"] == "calendar_load"
        )
        self.assertFalse(note["blocking"])
        self.assertTrue(note["evidence"]["overlap"])
        self.assertEqual(self.stored(), 1)

    def test_failure_projection_carries_findings(self) -> None:
        service = CoachStructuredToolFailureService(
            Path(self.temporary.name), Mock(), frozenset({"replace_training_plan"})
        )
        with self.assertRaises(PlanCheckError) as raised:
            self.run_tool("replace_training_plan", workouts=[{}])
        result = service.project(
            raised.exception,
            name="replace_training_plan",
            call_id="1",
            effect_key="e",
            step_key="s",
            repair_key=None,
            scope_repair_key=None,
            request_binding_key=None,
            plan_effect_key=None,
            action={},
            command_receipts=[],
        )
        self.assertFalse(result["ok"])
        self.assertEqual("plan_check_failed", result["reason"])
        self.assertEqual("illness_hard", result["findings"][0]["code"])

    def test_acknowledgement_writes_and_reports_text_only(self) -> None:
        result = self.run_tool(
            "replace_training_plan",
            workouts=[{}],
            accept_plan_findings=["illness_hard"],
        )
        self.assertEqual(1, self.stored())
        self.assertNotIn("accept_plan_findings", self.seen_arguments)
        self.assertEqual(
            [
                "back_to_back_hard",
                "illness_hard",
                "illness_hard",
                "intensity_distribution",
            ],
            sorted(f["code"] for f in result["plan_check_notes"]),
        )

    def test_adaptive_replan_is_plan_checked_by_its_own_service(self) -> None:
        from backend.coach import tool_execution_service as tools

        self.assertIn("apply_adaptive_replan", tools.PLAN_CHECKED_TOOLS)
        self.assertIn("apply_adaptive_replan", tools.SELF_GUARDED_TOOLS)
        self.run_tool("apply_adaptive_replan", adjustment_id="x")
        # The generic wrapper stays out; the tool's own service checks the plan.
        self.assertEqual(1, self.stored())
        self.dispatch.execute.assert_called_once()

    def test_listing_without_a_finding_does_not_ask(self) -> None:
        self.illness = ""
        asked: list[int] = []

        def confirm() -> bool:
            asked.append(1)
            return False

        with illness_confirmation(confirm):
            self.run_tool(
                "replace_training_plan", accept_plan_findings=["illness_hard"]
            )
        self.assertEqual(1, self.stored())
        self.assertEqual([], asked)

    def test_finding_without_confirmation_rolls_back(self) -> None:
        with (
            illness_confirmation(lambda: False),
            self.assertRaises(IllnessNotConfirmedError) as raised,
        ):
            self.run_tool(
                "replace_training_plan", accept_plan_findings=["illness_hard"]
            )
        self.assertEqual("illness_not_confirmed", raised.exception.reason)
        self.assertEqual("illness_hard", raised.exception.findings[0]["code"])
        self.assertEqual(0, self.stored())
        self.assertEqual([], self.published)

    def test_finding_with_confirmation_is_saved(self) -> None:
        with illness_confirmation(lambda: True):
            self.run_tool(
                "replace_training_plan", accept_plan_findings=["illness_hard"]
            )
        self.assertEqual(1, self.stored())

    def test_other_code_does_not_cover_the_finding(self) -> None:
        with self.assertRaises(PlanCheckError):
            self.run_tool("replace_training_plan", accept_plan_findings=[])
        self.assertEqual(0, self.stored())

    def test_harder_session_during_illness_blocks_again(self) -> None:
        self.units = hard_pair()
        harder = hard_pair()
        harder[0]["planned_duration_s"] = 9000
        self.write_units = harder
        with self.assertRaises(PlanCheckError):
            self.run_tool("replace_training_plan")
        self.assertEqual(0, self.stored())

    def test_shortening_an_illness_time_session_is_saved(self) -> None:
        longer = hard_pair()
        longer[0]["planned_duration_s"] = 9000
        self.units = longer
        self.write_units = hard_pair()
        self.run_tool("replace_training_plan")
        self.assertEqual(1, self.stored())

    def test_easier_but_much_longer_illness_session_blocks(self) -> None:
        self.units = hard_pair()
        easier = hard_pair()
        easier[0].pop("planned_intensity")
        easier[0]["planned_duration_s"] = 12000
        self.write_units = easier
        with self.assertRaises(PlanCheckError):
            self.run_tool("replace_training_plan")
        self.assertEqual(0, self.stored())

    def test_spike_growing_into_a_warning_is_a_new_note(self) -> None:
        self.illness = ""
        self.completed = [
            {
                "sport": "run",
                "started_at_local": "2026-10-30T08:00:00",
                "moving_duration_s": 3600,
                "distance_m": 10000,
            }
        ]
        run = {
            "local_id": "r",
            "date": "2026-11-06",
            "sport": "run",
            "planned_duration_s": 4200,
            "description": "- 12km 70% pace",
        }
        self.units = [run]
        self.write_units = [{**run, "description": "- 15km 70% pace"}]
        result = self.run_tool("replace_training_plan")
        note = result["plan_check_notes"][0]
        self.assertEqual("warning", note["evidence"]["severity"])
        self.assertFalse(note["blocking"])

    def test_load_spike_note_flows_through_the_write(self) -> None:
        self.illness = ""
        self.guard = PlanGuardService(
            planned_units=lambda: list(self.units),
            completed_activities=lambda: list(self.completed),
            competitions=list,
            illness=lambda: "",
            progress=lambda: {"week_list": []},
            training_model=lambda: "pyramidal",
            today=lambda: TODAY,
            estimate_unit=lambda unit: estimate_planned_unit(unit, AthleteThresholds()),
            thresholds=lambda: LoadThresholds(
                {Sport.RIDE: AthleteThresholds(zones=ZoneSettings(ftp=250.0))}
            ),
        )
        self.completed = [
            {
                "sport": "ride",
                "started_at_local": "2026-10-30T08:00:00",
                "moving_duration_s": 3600,
                "normalized_power": 200,
            }
        ]
        self.units = []
        self.write_units = [
            {
                "local_id": "b",
                "date": "2026-11-06",
                "sport": "ride",
                "planned_duration_s": 3600,
                "description": "- 60m 100%",
            }
        ]
        result = self.run_tool("replace_training_plan")
        notes = [n for n in result["plan_check_notes"] if n["code"] == "load_spike"]
        self.assertEqual("warning", notes[0]["evidence"]["severity"])
        self.assertFalse(notes[0]["blocking"])

    def test_existing_findings_do_not_block_unrelated_writes(self) -> None:
        self.units = hard_pair()
        self.run_tool("replace_training_plan")
        self.assertEqual(1, self.stored())

    def test_coach_strength_units_need_structure_focus_and_intensity(self) -> None:
        self.illness = ""
        free_text = {
            "local_id": "s",
            "date": "2026-11-04",
            "sport": "strength",
            "name": "Krafttraining Oberkörper",
            "description": "Face Pulls: 4 Sätze; Dips: 4 Sätze",
            "planned_duration_s": 2700,
        }
        complete = {
            **free_text,
            "strength_structure": [{"name": "Face Pulls", "sets": 4, "reps": 12}],
            "session_focus": "upper",
            "strength_intensity": "moderate",
        }
        cases = {
            "new unit": ([], [free_text]),
            "moved unit": ([free_text], [{**free_text, "date": "2026-11-07"}]),
            "made-up unit": (
                [],
                [{**free_text, "local_id": "n", "name": "Kraft – nachgeholt"}],
            ),
            "focus only": ([], [{**free_text, "session_focus": "upper"}]),
        }
        for label, (before, after) in cases.items():
            with self.subTest(label):
                self.units, self.write_units = list(before), after
                with self.assertRaises(PlanCheckError) as raised:
                    # Never acceptable: it is data, not a training deviation.
                    self.run_tool(
                        "apply_training_changes", accept_plan_findings=["illness_hard"]
                    )
                self.assertEqual(
                    ["strength_incomplete"],
                    [item["code"] for item in raised.exception.findings],
                )
                self.assertEqual(0, self.stored())
        # A complete unit saves, and an untouched older free-text unit does not
        # block an unrelated write.
        self.units, self.write_units = (
            [free_text],
            [free_text, {**complete, "local_id": "c"}],
        )
        self.run_tool("apply_training_changes")
        self.assertEqual(1, self.stored())

    def test_coach_run_and_ride_units_need_a_session_focus(self) -> None:
        self.illness = ""
        self.default_focus = False
        run = {
            "local_id": "r",
            "date": "2026-11-04",
            "sport": "run",
            "name": "Lockerer Lauf",
            "planned_duration_s": 2700,
        }
        cases = {
            "new run": ([], [run]),
            "moved run": ([run], [{**run, "date": "2026-11-07"}]),
            "new ride": ([], [{**run, "local_id": "b", "sport": "ride"}]),
            "blank focus": ([], [{**run, "session_focus": " "}]),
        }
        for label, (before, after) in cases.items():
            with self.subTest(label):
                self.units, self.write_units = list(before), after
                with self.assertRaises(PlanCheckError) as raised:
                    # Data, not a training deviation: it can never be accepted.
                    self.run_tool(
                        "apply_training_changes", accept_plan_findings=["illness_hard"]
                    )
                self.assertEqual(
                    ["focus_missing"],
                    [item["code"] for item in raised.exception.findings],
                )
                self.assertIn("session_focus", raised.exception.findings[0]["message"])
                self.assertEqual(0, self.stored())
        # With a focus the write saves; an untouched older unit without one and a
        # sport without a focus vocabulary do not block an unrelated write.
        swim = {**run, "local_id": "w", "sport": "swim"}
        self.units, self.write_units = (
            [run],
            [
                run,
                swim,
                {
                    **run,
                    "local_id": "c",
                    "session_focus": "easy",
                    "hr_cap": effective_caps(None)["easy"],
                },
            ],
        )
        self.run_tool("apply_training_changes")
        self.assertEqual(1, self.stored())

    def test_waived_codes_neither_block_nor_report(self) -> None:
        self.illness = ""
        self.units = [
            {
                "local_id": "r",
                "date": "2026-11-07",
                "sport": "run",
                "name": "Lockerer Lauf",
                "planned_duration_s": 2700,
            }
        ]
        with self.assertRaises(PlanCheckError):
            self.guard.verify([], [])
        self.assertEqual([], self.guard.verify([], [], waived=("focus_missing",)))

    def test_inherited_gaps_pass_only_for_units_that_already_had_them(self) -> None:
        # An approved replan rewrites a legacy easy run without hr_cap and a
        # legacy strength unit without structure: the gaps are not its doing.
        self.illness = ""
        legacy_run = {
            "local_id": "r",
            "date": "2026-11-07",
            "sport": "run",
            "name": "Lockerer Lauf",
            "session_focus": "easy",
            "planned_duration_s": 2700,
        }
        legacy_strength = {
            "local_id": "s",
            "date": "2026-11-08",
            "sport": "strength",
            "name": "Kraft",
            "description": "Kniebeuge schwer",
            "planned_duration_s": 2700,
        }
        self.units = [legacy_run, legacy_strength]
        before = self.guard.findings()
        self.units = [
            {**legacy_run, "planned_duration_s": 1800, "description": "- 30m Z1 HR"},
            {**legacy_strength, "description": "- 30m Mobility"},
        ]
        codes = plan_checks.REQUIRED_CODES
        self.assertEqual([], self.guard.verify(before, [], inherited=codes))
        # A unit the write leaves without data it had still blocks.
        complete = {
            **legacy_strength,
            "strength_structure": [{"name": "Kniebeuge", "sets": 3, "reps": 5}],
            "session_focus": "legs",
            "strength_intensity": "heavy",
        }
        self.units = [complete]
        before = self.guard.findings()
        self.units = [legacy_strength]
        with self.assertRaises(PlanCheckError) as raised:
            self.guard.verify(before, [], inherited=codes)
        self.assertEqual(
            ["strength_incomplete"],
            [item["code"] for item in raised.exception.findings],
        )

    def test_unchecked_tools_skip_the_guard(self) -> None:
        self.guard = Mock()
        self.run_tool("save_checkin")
        self.guard.findings.assert_not_called()
        self.assertEqual(1, self.stored())


class AllDayEventsBriefTests(unittest.TestCase):
    def test_all_day_events_are_listed_per_date_and_trimmed_last_day_first(self):
        events = [
            {
                "name": "Reise",
                "all_day": True,
                "start_local": "2026-11-04T00:00:00",
                "end_local": "2026-11-05T00:00:00",
                "no_training": True,
            },
            {
                "name": "Timed",
                "start_local": "2026-11-04T09:00:00",
                "end_local": "2026-11-04T10:00:00",
            },
        ]
        listed = calendar_load.all_day_brief(events, TODAY, 7)
        self.assertEqual(["2026-11-04"], list(listed))
        self.assertEqual("Reise", listed["2026-11-04"][0]["name"])
        self.assertTrue(listed["2026-11-04"][0]["no_training"])
        brief = build_planning_brief(
            progress={},
            completed=[],
            competitions=[],
            training_model="pyramidal",
            today=TODAY,
            all_day_events=listed,
        )
        self.assertEqual(listed, brief["all_day_events"])
        self.assertIn("never subtracted", brief["all_day_events_source"])


class LastTestsTests(unittest.TestCase):
    def test_last_completed_test_or_race_per_sport(self):
        units = [
            {"date": "2026-09-20", "sport": "run", "session_focus": "test"},
            # Planned but never run: no completed activity on that day.
            {"date": "2026-10-10", "sport": "run", "session_focus": "test"},
            {"date": "2026-10-20", "sport": "run", "session_focus": "easy"},
            {"date": "2026-11-05", "sport": "ride", "session_focus": "test"},
            {"date": "2026-05-01", "sport": "ride", "session_focus": "test"},
        ]
        completed = [
            {"sport": "run", "started_at_local": "2026-09-20T08:00:00"},
            {"sport": "run", "started_at_local": "2026-10-20T08:00:00"},
            {"sport": "ride", "started_at_local": "2026-05-01T08:00:00"},
        ]
        competitions = [{"date": "2026-09-27", "sport": "Running", "name": "10k"}]
        result = last_tests(units, competitions, completed, TODAY)
        # The race beats the older completed test; missed, future and old tests do not count.
        self.assertEqual("2026-09-27", result["run"])
        self.assertIsNone(result["ride"])
        self.assertIn("session_focus test", result["source"])
        without_race = last_tests(units, [], completed, TODAY)
        self.assertEqual("2026-09-20", without_race["run"])


class PlanBriefTests(unittest.TestCase):
    def test_brief_progress_read_skips_mean_max_curves(self) -> None:
        reports = Mock()
        reports.timezone.return_value = "UTC"
        read_progress(reports)
        reports.report.progress.assert_called_once_with(
            {"days": 42}, "UTC", with_curves=False
        )

    def test_brief_is_bounded_and_labelled(self) -> None:
        weeks = [
            {
                "week_start": f"2026-10-{day:02d}",
                "week_end": f"2026-10-{day + 6:02d}",
                "status": "recorded",
                "sports": {
                    "run": {
                        "sessions": 2,
                        "duration_s": {"value": 3600},
                        "training_load": {"value": 80},
                        "intensity_3zone": {
                            "seconds": {"low": 1, "moderate": 2, "high": 3}
                        },
                    }
                },
            }
            for day in (1, 8, 15, 22)
        ]
        brief = build_planning_brief(
            progress={"week_list": weeks},
            completed=[
                {
                    "sport": "run",
                    "started_at_local": "2026-10-09T08:00:00",
                    "moving_duration_s": 3000,
                    "intensity": 0.9,
                }
            ],
            competitions=[{"date": "2026-12-01", "name": "Race", "priority": "A"}],
            training_model="polarized",
            today=TODAY,
        )
        self.assertEqual("polarized", brief["training_model"])
        self.assertEqual(1, brief["weeks"][1]["run"]["hard_sessions"])
        self.assertEqual(50, brief["longest_run_30d_minutes"])
        self.assertEqual("Race", brief["next_competitions"][0]["name"])
        self.assertEqual(set(plan_checks.FINDING_CODES), set(brief["plan_checks"]))
        self.assertIn("source", brief)
        phase = brief["season_phase"]
        self.assertEqual(("peak", 4), (phase["phase"], phase["weeks_to_race"]))
        self.assertEqual("2026-12-01", phase["race"]["date"])

    def test_brief_phase_unknown_without_target_race(self) -> None:
        brief = build_planning_brief(
            progress={},
            completed=[],
            competitions=[{"date": "2026-12-01", "name": "Run", "priority": "C"}],
            training_model="pyramidal",
            today=TODAY,
        )
        self.assertEqual("unknown", brief["season_phase"]["phase"])

    def test_brief_section_only_for_plan_kinds(self) -> None:
        for kind in ("plan_week", "plan_block", "adjust_week"):
            selection = select_coach_context("Plane", {}, request_kind=kind)
            self.assertIn("planning_brief", selection.sections)
        for other in (None, "progress_review", "session_analysis"):
            selection = select_coach_context("Plane", {}, request_kind=other)
            self.assertNotIn("planning_brief", selection.sections)

    def test_recent_illness_reads_latest_checkin(self) -> None:
        rows = [
            {"checkin_date": "2026-11-02", "illness": "Erkältung"},
            {"checkin_date": "2026-10-20", "illness": "alt"},
        ]
        self.assertEqual("Erkältung", recent_illness(rows, TODAY))
        self.assertEqual("", recent_illness(rows[1:], TODAY))

    def test_schema_enum_matches_rule_codes(self) -> None:
        self.assertEqual(
            list(plan_checks.BLOCKING_CODES), ACCEPT_PLAN_FINDINGS["items"]["enum"]
        )


if __name__ == "__main__":
    unittest.main()
