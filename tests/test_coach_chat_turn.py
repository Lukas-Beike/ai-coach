"""Direct session, replay, and provider contracts for Coach chat turns."""

from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import MagicMock, Mock

from backend.coach.chat_turn import CoachChatTurnService
from backend.coach.conversation_gate import CoachConversationGate
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class CoachChatTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Mock()
        self.db.execute.return_value.fetchone.return_value = None
        self.manager = Mock()
        self.manager.unit_of_work.return_value = MagicMock()
        self.manager.unit_of_work.return_value.__enter__.return_value = self.db
        self.receipts = Mock()
        self.settings = Mock()
        self.settings.selected_ai_provider.return_value = "openai"
        self.settings.selected_model.return_value = "synthetic-model"
        self.settings.selected_thinking_level.return_value = "medium"
        self.conversations = Mock()
        self.conversations.ensure.return_value = "synthetic-conversation"
        self.conversations_factory = Mock(return_value=self.conversations)
        self.structured = Mock()
        self.structured.run.return_value = {"status": "completed"}
        self.structured_factory = Mock(return_value=self.structured)
        self.service = CoachChatTurnService(
            lambda: self.manager, MagicMock(), self.receipts, self.settings,
            self.conversations_factory, self.structured_factory, lambda: "synthetic-time",
            CoachConversationGate(), MaintenanceGate(),
        )

    def test_new_turn_validates_and_forwards_exact_session_and_provider(self) -> None:
        result = self.service.run(
            "  synthetic request  ", client_turn_id="  turn-one  ",
            session_csrf_hash="synthetic-session", allow_mutations=False,
        )

        self.assertEqual(result, {"status": "completed"})
        self.assertEqual(self.structured.run.call_args.args, ("synthetic request",))
        self.assertEqual(self.structured.run.call_args.kwargs["client_turn_id"], "turn-one")
        self.assertEqual(self.structured.run.call_args.kwargs["session_csrf_hash"], "synthetic-session")
        self.assertEqual(self.structured.run.call_args.kwargs["intent"], {"allow_mutations": False})
        self.assertEqual(self.structured.run.call_args.kwargs["ai_provider"], "openai")

    def test_invalid_or_cancelled_request_never_reads_or_mutates_state(self) -> None:
        event = threading.Event()
        event.set()
        with self.assertRaises(AppError):
            self.service.run("synthetic", client_turn_id="turn", cancel_event=event)
        with self.assertRaises(AppError):
            self.service.run("   ", client_turn_id="turn")
        with self.assertRaises(AppError):
            self.service.run("synthetic", client_turn_id=" " * 3)
        self.manager.unit_of_work.assert_not_called()
        self.conversations_factory.assert_not_called()
        self.structured_factory.assert_not_called()
        self.structured.run.assert_not_called()

    def test_completed_turn_is_read_idempotently_without_second_execution(self) -> None:
        self.db.execute.return_value.fetchone.return_value = {
            "status": "completed", "receipt": json.dumps({"status": "completed"}),
        }
        self.receipts.read.return_value = {"status": "completed", "operation_id": "synthetic-operation"}

        result = self.service.run("synthetic", client_turn_id="turn", session_csrf_hash="owner")

        self.assertEqual(result["operation_id"], "synthetic-operation")
        self.receipts.require_owner.assert_called_once()
        self.receipts.read.assert_called_once_with("turn", "owner")
        self.conversations_factory.assert_not_called()
        self.structured_factory.assert_not_called()
        self.structured.run.assert_not_called()

    def test_foreign_turn_is_denied_before_resume_or_provider_access(self) -> None:
        self.db.execute.return_value.fetchone.return_value = {
            "status": "running", "receipt": json.dumps({"mode": "background"}),
        }
        self.receipts.require_owner.side_effect = AppError(403, "synthetic denial", reason="command_scope_denied")

        with self.assertRaises(AppError) as caught:
            self.service.run("synthetic", client_turn_id="turn", session_csrf_hash="intruder", background_job=True)

        self.assertEqual(caught.exception.status, 403)
        self.conversations_factory.assert_not_called()
        self.structured_factory.assert_not_called()
        self.conversations.ensure.assert_not_called()
        self.structured.run.assert_not_called()

    def test_background_resume_preserves_persisted_provider_and_conversation(self) -> None:
        self.db.execute.return_value.fetchone.return_value = {
            "status": "running", "receipt": json.dumps({
                "mode": "background", "ai_provider": "gemini", "model": "synthetic-gemini",
                "thinking_level": "high",
            }), "conversation_id": "persisted-conversation",
        }

        result = self.service.run(
            "synthetic", client_turn_id="turn", session_csrf_hash="owner", background_job=True,
        )

        self.assertEqual(result, {"status": "completed"})
        self.assertEqual(self.structured.run.call_args.kwargs["ai_provider"], "gemini")
        self.assertEqual(self.structured.run.call_args.kwargs["model"], "synthetic-gemini")
        self.assertEqual(self.structured.run.call_args.kwargs["thinking_level"], "high")
        self.assertEqual(self.structured.run.call_args.kwargs["conversation_id"], "persisted-conversation")
        self.conversations.ensure.assert_not_called()
        self.conversations_factory.assert_not_called()
        self.assertTrue(any(
            "UPDATE coach_commands SET conversation_id" in call.args[0]
            for call in self.db.execute.call_args_list
        ))

    def test_stale_synchronous_turn_is_released_before_idempotent_read(self) -> None:
        row = {"status": "running", "updated_at": "synthetic-old-time", "receipt": json.dumps({"status": "running"})}
        self.db.execute.side_effect = [
            Mock(fetchone=Mock(return_value=row)),
            Mock(fetchone=Mock(return_value={"age": 901})),
            Mock(),
        ]
        self.receipts.read.return_value = {"status": "failed", "error": "synthetic-safe"}

        result = self.service.run("synthetic", client_turn_id="turn", session_csrf_hash="owner")

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(
            "UPDATE coach_commands SET status='completed'" in call.args[0]
            for call in self.db.execute.call_args_list
        ))
        self.structured.run.assert_not_called()
        self.conversations_factory.assert_not_called()
        self.structured_factory.assert_not_called()

    def test_recent_synchronous_turn_remains_in_progress(self) -> None:
        row = {"status": "running", "updated_at": "synthetic-recent-time", "receipt": json.dumps({"status": "running"})}
        self.db.execute.side_effect = [
            Mock(fetchone=Mock(return_value=row)),
            Mock(fetchone=Mock(return_value={"age": 899})),
        ]

        with self.assertRaises(AppError) as caught:
            self.service.run("synthetic", client_turn_id="turn", session_csrf_hash="owner")

        self.assertEqual(caught.exception.reason, "client_turn_in_progress")
        self.assertEqual(len(self.db.execute.call_args_list), 2)
        self.structured.run.assert_not_called()
        self.conversations_factory.assert_not_called()
        self.structured_factory.assert_not_called()

    def test_maintenance_blocks_before_database_or_conversation_slot(self) -> None:
        with self.service._maintenance_gate.restore(), self.assertRaises(AppError) as caught:
            self.service.run("synthetic", client_turn_id="turn", session_csrf_hash="owner")

        self.assertEqual(caught.exception.reason, "maintenance")
        self.manager.unit_of_work.assert_not_called()
        with self.service._conversation_gate.operation():
            pass

    def test_full_conversation_queue_releases_outer_maintenance_operation(self) -> None:
        gate = CoachConversationGate(queue_limit=1)
        self.service._conversation_gate = gate
        self.assertTrue(gate._queue.acquire(blocking=False))
        try:
            with self.assertRaises(AppError) as caught:
                self.service.run("synthetic", client_turn_id="turn", session_csrf_hash="owner")
        finally:
            gate._queue.release()

        self.assertEqual(caught.exception.reason, "chat_queue_full")
        self.assertEqual(self.service._maintenance_gate.state()["running_operations"], 0)
        self.manager.unit_of_work.assert_not_called()


if __name__ == "__main__":
    unittest.main()
