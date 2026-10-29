from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from backend.coach.planning_action_tools import CoachPlanningActionToolService
from backend.coach.proposal_creation import CoachProposalCreationService
from backend.coach.proposal_execution import CoachProposalExecutionService
from backend.coach.proposal_read import CoachProposalConfirmationService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import PlanningStateRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.runtime.maintenance import MaintenanceGate

NOW = "2026-09-20T08:00:00+00:00"


class CoachPlanningActionToolServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preview = Mock()
        self.preview.preview.return_value = {"id": "adjustment-1", "status": "preview"}
        self.adaptive_apply = Mock()
        self.adaptive_apply.apply.return_value = {"ok": True, "updated": 1}
        self.plans = Mock()
        self.plans.update.return_value = {"status": "updated", "plan_id": "plan-1"}
        self.history = Mock()
        self.history.preview.return_value = {
            "status": "preview",
            "change": {"id": "change-1"},
            "proposal": {
                "action_type": "undo_change",
                "payload": {"change_id": "change-1"},
            },
        }
        self.proposals = Mock()
        self.proposals.create.return_value = {"proposed_action": {"id": "proposal-1"}}
        self.factories = {
            "preview": Mock(return_value=self.preview),
            "adaptive_apply": Mock(return_value=self.adaptive_apply),
            "plans": Mock(return_value=self.plans),
            "history": Mock(return_value=self.history),
            "proposals": Mock(return_value=self.proposals),
        }
        self.service = CoachPlanningActionToolService(
            self.factories["preview"],
            self.factories["adaptive_apply"],
            self.factories["plans"],
            self.factories["history"],
            self.factories["proposals"],
        )

    def test_preview_returns_local_preview_only_after_operation_and_scope_checks(
        self,
    ) -> None:
        result = self.service.execute(
            "preview_adaptive_replan",
            {},
            {
                "operation": "preview_adaptive_replan",
                "authorization_scope": ["adaptive_replan"],
            },
            "turn-1",
            "csrf-hash-1",
        )

        self.assertEqual(
            result, {"ok": True, "id": "adjustment-1", "status": "preview"}
        )
        self.preview.preview.assert_called_once_with()
        self.adaptive_apply.apply.assert_not_called()

    def test_preview_rejects_missing_operation_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "preview_adaptive_replan",
                {},
                {"operation": "other", "authorization_scope": ["adaptive_replan"]},
                "turn-1",
                "csrf-hash-1",
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (403, "intent_scope_denied"),
        )
        self.factories["preview"].assert_not_called()

    def test_preview_rejects_missing_scope_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "preview_adaptive_replan",
                {},
                {"operation": "preview_adaptive_replan", "authorization_scope": []},
                "turn-1",
                "csrf-hash-1",
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (403, "intent_scope_denied"),
        )
        self.factories["preview"].assert_not_called()

    def test_apply_delegates_arguments_intent_and_later_client_turn(self) -> None:
        arguments = {"adjustment_id": "adjustment-1"}
        intent = {
            "operation": "apply_adaptive_replan",
            "authorization_scope": ["adaptive_replan:adjustment-1"],
        }

        result = self.service.execute(
            "apply_adaptive_replan", arguments, intent, "turn-2", "csrf-hash-1"
        )

        self.assertEqual(result, {"ok": True, "updated": 1})
        self.factories["adaptive_apply"].assert_called_once_with()
        self.adaptive_apply.apply.assert_called_once_with(arguments, intent, "turn-2")

    def test_apply_propagates_authorization_failure_from_adaptive_owner(self) -> None:
        denied = AppError(403, "denied", reason="intent_scope_denied")
        self.adaptive_apply.apply.side_effect = denied

        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "apply_adaptive_replan",
                {"adjustment_id": "adjustment-1"},
                {"operation": "other", "authorization_scope": []},
                "turn-2",
                "csrf-hash-1",
            )

        self.assertIs(raised.exception, denied)
        self.factories["adaptive_apply"].assert_called_once_with()

    def test_update_projects_structured_payload_and_accepts_plan_scope(self) -> None:
        arguments = {
            "payload": {"plan_id": "plan-1", "action": "update", "goal": "Base"}
        }
        intent = {
            "operation": "update_training_plan",
            "authorization_scope": ["training_plan:plan-1"],
        }

        result = self.service.execute(
            "update_training_plan", arguments, intent, "turn-1", "csrf-hash-1"
        )

        self.assertEqual(result, {"ok": True, "status": "updated", "plan_id": "plan-1"})
        self.plans.update.assert_called_once_with("plan-1", arguments["payload"])

    def test_update_accepts_local_plan_scope(self) -> None:
        arguments = {"payload": {"plan_id": "plan-1", "action": "delete"}}
        self.service.execute(
            "update_training_plan",
            arguments,
            {
                "operation": "update_training_plan",
                "authorization_scope": ["local_plan"],
            },
            "turn-1",
            "csrf-hash-1",
        )

        self.plans.update.assert_called_once_with("plan-1", arguments["payload"])

    def test_update_rejects_missing_operation_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "update_training_plan",
                {"payload": {"plan_id": "plan-1"}},
                {"operation": "other", "authorization_scope": ["training_plan:plan-1"]},
                "turn-1",
                "csrf-hash-1",
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (403, "intent_scope_denied"),
        )
        self.factories["plans"].assert_not_called()

    def test_update_rejects_scope_for_a_different_plan_before_factory(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "update_training_plan",
                {"payload": {"plan_id": "plan-1"}},
                {
                    "operation": "update_training_plan",
                    "authorization_scope": ["training_plan:plan-2"],
                },
                "turn-1",
                "csrf-hash-1",
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (403, "intent_scope_denied"),
        )
        self.factories["plans"].assert_not_called()

    def test_update_rejects_missing_payload_with_existing_client_error(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "update_training_plan",
                {},
                {
                    "operation": "update_training_plan",
                    "authorization_scope": ["local_plan"],
                },
                "turn-1",
                "csrf-hash-1",
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.reason), (400, "invalid_action")
        )
        self.factories["plans"].assert_not_called()

    def test_undo_creates_session_bound_proposal_and_excludes_raw_proposal(
        self,
    ) -> None:
        result = self.service.execute(
            "undo_training_change",
            {"change_id": "change-1"},
            {
                "operation": "undo_training_change",
                "authorization_scope": ["change:change-1"],
            },
            "turn-1",
            "csrf-hash-1",
        )

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "preview",
                "change": {"id": "change-1"},
                "proposed_action": {"id": "proposal-1"},
            },
        )
        self.history.preview.assert_called_once_with("change-1")
        self.proposals.create.assert_called_once_with(
            {"action_type": "undo_change", "payload": {"change_id": "change-1"}},
            "csrf-hash-1",
        )
        self.assertNotIn("proposal", result)

    def test_undo_applies_directly_when_apply_is_true(self) -> None:
        self.history.preview.return_value = {
            "status": "preview",
            "change": {"id": "change-1", "action": "update"},
            "proposal": {
                "action_type": "undo_change",
                "payload": {
                    "change_id": "change-1",
                    "expected_current_hash": "current-hash",
                },
            },
        }
        self.history.apply.return_value = {
            "status": "undone",
            "restored_entity_type": "planned_unit",
            "restored_entity_id": "unit-1",
        }
        result = self.service.execute(
            "undo_training_change",
            {"change_id": "change-1", "apply": True},
            {
                "operation": "undo_training_change",
                "authorization_scope": ["change:change-1"],
            },
            "turn-1",
            "csrf-hash-1",
        )
        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "undone",
                "change": {"id": "change-1", "action": "update"},
                "restored_entity_type": "planned_unit",
                "restored_entity_id": "unit-1",
            },
        )
        self.history.preview.assert_called_once_with("change-1")
        self.history.apply.assert_called_once_with(
            {
                "change_id": "change-1",
                "expected_current_hash": "current-hash",
            }
        )
        self.proposals.create.assert_not_called()

    def test_create_undo_with_apply_is_only_offered_as_a_card(self) -> None:
        proposal = {
            "action_type": "undo_change",
            "payload": {"change_id": "change-1", "expected_current_hash": "hash"},
        }
        self.history.preview.return_value = {
            "status": "preview",
            "change": {"id": "change-1", "action": "create"},
            "proposal": proposal,
        }

        result = self.service.execute(
            "undo_training_change",
            {"change_id": "change-1", "apply": True},
            {
                "operation": "undo_training_change",
                "authorization_scope": ["change:change-1"],
            },
            "turn-1",
            "csrf-hash-1",
        )

        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "preview",
                "change": {"id": "change-1", "action": "create"},
                "confirmation_required": True,
                "proposed_action": {"id": "proposal-1"},
            },
        )
        self.history.apply.assert_not_called()
        self.proposals.create.assert_called_once_with(proposal, "csrf-hash-1")

    def test_undo_rejects_missing_operation_before_history_or_proposal_factories(
        self,
    ) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "undo_training_change",
                {"change_id": "change-1"},
                {"operation": "other", "authorization_scope": ["change:change-1"]},
                "turn-1",
                "csrf-hash-1",
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (403, "intent_scope_denied"),
        )
        self.factories["history"].assert_not_called()
        self.factories["proposals"].assert_not_called()

    def test_undo_rejects_wrong_change_scope_before_factories(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.service.execute(
                "undo_training_change",
                {"change_id": "change-1"},
                {
                    "operation": "undo_training_change",
                    "authorization_scope": ["change:change-2"],
                },
                "turn-1",
                "csrf-hash-1",
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.reason),
            (403, "intent_scope_denied"),
        )
        self.factories["history"].assert_not_called()
        self.factories["proposals"].assert_not_called()

    def test_unknown_name_returns_none_without_constructing_any_owner(self) -> None:
        result = self.service.execute(
            "not_a_misc_tool", {}, {}, "turn-1", "csrf-hash-1"
        )

        self.assertIsNone(result)
        for factory in self.factories.values():
            factory.assert_not_called()


class CoachUndoToolPersistenceTests(unittest.TestCase):
    """The undo tool against real history, planning and proposal owners."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "undo.sqlite", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 0, ?)",
                (NOW,),
            )
        revisions = PlanningRevisionService(PlanningStateRepository(), lambda: NOW)
        ids = (uuid.UUID(int=number) for number in range(1, 100))
        calendar = Mock()
        calendar.constraints.return_value = []
        calendar.conflicts.return_value = []
        self.units = PlannedUnitService(
            self.manager,
            revisions,
            lambda: NOW,
            lambda: date(2026, 9, 20),
            lambda: next(ids),
            lambda value: value,
            calendar,
            lambda: None,
        )
        self.undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, None),
            None,
            None,
            None,
            self.units,
            None,
            revisions,
            profile_mutation_coordinator=threading.RLock(),
        )
        proposals = CoachProposalCreationService(self.manager, Mock())
        self.service = CoachPlanningActionToolService(
            Mock(), Mock(), Mock(), lambda: self.undo, lambda: proposals
        )
        self.local_id = self.units.create(
            {
                "date": "2026-09-21",
                "sport": "Run",
                "name": "Lauf",
                "description": "- 30m 60% locker",
                "duration_minutes": 30,
            }
        )["id"]

    def undo_with_apply(self, action: str) -> dict[str, Any]:
        with self.manager.reader() as db:
            change_id = db.execute(
                "SELECT id FROM change_history WHERE action=?", (action,)
            ).fetchone()["id"]
        result = self.service.execute(
            "undo_training_change",
            {"change_id": change_id, "apply": True},
            {
                "operation": "undo_training_change",
                "authorization_scope": [f"change:{change_id}"],
            },
            "turn-1",
            "csrf-hash-1",
        )
        assert result is not None
        return result

    def stored(self) -> tuple[list[str], list[str], int]:
        with self.manager.reader() as db:
            names = [
                row["name"]
                for row in db.execute(
                    "SELECT json_extract(payload, '$.name') AS name FROM planned_units"
                )
            ]
            actions = [
                row["action"]
                for row in db.execute(
                    "SELECT action FROM change_history ORDER BY rowid"
                )
            ]
            proposals = db.execute(
                "SELECT COUNT(*) AS count FROM coach_action_proposals"
            ).fetchone()["count"]
        return names, actions, proposals

    def test_create_undo_deletes_only_after_the_athlete_confirms_the_card(
        self,
    ) -> None:
        result = self.undo_with_apply("create")

        self.assertEqual(result["status"], "preview")
        self.assertTrue(result["confirmation_required"])
        card = result["proposed_action"]
        self.assertEqual(card["action_type"], "undo_change")
        self.assertEqual(self.stored(), (["Lauf"], ["create"], 1))

        confirmed = CoachProposalConfirmationService(self.manager).confirm(
            card["id"], "csrf-hash-1"
        )
        executed = CoachProposalExecutionService(
            self.manager, Mock(), self.undo, Mock(), MaintenanceGate()
        ).execute(confirmed["action_token"], "csrf-hash-1", card["payload_hash"])

        self.assertEqual(executed["status"], "undone")
        self.assertEqual(self.stored(), ([], ["create", "undo"], 1))

    def test_update_undo_with_apply_still_runs_directly(self) -> None:
        self.units.update(self.local_id, {"name": "Umbenannt"})

        result = self.undo_with_apply("update")

        self.assertEqual(result["status"], "undone")
        self.assertNotIn("proposed_action", result)
        self.assertEqual(self.stored(), (["Lauf"], ["create", "update", "undo"], 0))


if __name__ == "__main__":
    unittest.main()
