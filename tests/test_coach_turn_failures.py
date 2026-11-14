"""Terminal Coach failures keep confirmed effects and roll back atomically."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from support import temp_database

from backend.coach.turn_failures import (
    CoachTurnFailureDependencies,
    CoachTurnFailureService,
)
from backend.coach.turn_undo import CoachTurnUndoService
from backend.db import row_factory as production_row_factory
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.errors import AppError, DatabaseBusyError
from backend.providers.state import metered_turn
from backend.runtime.events import StateEventBuffer


class CoachTurnFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = temp_database(
            self,
            path=Path(self.temporary.name) / "failure.sqlite",
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
            db.execute(
                "CREATE TABLE coach_commands (client_turn_id TEXT PRIMARY KEY, receipt TEXT, status TEXT, updated_at TEXT)"
            )
            db.execute(
                "CREATE TABLE messages (attachments TEXT NOT NULL DEFAULT '[]', id INTEGER PRIMARY KEY, role TEXT, content TEXT, client_turn_id TEXT, created_at TEXT)"
            )
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )

    def _seed(self, receipt: dict, *, status: str = "running") -> None:
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands VALUES (?, ?, ?, ?)",
                ("turn-1", json.dumps(receipt), status, self.now()),
            )

    def _stored(self) -> tuple[str, dict]:
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id='turn-1'"
            ).fetchone()
        return row["status"], json.loads(row["receipt"])

    def test_partial_failure_commits_pending_request_and_discards_open_tool_calls(
        self,
    ) -> None:
        with self.manager.unit_of_work() as db:
            user = self.chat.add(
                db, "user", "Plan bitte lokal", client_turn_id="turn-1"
            )
        self._seed(
            {
                "user_message_id": user["id"],
                "command_receipts": [
                    {"tool": "save_checkin", "result": {"ok": True, "status": "saved"}}
                ],
                "pending_tool_calls": [{"tool": "apply_workout_library_plan"}],
                "openai_reached": True,
            }
        )

        result = self.service.persist(
            "turn-1",
            {
                "operation": "save_checkin",
                "follow_up_operations": ["apply_workout_library_plan"],
            },
            AppError(429, "sensitive provider text", reason="rate_limit_exceeded"),
        )

        status, stored = self._stored()
        self.assertEqual((status, result["status"]), ("completed", "partial"))
        self.assertEqual(stored["pending_operations"], ["apply_workout_library_plan"])
        self.assertNotIn("pending_tool_calls", stored)
        # A failed turn is no attachment anchor.
        self.assertNotIn("openai_reached", stored)
        self.assertEqual(stored["error"], "[REDACTED]")
        self.assertIn("Bereits erfolgreich", stored["message"]["content"])
        with self.manager.reader() as db:
            pending = json.loads(self.kv.get(db, "coach_pending_request"))
            assistants = db.execute(
                "SELECT COUNT(*) FROM messages WHERE role='assistant'"
            ).fetchone()[0]
        self.assertEqual(
            pending["completed_steps"], [{"tool": "save_checkin", "status": "saved"}]
        )
        self.assertEqual(assistants, 1)
        self.assertEqual(len(self.events.since()["events"]), 1)

    def test_applied_tracked_write_stays_undoable_after_a_failed_follow_up(
        self,
    ) -> None:
        with self.manager.unit_of_work() as db:
            user = self.chat.add(
                db, "user", "Passe mein Profil an", client_turn_id="turn-1"
            )
        change = {
            "id": "change-1",
            "entity_type": "profile",
            "action": "update",
            "after_hash": "hash-1",
        }
        self._seed(
            {
                "user_message_id": user["id"],
                "command_receipts": [
                    {
                        "tool": "update_profile",
                        "result": {"ok": True, "status": "saved"},
                        "changes": [change],
                    }
                ],
            }
        )

        result = self.service.persist(
            "turn-1",
            {"operation": "update_profile"},
            AppError(503, "failed", reason="provider_unavailable"),
        )

        _, stored = self._stored()
        summary = stored["change_summary"]
        self.assertEqual(summary["undoable"], True)
        self.assertEqual(result["message"]["coach_changes"], summary)
        # The chat reader projects dict rows, as the production database does.
        reader = temp_database(
            self,
            path=Path(self.temporary.name) / "failure.sqlite",
            row_factory=production_row_factory,
            persist_connections=False,
        )
        with reader.reader() as db:
            reloaded = [m for m in self.chat.list(db) if m["role"] == "assistant"]
        self.assertEqual(reloaded[0]["coach_changes"], summary)

        history = Mock()
        history.profile_mutation_coordinator = threading.RLock()
        undo = CoachTurnUndoService(
            lambda: self.manager, threading.RLock(), lambda: history, now=self.now
        )
        self.assertEqual(undo.undo("turn-1")["status"], "undone")
        history.apply_many.assert_called_once()
        self.assertEqual(self._stored()[1]["change_summary"]["undone_at"], self.now())

    def test_failure_receipt_drops_bulky_tool_results_and_keeps_ids_and_changes(
        self,
    ) -> None:
        with self.manager.unit_of_work() as db:
            user = self.chat.add(db, "user", "Lies den Plan", client_turn_id="turn-1")
        self._seed(
            {
                "user_message_id": user["id"],
                "command_receipts": [
                    {
                        "tool": "update_profile",
                        "result": {
                            "ok": True,
                            "status": "saved",
                            "artifact_id": "art-1",
                            "profile": {"notes": "synthetic bulk " * 1000},
                        },
                        "changes": [{"id": "change-1"}],
                    }
                ],
            }
        )

        self.service.persist(
            "turn-1",
            {"operation": "update_profile"},
            AppError(503, "failed", reason="provider_unavailable"),
        )

        _, stored = self._stored()
        step = stored["command_receipts"][0]
        self.assertEqual(
            step["result"], {"ok": True, "status": "saved", "artifact_id": "art-1"}
        )
        self.assertEqual(step["changes"], [{"id": "change-1"}])
        self.assertNotIn("synthetic bulk", json.dumps(stored))

    def test_failed_and_cancelled_turns_keep_the_usage_they_spent(self) -> None:
        usage = {
            "requests": 2,
            "input_tokens": 4000,
            "cached_input_tokens": 1000,
            "output_tokens": 30,
        }
        for error in (
            AppError(503, "failed", reason="provider_unavailable"),
            AppError(499, "cancelled", reason="chat_cancelled"),
        ):
            with self.subTest(reason=error.reason):
                with self.manager.unit_of_work() as db:
                    db.execute("DELETE FROM coach_commands")
                    user = self.chat.add(db, "user", "Frage", client_turn_id="turn-1")
                self._seed({"user_message_id": user["id"]})
                with metered_turn(usage):
                    self.service.persist("turn-1", {}, error)
                self.assertEqual(
                    self._stored()[1]["usage"], {**usage, "by_model": {"": usage}}
                )

    def test_cancellation_clears_pending_and_completed_replay_does_not_duplicate(
        self,
    ) -> None:
        self._seed({"command_receipts": []})
        with self.manager.unit_of_work() as db:
            self.kv.set(db, "coach_pending_request", "queued")
        first = self.service.persist(
            "turn-1", {}, AppError(499, "stopped", reason="chat_cancelled")
        )
        second = self.service.persist(
            "turn-1", {}, AppError(499, "stopped", reason="chat_cancelled")
        )
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "cancelled")
        with self.manager.reader() as db:
            self.assertEqual(self.kv.get(db, "coach_pending_request"), "null")
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM messages WHERE role='assistant'"
                ).fetchone()[0],
                1,
            )
        self.assertEqual(len(self.events.since()["events"]), 1)

    def test_message_insert_failure_rolls_back_pending_request_and_receipt(
        self,
    ) -> None:
        with self.manager.unit_of_work() as db:
            user = self.chat.add(
                db, "user", "Plan bitte lokal", client_turn_id="turn-1"
            )
        self._seed({"user_message_id": user["id"], "command_receipts": []})
        self.service._deps.chat_repository.add = Mock(
            side_effect=RuntimeError("synthetic write failure")
        )

        with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
            self.service.persist("turn-1", {}, AppError(503, "failed"))

        status, _ = self._stored()
        self.assertEqual(status, "running")
        with self.manager.reader() as db:
            self.assertIsNone(self.kv.get(db, "coach_pending_request"))
        self.assertEqual(self.events.since()["events"], [])

    def test_response_keeps_confirmed_effects_clarification_and_cancellation(
        self,
    ) -> None:
        saved = {"tool": "save_checkin", "result": {"ok": True, "status": "saved"}}
        asked = {
            "tool": "clarify_coach_request",
            "result": {"ok": True, "question": "Wie fühlst du dich?"},
        }
        sync = {
            "tool": "start_intervals_plan_sync",
            "result": {"ok": True, "status": "queued"},
        }
        status, text, question, cancelled = self.service._response(
            AppError(429, "Provider limit", reason="rate_limit_exceeded"),
            [sync],
            [sync],
            [],
            ["start_intervals_plan_sync"],
        )
        self.assertEqual((status, question, cancelled), ("partial", None, False))
        for expected in ("Anfragelimit", "bleibt bestehen", "Noch offen"):
            self.assertIn(expected, text)

        status, text, question, cancelled = self.service._response(
            AppError(502, "Provider error", reason="provider_unavailable"),
            [saved, asked],
            [saved],
            [],
            [],
        )
        self.assertEqual(
            (status, question, cancelled), ("completed", "Wie fühlst du dich?", False)
        )
        self.assertTrue(text.startswith("Wie fühlst du dich?"))
        self.assertIn("Bereits erfolgreich ausgeführt", text)

        status, _, question, cancelled = self.service._response(
            AppError(499, "Cancelled", reason="chat_cancelled"),
            [saved, asked],
            [saved],
            [],
            [],
        )
        self.assertEqual(
            (status, question, cancelled), ("partial", "Wie fühlst du dich?", True)
        )

    def test_openai_configuration_failure_explanation(self) -> None:
        for reason, expected in (
            ("openai_not_configured", "OpenAI ist nicht eingerichtet"),
            ("not_configured", "OpenAI ist nicht eingerichtet"),
        ):
            status, text, _, _ = self.service._base_response(
                AppError(503, "not configured", reason=reason), []
            )
            self.assertEqual(status, "failed")
            self.assertIn(expected, text)
            self.assertNotIn("OPENAI_API_KEY", text)

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

    def test_busy_local_database_is_explained_as_a_short_retry(self) -> None:
        status, text, _, _ = self.service._base_response(
            DatabaseBusyError("writer"), []
        )

        self.assertEqual(status, "failed")
        self.assertEqual(
            text, "Die lokale Datenbank war kurz ausgelastet. Bitte versuche es erneut."
        )

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

    def test_openai_billing_failure_is_a_persisted_actionable_chat_message(
        self,
    ) -> None:
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
            message = db.execute(
                "SELECT content FROM messages WHERE role='assistant'"
            ).fetchone()
        self.assertEqual(message["content"], expected)
        self.assertIs(result["message"]["coach_failed"], True)
        # The chat offers to send a failed turn again, after a reload too.
        self.assertIs(self._reloaded_reply()["coach_failed"], True)

    def _reloaded_reply(self) -> dict:
        # The chat reader projects dict rows, as the production database does.
        reader = temp_database(
            self,
            path=Path(self.temporary.name) / "failure.sqlite",
            row_factory=production_row_factory,
            persist_connections=False,
        )
        with reader.reader() as db:
            return next(m for m in self.chat.list(db) if m["role"] == "assistant")

    def test_failed_quick_action_keeps_its_kind_for_the_retry(self) -> None:
        self._seed({"command_receipts": [], "request_kind": "plan_week"})
        result = self.service.persist(
            "turn-1", {}, AppError(504, "late", reason="provider_timeout")
        )
        self.assertEqual(result["message"]["coach_request_kind"], "plan_week")
        self.assertEqual(self._reloaded_reply()["coach_request_kind"], "plan_week")

    def test_reloaded_reply_names_the_model_that_wrote_it(self) -> None:
        self._seed({"command_receipts": [], "model": "claude-opus"})
        self.service.persist(
            "turn-1", {}, AppError(504, "late", reason="provider_timeout")
        )
        self.assertEqual(self._reloaded_reply()["coach_model"], "claude-opus")
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE coach_commands SET receipt='{}'")
        self.assertNotIn("coach_model", self._reloaded_reply())

    def test_cancelled_turn_is_not_marked_as_failed(self) -> None:
        self._seed({"command_receipts": []})
        result = self.service.persist(
            "turn-1", {}, AppError(499, "stopped", reason="chat_cancelled")
        )
        self.assertNotIn("coach_failed", result["message"])
        self.assertNotIn("coach_failed", self._reloaded_reply())


if __name__ == "__main__":
    unittest.main()
