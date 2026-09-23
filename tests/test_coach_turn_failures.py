"""Terminal Coach failures keep confirmed effects and roll back atomically."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.coach.turn_failures import (
    CoachTurnFailureDependencies,
    CoachTurnFailureService,
)
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.errors import AppError
from backend.runtime.events import StateEventBuffer


class CoachTurnFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = DatabaseManager(
            Path(self.temporary.name) / "failure.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
            persist_connections=False,
        )
        self.events = StateEventBuffer()
        self.now = lambda: "2026-09-23T00:00:00Z"
        self.chat = ChatRepository(self.now)
        self.kv = KeyValueRepository(self.now)
        self.redactor = Mock()
        self.redactor.redact_text.return_value = "[REDACTED]"
        self.service = CoachTurnFailureService(
            CoachTurnFailureDependencies(
                database_manager=lambda: self.manager,
                database_lock=threading.RLock(),
                chat_repository=self.chat,
                key_values=self.kv,
                event_buffer=self.events,
                redactor=self.redactor,
                utc_now=self.now,
                repository_root=Path(self.temporary.name),
                read_only_tools=frozenset({"get_activity_details"}),
            )
        )
        with self.manager.unit_of_work() as db:
            db.execute("CREATE TABLE coach_commands (client_turn_id TEXT PRIMARY KEY, receipt TEXT, status TEXT, updated_at TEXT)")
            db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, client_turn_id TEXT, created_at TEXT)")
            db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")

    def _seed(self, receipt: dict, *, status: str = "running") -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands VALUES (?, ?, ?, ?)",
                ("turn-1", json.dumps(receipt), status, self.now()),
            )

    def _stored(self) -> tuple[str, dict]:
        with self.manager.reader() as db:
            row = db.execute("SELECT status, receipt FROM coach_commands WHERE client_turn_id='turn-1'").fetchone()
        return row["status"], json.loads(row["receipt"])

    def test_partial_failure_commits_pending_request_and_discards_provider_checkpoint(self) -> None:
        with self.manager.unit_of_work() as db:
            user = self.chat.add(db, "user", "Plan bitte lokal", client_turn_id="turn-1")
        self._seed({
            "user_message_id": user["id"],
            "command_receipts": [{"tool": "save_checkin", "result": {"ok": True, "status": "saved"}}],
            "pending_tool_calls": [{"tool": "apply_workout_library_plan"}],
            "response_input": [{"image": "secret-image"}],
            "openai_response_id": "provider-response",
        })

        result = self.service.persist(
            "turn-1",
            {"operation": "save_checkin", "follow_up_operations": ["apply_workout_library_plan"]},
            AppError(429, "sensitive provider text", reason="rate_limit_exceeded"),
        )

        status, stored = self._stored()
        self.assertEqual((status, result["status"]), ("completed", "partial"))
        self.assertEqual(stored["pending_operations"], ["apply_workout_library_plan"])
        self.assertNotIn("response_input", stored)
        self.assertNotIn("pending_tool_calls", stored)
        self.assertNotIn("openai_response_id", stored)
        self.assertEqual(stored["error"], "[REDACTED]")
        self.assertIn("Bereits erfolgreich", stored["message"]["content"])
        with self.manager.reader() as db:
            pending = json.loads(self.kv.get(db, "coach_pending_request"))
            assistants = db.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0]
        self.assertEqual(pending["completed_steps"], [{"tool": "save_checkin", "status": "saved"}])
        self.assertEqual(assistants, 1)
        self.assertEqual(len(self.events.since()["events"]), 1)

    def test_cancellation_clears_pending_and_completed_replay_does_not_duplicate(self) -> None:
        self._seed({"command_receipts": []})
        with self.manager.unit_of_work() as db:
            self.kv.set(db, "coach_pending_request", "queued")
        first = self.service.persist("turn-1", {}, AppError(499, "stopped", reason="chat_cancelled"))
        second = self.service.persist("turn-1", {}, AppError(499, "stopped", reason="chat_cancelled"))
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "cancelled")
        with self.manager.reader() as db:
            self.assertEqual(self.kv.get(db, "coach_pending_request"), "null")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0], 1)
        self.assertEqual(len(self.events.since()["events"]), 1)

    def test_message_insert_failure_rolls_back_pending_request_and_receipt(self) -> None:
        with self.manager.unit_of_work() as db:
            user = self.chat.add(db, "user", "Plan bitte lokal", client_turn_id="turn-1")
        self._seed({"user_message_id": user["id"], "command_receipts": []})
        self.service._deps.chat_repository.add = Mock(side_effect=RuntimeError("synthetic write failure"))

        with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
            self.service.persist("turn-1", {}, AppError(503, "failed"))

        status, _ = self._stored()
        self.assertEqual(status, "running")
        with self.manager.reader() as db:
            self.assertIsNone(self.kv.get(db, "coach_pending_request"))
        self.assertEqual(self.events.since()["events"], [])


if __name__ == "__main__":
    unittest.main()
