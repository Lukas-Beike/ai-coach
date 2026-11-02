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

from backend.coach.context_selection import select_coach_context
from backend.coach.tool_execution_service import CoachStructuredToolExecutionService
from backend.coach.tool_failures import CoachStructuredToolFailureService
from backend.coach.tool_schemas import ACCEPT_PLAN_FINDINGS
from backend.db.manager import DatabaseManager
from backend.planning import plan_checks
from backend.planning.plan_guard_service import (
    PlanCheckError,
    PlanGuardService,
    build_planning_brief,
    recent_illness,
)

TODAY = date(2026, 11, 2)


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
        self.write_units: list[dict[str, Any]] | None = None
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
            Mock(),
            self.dispatch,
            threading.RLock(),
            lambda: self.guard,
        )

    def write(self, name: str, arguments: dict[str, Any], **_: Any) -> dict[str, Any]:
        with self.manager.unit_of_work() as db:
            db.execute("INSERT INTO synthetic_writes VALUES (?)", (name,))
        self.units = self.write_units if self.write_units is not None else hard_pair()
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

    def test_load_findings_save_with_notes(self) -> None:
        self.illness = ""
        result = self.run_tool("replace_training_plan", workouts=[{}])
        self.assertEqual(1, self.stored())
        note = result["plan_check_notes"][0]
        self.assertEqual("back_to_back_hard", note["code"])
        self.assertIn("practice-based", note["evidence_strength"])

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
            ["back_to_back_hard", "illness_hard", "illness_hard"],
            sorted(f["code"] for f in result["plan_check_notes"]),
        )

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

    def test_spike_growing_into_a_warning_is_a_new_note(self) -> None:
        self.illness = ""
        self.completed = [
            {
                "sport": "run",
                "started_at_local": "2026-10-30T08:00:00",
                "moving_duration_s": 3600,
            }
        ]
        run = {
            "local_id": "r",
            "date": "2026-11-06",
            "sport": "run",
            "planned_duration_s": 4200,
        }
        self.units = [run]
        self.write_units = [{**run, "planned_duration_s": 7200}]
        result = self.run_tool("replace_training_plan")
        note = result["plan_check_notes"][0]
        self.assertEqual("warning", note["evidence"]["severity"])
        self.assertFalse(note["blocking"])

    def test_existing_findings_do_not_block_unrelated_writes(self) -> None:
        self.units = hard_pair()
        self.run_tool("replace_training_plan")
        self.assertEqual(1, self.stored())

    def test_unchecked_tools_skip_the_guard(self) -> None:
        self.guard = Mock()
        self.run_tool("save_checkin")
        self.guard.findings.assert_not_called()
        self.assertEqual(1, self.stored())


class PlanBriefTests(unittest.TestCase):
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

    def test_brief_section_only_for_plan_kinds(self) -> None:
        for kind in ("plan_week", "plan_block"):
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
