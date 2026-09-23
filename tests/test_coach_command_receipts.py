"""Focused tests for the session-bound command receipt projection."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from backend.coach.authorization import coach_session_key
from backend.coach.receipt_reads import CoachCommandReceiptService
from backend.db.manager import DatabaseManager
from backend.errors import AppError


class CoachCommandReceiptServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.directory.name) / "receipts.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
            persist_connections=False,
        )
        with self.manager.unit_of_work() as db:
            db.executescript(
                """
                CREATE TABLE coach_commands (
                    client_turn_id TEXT PRIMARY KEY, receipt TEXT
                );
                CREATE TABLE coach_action_proposals (
                    id TEXT PRIMARY KEY, session_csrf_hash TEXT NOT NULL,
                    action_type TEXT NOT NULL, target_system TEXT NOT NULL,
                    object_ids TEXT NOT NULL, diff TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                    status TEXT NOT NULL
                );
                """
            )
        self.session = "session-a"
        self.service = CoachCommandReceiptService(
            lambda: self.manager,
            threading.RLock(),
            now=lambda: 100,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.directory.cleanup()

    def _proposal(self, proposal_id: str, session: str, status: str, expires: float) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_action_proposals "
                "(id, session_csrf_hash, action_type, target_system, object_ids, "
                "diff, payload_hash, expires_at, status) "
                "VALUES (?, ?, 'undo_change', 'local', '{}', '{}', 'hash', ?, ?)",
                (proposal_id, session, expires, status),
            )

    def _receipt(self, turn_id: str, receipt: dict) -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands (client_turn_id, receipt) VALUES (?, ?)",
                (turn_id, json.dumps(receipt)),
            )

    def test_read_validates_identifier_and_missing_command(self) -> None:
        for invalid in (None, "  ", "x" * 121):
            with self.subTest(invalid=invalid), self.assertRaises(AppError) as caught:
                self.service.read(invalid, self.session)
            self.assertEqual((400, "invalid_client_turn"), (caught.exception.status, caught.exception.reason))

        with self.assertRaises(AppError) as caught:
            self.service.read("missing", self.session)
        self.assertEqual((404, "command_not_found"), (caught.exception.status, caught.exception.reason))

    def test_read_projects_owned_proposals_and_redacts_session_key(self) -> None:
        self._proposal("expired", self.session, "preview", 99)
        self._proposal("consumed", self.session, "consumed", 99)
        self._proposal("foreign", "session-b", "preview", 200)
        self._receipt(
            "turn-a",
            {
                "session_key": coach_session_key(self.session),
                "status": "completed",
                "proposed_actions": [
                    {"id": "expired"},
                    {"id": "consumed"},
                    {"id": "foreign"},
                ],
            },
        )

        result = self.service.read(" turn-a ", self.session)

        self.assertEqual("turn-a", result["client_turn_id"])
        self.assertNotIn("session_key", result)
        self.assertEqual(
            [("expired", "expired"), ("consumed", "consumed")],
            [(item["id"], item["status"]) for item in result["proposed_actions"]],
        )

    def test_read_rejects_another_session(self) -> None:
        self._receipt("turn-b", {"session_key": coach_session_key("session-b")})

        with self.assertRaises(AppError) as caught:
            self.service.read("turn-b", self.session)

        self.assertEqual((403, "command_scope_denied"), (caught.exception.status, caught.exception.reason))

    def test_read_uses_manager_transactions_compatible_with_restore_drain(self) -> None:
        self._receipt(
            "turn-c",
            {"session_key": coach_session_key(self.session), "status": "completed"},
        )

        with self.manager.restore_drain():
            pass

        self.assertEqual("completed", self.service.read("turn-c", self.session)["status"])


if __name__ == "__main__":
    unittest.main()
