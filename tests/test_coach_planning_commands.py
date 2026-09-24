"""Durable claim, scope, replay, and rollback contracts for planning commands."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from test_coach_dialogue import DialogueHarness, server

from backend.coach.authorization import coach_session_key
from backend.coach.proposals import coach_action_hash


class CoachPlanningCommandTests(DialogueHarness, unittest.TestCase):
    def payload(self, turn="synthetic-command", **arguments):
        return {
            "client_turn_id": turn,
            "operation": "manage_training_templates",
            "arguments": {"templates": [{"action": "create", "name": "Synthetic"}], **arguments},
        }

    def test_http_route_only_reads_body_and_delegates_with_session(self):
        handler = object.__new__(server.RequestHandler)
        handler.read_json = Mock(return_value=self.payload())
        handler.send_json = Mock()
        service = Mock()
        service.execute.return_value = {"status": "completed"}
        provision = Mock()
        provision.ensure.return_value = "synthetic-conversation"
        routes = server.PlanningCommandsPostRoutes(lambda: service, lambda: provision)
        handled = routes.handle(
            handler, "/api/planning/commands", {"csrf_hash": "synthetic-session"}
        )
        self.assertTrue(handled)
        service.execute.assert_called_once_with(
            self.payload(), conversation_id="synthetic-conversation",
            session_csrf_hash="synthetic-session",
        )
        handler.send_json.assert_called_once_with(200, {"status": "completed"})

    def test_success_replays_without_second_effect_and_binds_session_and_conversation(self):
        service = server.coach_planning_command_service()
        payload = self.payload()
        with patch.object(service._tools, "execute", return_value={"ok": True, "status": "applied"}) as execute:
            first = service.execute(payload, conversation_id="conversation-one", session_csrf_hash="session-one")
            replay = service.execute(payload, conversation_id="conversation-one", session_csrf_hash="session-one")
            self.assertEqual(replay, first)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.kwargs["intent"]["authorization_scope"], ["local_template"])
            with self.assertRaises(server.AppError) as foreign_session:
                service.execute(payload, conversation_id="conversation-one", session_csrf_hash="session-two")
            self.assertEqual(foreign_session.exception.status, 403)
            with self.assertRaises(server.AppError) as foreign_conversation:
                service.execute(payload, conversation_id="conversation-two", session_csrf_hash="session-one")
            self.assertEqual(foreign_conversation.exception.reason, "command_scope_denied")
            altered = self.payload(templates=[{"action": "create", "name": "Different"}])
            with self.assertRaises(server.AppError) as changed:
                service.execute(altered, conversation_id="conversation-one", session_csrf_hash="session-one")
            self.assertEqual(changed.exception.reason, "command_conflict")
            execute.assert_called_once()

    def test_invalid_command_never_claims_turn(self):
        service = server.coach_planning_command_service()
        invalid = (
            None,
            {**self.payload(), "client_turn_id": ""},
            {**self.payload(), "operation": "start_intervals_plan_sync"},
            {**self.payload(), "arguments": []},
            {**self.payload(), "arguments": {"templates": None}},
            {**self.payload(), "operation": "commit_training_plan"},
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(server.AppError):
                service.execute(payload, conversation_id="synthetic-conversation")
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM coach_commands").fetchone()["count"], 0)

    def test_existing_running_claim_does_not_execute_again(self):
        service = server.coach_planning_command_service()
        payload = self.payload(turn="running-command")
        identity = {
            "client_turn_id": payload["client_turn_id"],
            "session_key": coach_session_key("synthetic-session"),
            "effect_key": coach_action_hash({
                "operation": payload["operation"], "arguments": payload["arguments"],
            }),
        }
        with server.database() as db:
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, "
                "target_system, status, receipt, created_at, updated_at) "
                "VALUES ('synthetic-running', ?, 'synthetic-conversation', '{}', "
                "'local', 'running', ?, 'now', 'now')",
                (payload["client_turn_id"], json.dumps(identity)),
            )
        with patch.object(service._tools, "execute") as execute, self.assertRaises(server.AppError) as pending:
            service.execute(
                payload, conversation_id="synthetic-conversation", session_csrf_hash="synthetic-session",
            )
        self.assertEqual(pending.exception.reason, "client_turn_in_progress")
        execute.assert_not_called()

    def test_artifact_revision_is_checked_before_claim(self):
        service = server.coach_planning_command_service()
        revision = self.state()["planning_revision"]
        payload = {
            "client_turn_id": "artifact-command", "operation": "commit_training_plan",
            "arguments": {}, "artifact_id": "synthetic-artifact", "expected_revision": revision + 1,
        }
        with self.assertRaises(server.AppError) as stale:
            service.execute(payload, conversation_id="synthetic-conversation")
        self.assertEqual(stale.exception.reason, "planning_revision_conflict")
        with server.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM coach_commands").fetchone()["count"], 0)

    def test_tool_failure_rolls_back_effect_and_persists_failure_receipt(self):
        service = server.coach_planning_command_service()

        def fail(*_args, **_kwargs):
            with server.database() as db:
                db.execute("INSERT INTO kv(key, value, updated_at) VALUES ('synthetic-command-effect', 'bad', 'now')")
            raise RuntimeError("synthetic tool failure")

        with patch.object(service._tools, "execute", side_effect=fail) as execute:
            receipt = service.execute(
                self.payload(turn="failed-command"),
                conversation_id="synthetic-conversation", session_csrf_hash="synthetic-session",
            )
        execute.assert_called_once()
        self.assertNotEqual(receipt["status"], "completed")
        with server.database() as db:
            self.assertIsNone(db.execute("SELECT value FROM kv WHERE key='synthetic-command-effect'").fetchone())
            row = db.execute("SELECT status, receipt FROM coach_commands WHERE client_turn_id='failed-command'").fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["status"], "running")
