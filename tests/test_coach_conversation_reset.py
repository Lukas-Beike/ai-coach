"""Conversation reset cancels turns first, bounds the lock wait and defers remote deletion."""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
import uuid
from contextlib import contextmanager
from typing import cast
from unittest.mock import Mock

from backend.coach.conversation import (
    CoachConversationProvisionService,
    CoachConversationResetService,
)
from backend.coach.streams import ChatStreamRegistry
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError

WAIT_SECONDS = 2
NEW_GENERATION = uuid.UUID(int=1)


class _Manager:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE coach_commands(client_turn_id TEXT, receipt TEXT, status TEXT, updated_at TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY, content TEXT);
            CREATE TABLE coach_action_proposals(action_type TEXT, status TEXT, action_token_hash TEXT);
            CREATE TABLE coach_plan_artifacts(status TEXT, updated_at TEXT);
            INSERT INTO messages(content) VALUES ('old chat');
            INSERT INTO coach_commands(client_turn_id, receipt, status)
                VALUES ('turn-1', '{"operation_id":"op-1","status":"running"}', 'running');
            """
        )
        self.db.commit()

    @contextmanager
    def unit_of_work(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


class CoachConversationResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _Manager()
        self.database_manager = cast(DatabaseManager, self.manager)
        self.addCleanup(self.manager.db.close)
        self.key_values = KeyValueRepository(lambda: "2026-09-29T12:00:00+00:00")
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, "openai_conversation_id", "old-openai-id")
            self.key_values.set(db, "chat_generation", "old-generation")
        self.conversation_lock = threading.RLock()
        self.streams = ChatStreamRegistry()
        self.turn_cancel = threading.Event()
        self.streams.set_background_event("op-1", self.turn_cancel)
        self.remote_entered = threading.Event()
        self.remote_release = threading.Event()
        self.remote_calls: list[str] = []
        self.remote_result: bool | Exception = True
        self.logger = Mock()

        def delete_conversation(conversation_id: str) -> bool:
            self.remote_calls.append(conversation_id)
            self.remote_entered.set()
            self.remote_release.wait(WAIT_SECONDS)
            if isinstance(self.remote_result, Exception):
                raise self.remote_result
            return self.remote_result

        self.openai = Mock(delete_conversation=delete_conversation)
        self.service = self.make_service()

    def make_service(self, **kwargs) -> CoachConversationResetService:
        return CoachConversationResetService(
            self.database_manager,
            self.key_values,
            self.openai,
            self.streams,
            threading.RLock(),
            self.conversation_lock,
            lambda: "2026-09-29T12:00:00+00:00",
            lambda: NEW_GENERATION,
            self.logger,
            **kwargs,
        )

    def read(self, key: str) -> str | None:
        with self.manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def count_messages(self) -> int:
        with self.manager.unit_of_work() as db:
            return db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def command(self) -> tuple[str, dict]:
        with self.manager.unit_of_work() as db:
            row = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id='turn-1'"
            ).fetchone()
        return row["status"], json.loads(row["receipt"])

    def hold_lock_in_thread(self) -> tuple[threading.Thread, threading.Event]:
        """Hold the conversation lock from another thread, like a running turn."""
        held = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with self.conversation_lock:
                held.set()
                release.wait(WAIT_SECONDS * 5)

        thread = threading.Thread(target=hold, daemon=True)
        thread.start()
        self.assertTrue(held.wait(WAIT_SECONDS))
        self.addCleanup(release.set)
        return thread, release

    @staticmethod
    def remote_thread(service: CoachConversationResetService) -> threading.Thread:
        thread = service.remote_delete_thread
        assert thread is not None
        return thread

    def finish_remote_delete(self) -> None:
        self.remote_release.set()
        thread = self.remote_thread(self.service)
        thread.join(WAIT_SECONDS)
        self.assertFalse(thread.is_alive())

    def test_reset_cancels_running_turn_before_waiting_for_the_lock(self) -> None:
        turn_saw_cancel: list[bool] = []
        turn_holding_lock = threading.Event()

        def running_turn() -> None:
            with self.conversation_lock:
                turn_holding_lock.set()
                # A turn only ends early when the reset asks it to stop.
                turn_saw_cancel.append(self.turn_cancel.wait(WAIT_SECONDS))

        turn = threading.Thread(target=running_turn, daemon=True)
        turn.start()
        self.assertTrue(turn_holding_lock.wait(WAIT_SECONDS))
        results: list[dict] = []
        reset = threading.Thread(
            target=lambda: results.append(self.service.reset()), daemon=True
        )
        reset.start()
        turn.join(WAIT_SECONDS * 2)
        reset.join(WAIT_SECONDS * 2)

        self.assertEqual(turn_saw_cancel, [True])
        self.assertFalse(reset.is_alive())
        self.assertEqual(results[0]["generation"], NEW_GENERATION.hex)
        self.assertEqual(self.count_messages(), 0)
        status, receipt = self.command()
        self.assertEqual((status, receipt["status"]), ("completed", "cancelled"))
        self.finish_remote_delete()

    def test_lock_timeout_fails_with_error_and_leaves_state_untouched(self) -> None:
        service = self.make_service(lock_timeout_seconds=0.05)
        self.hold_lock_in_thread()

        with self.assertRaises(AppError) as raised:
            service.reset()

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.reason, "chat_reset_timeout")
        self.assertTrue(self.turn_cancel.is_set())
        self.assertEqual(self.count_messages(), 1)
        self.assertEqual(self.read("openai_conversation_id"), "old-openai-id")
        self.assertEqual(self.read("chat_generation"), "old-generation")
        self.assertEqual(self.command()[0], "running")
        self.assertEqual(self.remote_calls, [])
        self.assertIsNone(service.remote_delete_thread)

    def test_reset_succeeds_after_a_lock_timeout_once_the_turn_released(self) -> None:
        service = self.make_service(lock_timeout_seconds=0.05)
        _, release = self.hold_lock_in_thread()
        with self.assertRaises(AppError):
            service.reset()
        release.set()
        self.assertTrue(self.conversation_lock.acquire(timeout=WAIT_SECONDS))
        self.conversation_lock.release()

        result = service.reset()

        self.assertEqual(result["generation"], NEW_GENERATION.hex)
        self.assertEqual(self.count_messages(), 0)
        self.remote_release.set()
        self.remote_thread(service).join(WAIT_SECONDS)

    def test_slow_remote_delete_does_not_delay_the_reset_response(self) -> None:
        result = self.service.reset()

        # The remote call is still blocked, yet the local reset is committed.
        self.assertIsNone(result["remote_conversation_deleted"])
        self.assertEqual(result["generation"], NEW_GENERATION.hex)
        self.assertEqual(self.read("openai_conversation_id"), "")
        self.assertEqual(self.count_messages(), 0)
        self.assertTrue(self.remote_entered.wait(WAIT_SECONDS))
        self.assertTrue(self.remote_thread(self.service).is_alive())
        self.assertTrue(self.conversation_lock.acquire(timeout=WAIT_SECONDS))
        self.conversation_lock.release()
        self.assertEqual(self.remote_calls, ["old-openai-id"])
        self.finish_remote_delete()

    def test_failing_remote_delete_is_logged_and_does_not_fail_the_reset(self) -> None:
        self.remote_result = RuntimeError("synthetic remote failure")
        self.remote_release.set()

        result = self.service.reset()
        self.finish_remote_delete()

        self.assertEqual(result["status"], "ok")
        self.logger.warning.assert_called_once()
        self.assertEqual(
            self.logger.warning.call_args.kwargs["extra"],
            {"event": "openai_reset_remote_delete_failed"},
        )

    def test_next_turn_provisions_a_new_conversation_after_failed_remote_delete(
        self,
    ) -> None:
        self.remote_result = RuntimeError("synthetic remote failure")
        self.remote_release.set()
        self.service.reset()
        self.finish_remote_delete()
        client = Mock()
        client.request.return_value = {"id": "new-openai-id"}
        provision = CoachConversationProvisionService(
            self.database_manager,
            self.key_values,
            client,
            threading.RLock(),
            uuid.uuid4,
        )

        self.assertEqual(provision.ensure(), "new-openai-id")
        client.request.assert_called_once()
        self.assertEqual(self.read("openai_conversation_id"), "new-openai-id")

    def test_repeated_reset_is_idempotent_and_deletes_the_remote_chat_once(
        self,
    ) -> None:
        self.remote_release.set()
        first = self.service.reset()
        self.finish_remote_delete()
        second = self.service.reset()

        self.assertIsNone(first["remote_conversation_deleted"])
        self.assertFalse(second["remote_conversation_deleted"])
        self.assertEqual(second["status"], "ok")
        self.assertEqual(self.remote_calls, ["old-openai-id"])
        self.assertEqual(self.count_messages(), 0)
        self.assertEqual(self.read("openai_conversation_id"), "")

    def test_reset_without_running_turn_or_conversation_is_safe(self) -> None:
        with self.manager.unit_of_work() as db:
            db.execute("DELETE FROM coach_commands")
            self.key_values.set(db, "openai_conversation_id", "")

        result = self.service.reset()

        self.assertFalse(result["remote_conversation_deleted"])
        self.assertEqual(self.remote_calls, [])
        self.assertIsNone(self.service.remote_delete_thread)
        self.assertEqual(self.count_messages(), 0)


if __name__ == "__main__":
    unittest.main()
