"""Conversation reset commits local state before best-effort provider deletion."""

from __future__ import annotations

import sqlite3
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from backend.coach.conversation import CoachConversationResetService
from backend.db.repositories import KeyValueRepository


class _Manager:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE kv(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE coach_commands(client_turn_id TEXT, receipt TEXT, status TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY, content TEXT);
            CREATE TABLE coach_action_proposals(action_type TEXT, status TEXT, action_token_hash TEXT);
            CREATE TABLE coach_plan_artifacts(status TEXT, updated_at TEXT);
            INSERT INTO messages(content) VALUES ('old chat');
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


class _TrackedLock:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = False

    def __enter__(self):
        self.lock.acquire()
        self.active = True
        return self

    def __exit__(self, *_exc):
        self.active = False
        self.lock.release()


class CoachConversationResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _Manager()
        self.addCleanup(self.manager.db.close)
        self.key_values = KeyValueRepository(lambda: "2026-09-29T12:00:00+00:00")
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, "openai_conversation_id", "old-openai-id")
        self.conversation_lock = _TrackedLock()
        self.remote_entered = threading.Event()
        self.remote_release = threading.Event()

        def delete_conversation(conversation_id: str) -> bool:
            self.assertEqual(conversation_id, "old-openai-id")
            self.assertFalse(self.conversation_lock.active)
            with self.manager.unit_of_work() as db:
                self.assertEqual(self.key_values.get(db, "openai_conversation_id"), "")
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0
                )
            self.remote_entered.set()
            self.remote_release.wait(2)
            return True

        self.openai = Mock(delete_conversation=delete_conversation)
        self.service = CoachConversationResetService(
            self.manager,
            self.key_values,
            self.openai,
            Mock(),
            threading.RLock(),
            self.conversation_lock,
            lambda: "2026-09-29T12:00:00+00:00",
            lambda: SimpleNamespace(hex="new-generation"),
            Mock(),
        )

    def test_local_reset_commits_and_releases_chat_lock_before_remote_delete(
        self,
    ) -> None:
        results = []
        reset = threading.Thread(target=lambda: results.append(self.service.reset()))
        reset.start()
        self.assertTrue(self.remote_entered.wait(1))
        self.assertTrue(self.conversation_lock.lock.acquire(timeout=0.2))
        self.conversation_lock.lock.release()
        self.remote_release.set()
        reset.join(1)

        self.assertFalse(reset.is_alive())
        self.assertEqual(results[0]["generation"], "new-generation")
        self.assertTrue(results[0]["remote_conversation_deleted"])
        with self.manager.unit_of_work() as db:
            self.assertEqual(
                self.key_values.get(db, "last_chat_reset_at"),
                "2026-09-29T12:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
