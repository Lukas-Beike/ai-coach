"""Direct approval-boundary regression tests for adaptive Coach application."""

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from backend.activities.workout_load import AthleteThresholds
from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.db.manager import DatabaseManager
from backend.errors import AppError
from backend.planning.plan_guard_service import PlanCheckError, PlanGuardService
from backend.planning.planned_unit_load import estimate_planned_unit


class CoachAdaptiveApplyTests(unittest.TestCase):
    def setUp(self):
        self.preview = Mock()
        self.illness_sync = Mock()
        self.db = Mock()
        self.manager = Mock()

        @contextmanager
        def unit_of_work():
            yield self.db

        self.manager.unit_of_work.side_effect = unit_of_work
        self.service = CoachAdaptiveApplyService(
            self.preview, self.illness_sync, self.manager, threading.RLock()
        )
        self.intent = {
            "operation": "apply_adaptive_replan",
            "target_system": "local",
            "authorization_scope": ["adaptive_replan:adjustment-1"],
            "request": {"source_message_ids": [20]},
        }
        self.preview.latest_preview.return_value = {
            "id": "adjustment-1",
            "status": "preview",
            "published_message_id": 10,
        }
        self.rows(current=20, published=10, first_reply=20)
        self.illness_sync.complete.return_value = {"updated": 1}

    def rows(self, *, current, published, first_reply):
        self.db.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"id": current})),
            Mock(fetchone=Mock(return_value={"id": published})),
            Mock(fetchone=Mock(return_value={"id": first_reply})),
        ]

    def test_later_turn_apply_succeeds_without_remote_sync(self):
        self.assertEqual(
            self.service.apply(
                {"adjustment_id": "adjustment-1"}, self.intent, "turn-2"
            ),
            {"ok": True, "updated": 1},
        )
        self.illness_sync.apply_local.assert_called_once_with("adjustment-1")
        self.illness_sync.complete.assert_called_once_with(
            self.illness_sync.apply_local.return_value,
            sync_illness_to_intervals=False,
        )

    def test_same_turn_or_missing_provenance_cannot_apply(self):
        self.rows(current=10, published=10, first_reply=20)
        with self.assertRaises(AppError) as raised:
            self.service.apply({"adjustment_id": "adjustment-1"}, self.intent, "turn-1")
        self.assertEqual(raised.exception.reason, "adaptive_approval_required")
        self.illness_sync.apply_local.assert_not_called()

    def test_only_the_first_athlete_message_after_the_preview_can_approve(self):
        self.rows(current=30, published=10, first_reply=20)
        self.intent["request"]["source_message_ids"] = [20, 30]
        with self.assertRaises(AppError) as raised:
            self.service.apply({"adjustment_id": "adjustment-1"}, self.intent, "turn-3")
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(raised.exception.reason, "adaptive_approval_required")
        self.illness_sync.apply_local.assert_not_called()

    def test_a_missing_publication_or_later_message_cannot_approve(self):
        for published, first_reply in ((None, None), (10, None)):
            with self.subTest(published=published):
                self.db.execute.side_effect = [
                    Mock(fetchone=Mock(return_value={"id": 20})),
                    Mock(
                        fetchone=Mock(
                            return_value={"id": published} if published else None
                        )
                    ),
                    Mock(fetchone=Mock(return_value={"id": first_reply})),
                ]
                with self.assertRaises(AppError) as raised:
                    self.service.apply(
                        {"adjustment_id": "adjustment-1"}, self.intent, "turn-2"
                    )
                self.assertEqual(raised.exception.reason, "adaptive_approval_required")
        self.illness_sync.apply_local.assert_not_called()

    def test_remote_sync_requires_target_and_explicit_scope_before_db_read(self):
        with self.assertRaises(AppError) as raised:
            self.service.apply(
                {"adjustment_id": "adjustment-1", "sync_illness_to_intervals": True},
                self.intent,
                "turn-2",
            )
        self.assertEqual(raised.exception.reason, "intent_scope_denied")
        self.preview.latest_preview.assert_not_called()
        self.db.execute.assert_not_called()
        self.illness_sync.apply_local.assert_not_called()


class AdaptiveApplyPlanGuardTests(unittest.TestCase):
    """The approved replan is checked like any plan write, atomically."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="adaptive-guard-")
        self.addCleanup(self.temporary.cleanup)
        path = Path(self.temporary.name) / "guard.sqlite3"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE synthetic_writes (value TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, "
                "client_turn_id TEXT)"
            )
            db.execute("INSERT INTO messages VALUES (10, 'assistant', NULL)")
            db.execute("INSERT INTO messages VALUES (20, 'user', 'turn-2')")
        self.manager = DatabaseManager(
            path, sqlite3, row_factory=sqlite3.Row, persist_connections=False
        )
        self.addCleanup(self.manager.close)
        self.illness = ""
        self.units: list[dict] = []
        self.guard = PlanGuardService(
            planned_units=lambda: list(self.units),
            completed_activities=list,
            competitions=list,
            illness=lambda: self.illness,
            progress=lambda: {"week_list": []},
            training_model=lambda: "pyramidal",
            today=lambda: date(2026, 11, 2),
            estimate_unit=lambda unit: estimate_planned_unit(unit, AthleteThresholds()),
        )
        preview = Mock()
        preview.latest_preview.return_value = {
            "id": "adjustment-1",
            "status": "preview",
            "published_message_id": 10,
        }
        self.sync = Mock()
        self.sync.apply_local.side_effect = self.apply_local
        self.sync.complete.return_value = {"updated": 2}
        self.service = CoachAdaptiveApplyService(
            preview,
            self.sync,
            self.manager,
            threading.RLock(),
            lambda: self.guard,
        )
        self.intent = {
            "operation": "apply_adaptive_replan",
            "target_system": "local",
            "authorization_scope": ["adaptive_replan:adjustment-1"],
            "request": {"source_message_ids": [20]},
        }

    def apply_local(self, adjustment_id):
        with self.manager.unit_of_work() as db:
            db.execute("INSERT INTO synthetic_writes VALUES (?)", (adjustment_id,))
        self.units = [
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
        return {"status": "applied"}

    def stored(self) -> int:
        with self.manager.reader() as db:
            return db.execute("SELECT COUNT(*) FROM synthetic_writes").fetchone()[0]

    def apply(self, **arguments):
        return self.service.apply(
            {"adjustment_id": "adjustment-1", **arguments}, self.intent, "turn-2"
        )

    def test_new_finding_is_returned_as_a_note(self):
        result = self.apply()
        self.assertEqual(1, self.stored())
        self.assertEqual(
            ["back_to_back_hard"], [n["code"] for n in result["plan_check_notes"]]
        )
        self.sync.complete.assert_called_once()

    def test_illness_block_rolls_back_and_skips_the_remote_sync(self):
        self.illness = "Fieber"
        with self.assertRaises(PlanCheckError) as raised:
            self.apply(sync_illness_to_intervals=False)
        self.assertEqual("illness_hard", raised.exception.findings[0]["code"])
        self.assertEqual(0, self.stored())
        self.sync.complete.assert_not_called()

    def test_acknowledged_illness_finding_is_applied(self):
        self.illness = "Fieber"
        result = self.apply(accept_plan_findings=["illness_hard"])
        self.assertEqual(1, self.stored())
        self.assertIn("illness_hard", [n["code"] for n in result["plan_check_notes"]])

    def execute_approved_proposal(self, arguments):
        """The approved-proposal route: execution service, dispatcher's planning tail."""
        actions = CoachPlanningActionToolService(
            Mock(), lambda: self.service, Mock(), Mock(), Mock()
        )
        dispatch = Mock()
        dispatch.execute.side_effect = (
            lambda name, args, *, intent, client_turn_id, session_csrf_hash, **_: (
                actions.execute(name, args, intent, client_turn_id, session_csrf_hash)
            )
        )
        executor = CoachProposalExecutionService(
            self.manager, Mock(), Mock(), Mock(), Mock(), lambda: dispatch
        )
        intent = self.intent
        if arguments.get("sync_illness_to_intervals"):
            intent = {
                **intent,
                "target_system": "intervals",
                "authorization_scope": [
                    *intent["authorization_scope"],
                    "intervals_sync",
                ],
            }
        context = (
            "apply_adaptive_replan",
            {"adjustment_id": "adjustment-1", **arguments},
            intent,
            "conversation",
            "turn-2",
        )
        return executor._execute_coach_write("csrf", context)

    def test_approved_proposal_is_plan_checked_and_a_block_rolls_back(self):
        self.illness = "Fieber"
        with self.assertRaises(PlanCheckError):
            self.execute_approved_proposal({"sync_illness_to_intervals": True})
        self.assertEqual(0, self.stored())
        self.sync.complete.assert_not_called()

    def test_approved_proposal_returns_plan_check_notes(self):
        result = self.execute_approved_proposal({})
        self.assertEqual(1, self.stored())
        self.assertEqual(
            ["back_to_back_hard"], [n["code"] for n in result["plan_check_notes"]]
        )


if __name__ == "__main__":
    unittest.main()
