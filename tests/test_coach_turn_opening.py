from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from backend.coach.authorization import coach_session_key
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.coach.turn_opening import CoachTurnOpeningService
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository
from backend.errors import AppError


class CoachTurnOpeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="coach-turn-opening-")
        self.db_path = Path(self.temp_dir.name) / "coach.sqlite3"
        db = sqlite3.connect(self.db_path)
        try:
            db.executescript(
                """
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    client_turn_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE coach_commands (
                    id TEXT PRIMARY KEY,
                    client_turn_id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    target_system TEXT NOT NULL,
                    status TEXT NOT NULL,
                    receipt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        finally:
            db.close()
        self.manager = DatabaseManager(
            self.db_path,
            sqlite3,
            row_factory=sqlite3.Row,
            persist_connections=False,
        )
        import threading

        self.lock = threading.RLock()
        self.receipt_service = CoachCommandReceiptService(
            lambda: self.manager, self.lock
        )
        self.clock_values = iter(("command-created", "command-updated"))
        self.service = CoachTurnOpeningService(
            self.manager,
            self.lock,
            ChatRepository(lambda: "message-created"),
            self.receipt_service,
            lambda: next(self.clock_values),
            lambda: SimpleNamespace(hex="fixed-command-id"),
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def _open(self, **overrides):
        args = {
            "message": "  Plan a relaxed ride  ",
            "intent": {"allow_mutations": True, "summary": "easy ride"},
            "conversation_id": "conversation-1",
            "client_turn_id": "turn-1",
            "session_csrf_hash": "synthetic-csrf-secret",
            "ai_provider": "openai",
            "model": "gpt-test",
        }
        args.update(overrides)
        message = args.pop("message")
        return self.service.open(message, **args)

    def test_new_turn_atomically_inserts_message_and_session_bound_receipt(self) -> None:
        receipt = self._open()

        self.assertEqual(receipt, {
            "client_turn_id": "turn-1",
            "session_key": coach_session_key("synthetic-csrf-secret"),
            "user_message_id": 1,
            "status": "running",
            "command_receipts": [],
            "ai_provider": "openai",
            "model": "gpt-test",
        })
        self.assertNotIn("synthetic-csrf-secret", json.dumps(receipt))
        with self.manager.reader() as db:
            message = db.execute("SELECT * FROM messages").fetchone()
            command = db.execute("SELECT * FROM coach_commands").fetchone()
        self.assertEqual((message["role"], message["content"], message["client_turn_id"], message["created_at"]),
                         ("user", "Plan a relaxed ride", "turn-1", "message-created"))
        self.assertEqual(command["id"], "fixed-command-id")
        self.assertEqual(command["conversation_id"], "conversation-1")
        self.assertEqual(json.loads(command["intent"]), {"allow_mutations": True, "summary": "easy ride"})
        self.assertEqual((command["target_system"], command["status"]), ("none", "running"))
        self.assertEqual(json.loads(command["receipt"]), receipt)
        self.assertEqual((command["created_at"], command["updated_at"]),
                         ("command-created", "command-updated"))

    def test_existing_turn_checks_owner_and_returns_receipt_without_duplicate_message(self) -> None:
        prior_receipt = {
            "client_turn_id": "turn-1",
            "session_key": coach_session_key("synthetic-csrf-secret"),
            "user_message_id": 42,
            "status": "completed",
            "command_receipts": [{"name": "get_plan"}],
        }
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("existing-id", "turn-1", "conversation-1", "{}", "none", "completed",
                 json.dumps(prior_receipt), "created", "updated"),
            )
        require_owner = Mock(wraps=self.receipt_service.require_owner)
        self.service._receipt_service.require_owner = require_owner

        result = self._open()

        self.assertEqual(result, prior_receipt)
        require_owner.assert_called_once_with(prior_receipt, "synthetic-csrf-secret")
        with self.manager.reader() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coach_commands").fetchone()[0], 1)

    def test_foreign_session_is_rejected_without_writes(self) -> None:
        foreign_receipt = {"session_key": coach_session_key("another-session")}
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("existing-id", "turn-1", "conversation-1", "{}", "none", "running",
                 json.dumps(foreign_receipt), "created", "updated"),
            )

        with self.assertRaises(AppError) as raised:
            self._open()

        self.assertEqual((raised.exception.status, raised.exception.reason),
                         (403, "command_scope_denied"))
        with self.manager.reader() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coach_commands").fetchone()[0], 1)

    def test_receipt_insert_failure_rolls_back_user_message(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER reject_command BEFORE INSERT ON coach_commands "
                "BEGIN SELECT RAISE(ABORT, 'synthetic insert failure'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self._open()

        with self.manager.reader() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coach_commands").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
