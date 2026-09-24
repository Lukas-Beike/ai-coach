"""Direct contracts for atomic final Coach receipts."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock

from backend.coach.final_receipt import CoachFinalReceiptService
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.runtime.events import StateEventBuffer


class CoachFinalReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trace: list[str] = []
        self.manager = MagicMock()
        self.db = Mock()
        self.manager.unit_of_work.return_value.__enter__.return_value = self.db
        self.manager.unit_of_work.return_value.__exit__.side_effect = self._close_unit_of_work
        self.chat = Mock()
        self.chat.add.side_effect = self._add_message
        self.keys = Mock()
        self.events = Mock()
        self.events.publish.side_effect = lambda *_: self.trace.append("publish")
        self.service = CoachFinalReceiptService(
            self.manager, threading.RLock(), self.chat, self.keys,
            self.events, lambda: "2026-09-24T00:00:00Z",
        )

    def _close_unit_of_work(self, error_type, _error, _traceback):
        self.trace.append("rollback" if error_type else "commit")
        return False

    def _add_message(self, _db, _role, _text, *, client_turn_id):
        self.trace.append("message")
        return {"id": "assistant-1", "client_turn_id": client_turn_id}

    def test_build_projects_outcome_and_removes_all_replay_checkpoints(self) -> None:
        steps = [{"tool": "preview_adaptive_replan", "result": {"proposed_action": {"id": "p1"}}}]
        receipt = {
            "openai_response_id": "old", "pending_tool_outputs": [1],
            "pending_tool_calls": [2], "response_input": [3],
            "previous_response_id": "earlier", "session_key": "owner",
        }
        final = self.service.build(
            receipt, status="awaiting_clarification", response={"status": "incomplete"},
            client_turn_id="turn-1", command_receipts=steps, sync_job_ids=["sync-1"],
            intent={"allow_mutations": False}, rounds=2,
            failures=[{"tool": "z"}, {"tool": "a"}, {"tool": "z"}],
            awaiting_clarification=True,
        )
        self.assertEqual(final["pending_operations"], ["a", "z"])
        self.assertEqual(final["proposed_actions"], [{"id": "p1"}])
        self.assertEqual(final["response_status"], "incomplete")
        self.assertEqual(final["session_key"], "owner")
        self.assertEqual(final["tool_rounds"], 2)
        for key in ("openai_response_id", "pending_tool_outputs", "pending_tool_calls", "response_input", "previous_response_id"):
            self.assertNotIn(key, final)
            self.assertIn(key, receipt)

    def test_completed_command_returns_stored_receipt_without_duplicate_effect(self) -> None:
        self.db.execute.return_value.fetchone.return_value = {
            "status": "completed", "receipt": json.dumps({"status": "completed", "message": {"id": "old"}}),
        }
        result = self.service.persist(
            {"text": "new"}, client_turn_id="turn-1", command_receipts=[], ai_provider="openai",
        )
        self.assertEqual(result["message"]["id"], "old")
        self.chat.add.assert_not_called()
        self.keys.set.assert_not_called()
        self.events.publish.assert_not_called()
        self.assertEqual(self.trace, ["commit"])

    def test_persist_commits_message_preview_provider_and_receipt_before_event(self) -> None:
        def execute(sql, _values):
            if sql.startswith("SELECT status, receipt"):
                return Mock(fetchone=lambda: {"status": "running"})
            if sql.startswith("SELECT payload FROM plan_adjustments"):
                return Mock(fetchone=lambda: {"payload": '{"preview":true}'})
            return Mock()

        self.db.execute.side_effect = execute
        steps = [{"tool": "preview_adaptive_replan", "result": {"ok": True, "id": "preview-1"}}]
        final = {"status": "completed", "text": "Fertig", "command_receipts": steps}
        result = self.service.persist(
            final, client_turn_id="turn-1", command_receipts=steps, ai_provider="openai",
        )
        self.assertEqual(self.trace, ["message", "commit", "publish"])
        self.assertNotIn("text", result)
        self.chat.add.assert_called_once_with(self.db, "assistant", "Fertig", client_turn_id="turn-1")
        self.keys.set.assert_called_once_with(self.db, "last_coach_ai_provider", "openai")
        calls = self.db.execute.call_args_list
        preview = next(call for call in calls if call.args[0].startswith("UPDATE plan_adjustments"))
        self.assertEqual(json.loads(preview.args[1][0])["published_message_id"], "assistant-1")
        update = next(call for call in calls if call.args[0].startswith("UPDATE coach_commands"))
        self.assertEqual(update.args[1][1], "2026-09-24T00:00:00Z")
        self.assertNotIn("text", json.loads(update.args[1][0]))
        self.events.publish.assert_called_once_with(
            "coach", {"message_id": "assistant-1", "role": "assistant", "client_turn_id": "turn-1"},
        )

    def test_failed_command_update_rolls_back_without_event(self) -> None:
        def execute(sql, _values):
            if sql.startswith("SELECT status, receipt"):
                return Mock(fetchone=lambda: {"status": "running"})
            if sql.startswith("UPDATE coach_commands"):
                raise ValueError("synthetic update failure")
            return Mock()

        self.db.execute.side_effect = execute
        with self.assertRaisesRegex(ValueError, "synthetic update failure"):
            self.service.persist(
                {"text": "Fertig"}, client_turn_id="turn-1",
                command_receipts=[], ai_provider="openai",
            )
        self.assertEqual(self.trace, ["message", "rollback"])
        self.events.publish.assert_not_called()

    def test_real_sqlite_unit_of_work_rolls_back_message_when_provider_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = DatabaseManager(
                Path(temporary) / "coach.sqlite3", sqlite3,
                row_factory=sqlite3.Row, persist_connections=False,
            )
            with manager.unit_of_work() as db:
                db.execute("CREATE TABLE coach_commands (client_turn_id TEXT PRIMARY KEY, status TEXT, receipt TEXT, updated_at TEXT)")
                db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, client_turn_id TEXT, created_at TEXT)")
                db.execute("INSERT INTO coach_commands VALUES ('turn-1', 'running', '{}', '')")
            keys = Mock(spec=KeyValueRepository)
            keys.set.side_effect = ValueError("synthetic KV failure")
            events = StateEventBuffer()
            service = CoachFinalReceiptService(
                manager, threading.RLock(), ChatRepository(lambda: "now"), keys,
                events, lambda: "now",
            )
            with self.assertRaisesRegex(ValueError, "synthetic KV failure"):
                service.persist(
                    {"text": "Fertig"}, client_turn_id="turn-1",
                    command_receipts=[], ai_provider="openai",
                )
            with manager.unit_of_work() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT status FROM coach_commands").fetchone()[0], "running")
            self.assertEqual(events.since()["events"], [])
            manager.close()


if __name__ == "__main__":
    unittest.main()
