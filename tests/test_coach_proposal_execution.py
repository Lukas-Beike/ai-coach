"""Confirmed Coach actions consume session-bound tokens before side effects."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from backend.coach.proposals import CoachProposalExecutionService, coach_action_hash
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class CoachProposalExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = DatabaseManager(
            Path(temporary.name) / "proposals.sqlite", sqlite3, row_factory=row_factory,
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.duplicate_service = Mock()
        self.duplicate_service.delete.return_value = {"status": "deleted"}
        self.undo_service = Mock()
        self.undo_service.apply.return_value = {"status": "undone"}
        self.client = Mock()
        self.client_factory = Mock(return_value=self.client)
        self.service = CoachProposalExecutionService(
            self.manager,
            self.duplicate_service,
            self.undo_service,
            self.client_factory,
            MaintenanceGate(),
            now=lambda: 100.0,
            utc_now=lambda: "2026-09-23T10:00:00+00:00",
        )

    def add_ready(self, *, action_type: str = "undo_change", expires_at: float = 200.0) -> tuple[str, str]:
        token = "synthetic-token-" + "x" * 32
        payload = {"change_id": "synthetic-change"}
        payload_hash = coach_action_hash(payload)
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_action_proposals "
                "(id, session_csrf_hash, action_type, target_system, object_ids, diff, payload, "
                "payload_hash, status, expires_at, created_at, action_token_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)",
                (
                    "synthetic-proposal", "owner-session", action_type,
                    "intervals" if action_type == "delete_duplicate_intervals_activity" else "local",
                    "[]", "[]", json.dumps(payload), payload_hash, expires_at,
                    "2026-09-23T09:00:00+00:00",
                    hashlib.sha256(token.encode("utf-8")).hexdigest(),
                ),
            )
        return token, payload_hash

    def row(self) -> dict:
        with self.manager.reader() as db:
            return db.execute("SELECT * FROM coach_action_proposals").fetchone()

    def test_valid_undo_consumes_token_and_replay_is_rejected(self) -> None:
        token, payload_hash = self.add_ready()
        self.assertEqual(
            self.service.execute(token, "owner-session", payload_hash),
            {"status": "undone"},
        )
        self.assertEqual(self.row()["status"], "used")
        self.assertEqual(self.row()["used_at"], "2026-09-23T10:00:00+00:00")
        self.undo_service.apply.assert_called_once_with({"change_id": "synthetic-change"})
        with self.assertRaises(AppError) as error:
            self.service.execute(token, "owner-session", payload_hash)
        self.assertEqual(error.exception.status, 409)
        self.undo_service.apply.assert_called_once()

    def test_foreign_session_wrong_hash_and_expiry_cannot_consume_or_dispatch(self) -> None:
        token, payload_hash = self.add_ready()
        for session, expected_hash in (("foreign-session", payload_hash), ("owner-session", "0" * 64)):
            with self.assertRaises(AppError):
                self.service.execute(token, session, expected_hash)
        self.assertEqual(self.row()["status"], "ready")
        self.undo_service.apply.assert_not_called()
        self.client_factory.assert_not_called()

    def test_expired_token_never_dispatches(self) -> None:
        token, payload_hash = self.add_ready(expires_at=100.0)
        with self.assertRaises(AppError) as error:
            self.service.execute(token, "owner-session", payload_hash)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.row()["status"], "ready")
        self.undo_service.apply.assert_not_called()

    def test_competing_execution_dispatches_only_once(self) -> None:
        token, payload_hash = self.add_ready(action_type="delete_duplicate_intervals_activity")

        def attempt() -> str:
            try:
                self.service.execute(token, "owner-session", payload_hash)
                return "applied"
            except AppError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(outcomes, ["applied", "rejected"])
        self.duplicate_service.delete.assert_called_once_with(
            {"change_id": "synthetic-change"}, self.client,
        )
        self.client_factory.assert_called_once_with()
        self.undo_service.apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
