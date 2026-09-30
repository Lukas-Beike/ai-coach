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

    def test_unconfigured_ai_provider_explanation(self) -> None:
        for reason, expected in (
            ("ai_provider_not_configured", "Kein KI-Dienst konfiguriert"),
            ("openai_not_configured", "OpenAI ist nicht konfiguriert"),
            ("gemini_not_configured", "Gemini ist nicht konfiguriert"),
        ):
            status, text, _, _ = self.service._base_response(
                AppError(503, "not configured", reason=reason), []
            )
            self.assertEqual(status, "failed")
            self.assertIn(expected, text)

    def test_provider_failure_explanations_are_actionable_and_safe(self) -> None:
        cases = (
            ("provider_timeout", "nicht rechtzeitig geantwortet"),
            ("not_found", "Modellkonfiguration prüfen"),
            ("authentication_or_permission", "API-Zugang"),
            ("rate_limit_exceeded", "Anfragelimit erreicht"),
            ("provider_unavailable", "vorübergehend nicht verfügbar"),
            ("conversation_locked", "warte kurz"),
            ("conversation_state_invalid", "dein lokaler Chat bleibt erhalten"),
            ("insufficient_quota", "Guthaben und Abrechnung"),
            ("organization_spend_limit_exceeded", "Limit im OpenAI-Konto prüfen"),
            ("project_spend_limit_exceeded", "Limit im OpenAI-Konto prüfen"),
            ("organization_usage_limit_exceeded", "Limit im OpenAI-Konto prüfen"),
        )
        for reason, expected in cases:
            with self.subTest(reason=reason):
                status, text, _, _ = self.service._base_response(
                    AppError(502, "private provider text", reason=reason), []
                )
                self.assertEqual(status, "failed")
                self.assertIn(expected, text)
                self.assertNotIn("private provider text", text)

    def test_provider_timeout_is_a_persisted_actionable_chat_message(self) -> None:
        self._assert_persisted_failure(
            "provider_timeout",
            "Der KI-Dienst hat nicht rechtzeitig geantwortet. Bitte versuche es erneut.",
        )

    def test_model_not_found_is_a_persisted_actionable_chat_message(self) -> None:
        self._assert_persisted_failure(
            "not_found",
            "Das konfigurierte KI-Modell oder der angeforderte Dienst wurde nicht gefunden. Bitte die Modellkonfiguration prüfen.",
        )

    def test_openai_billing_failure_is_a_persisted_actionable_chat_message(self) -> None:
        self._assert_persisted_failure(
            "credit_balance_exhausted",
            "Das OpenAI-Guthaben ist aufgebraucht. Bitte im OpenAI-Billing Guthaben hinzufügen.",
        )

    def _assert_persisted_failure(self, reason: str, expected: str) -> None:
        self._seed({"command_receipts": []})
        result = self.service.persist(
            "turn-1", {}, AppError(502, "sensitive provider text", reason=reason)
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"]["content"], expected)
        status, stored = self._stored()
        self.assertEqual(status, "completed")
        self.assertEqual(stored["message"]["content"], expected)
        self.assertNotIn("sensitive provider text", json.dumps(stored))
        with self.manager.reader() as db:
            message = db.execute("SELECT content FROM messages WHERE role='assistant'").fetchone()
        self.assertEqual(message["content"], expected)


if __name__ == "__main__":
    unittest.main()
