"""Focused SQLite tests for the Coach chat-message service."""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.coach.conversation import CoachMessageService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import ChatRepository
from backend.db.schema import initialize_schema
from backend.runtime.events import StateEventBuffer


NOW = "2026-09-23T08:00:00+00:00"


class FailBeforeCommitDatabaseManager:
    """Raise after the service body, before the wrapped unit of work commits."""

    def __init__(self, manager: DatabaseManager):
        self._manager = manager

    @contextmanager
    def unit_of_work(self):
        with self._manager.unit_of_work() as db:
            yield db
            raise RuntimeError("synthetic pre-commit failure")

    def reader(self):
        return self._manager.reader()


class CoachMessageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "coach.sqlite"
        db = sqlite3.connect(self.database_path)
        try:
            db.row_factory = row_factory
            initialize_schema(db)
            db.commit()
        finally:
            db.close()
        self.database_manager = DatabaseManager(
            self.database_path,
            sqlite3,
            row_factory=row_factory,
            persist_connections=False,
        )
        self.events = StateEventBuffer()
        self.service = CoachMessageService(
            self.database_manager,
            ChatRepository(lambda: NOW),
            self.events,
        )

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temp_dir.cleanup()

    def test_add_commits_before_publishing_coach_event(self) -> None:
        result = self.service.add("user", "  Hallo Coach  ")

        self.assertEqual(result["content"], "Hallo Coach")
        with self.database_manager.reader() as db:
            persisted = db.execute(
                "SELECT id, role, content FROM messages WHERE id = ?", (result["id"],)
            ).fetchone()
        self.assertEqual(dict(persisted), {"id": result["id"], "role": "user", "content": "Hallo Coach"})
        self.assertEqual(
            self.events.since()["events"][0]["data"],
            {"message_id": result["id"], "role": "user"},
        )

    def test_invalid_role_rolls_back_without_publishing(self) -> None:
        with self.assertRaisesRegex(ValueError, "Chat role must be user or assistant"):
            self.service.add("system", "not allowed")

        with self.database_manager.reader() as db:
            count = db.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
        self.assertEqual(count, 0)
        self.assertEqual(self.events.since()["events"], [])

    def test_list_preserves_repository_order_limit_and_attachment_names(self) -> None:
        first = self.service.add("user", "first")
        second = self.service.add("assistant", "second")
        third = self.service.add("user", "third")
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE messages SET attachments = ? WHERE id = ?",
                (json.dumps([{"name": "run.fit"}, {"name": "notes.txt"}]), second["id"]),
            )

        messages = self.service.list(limit=2)

        self.assertEqual([message["id"] for message in messages], [second["id"], third["id"]])
        self.assertEqual(messages[0]["attachment_names"], '["run.fit","notes.txt"]')
        self.assertNotIn("client_turn_id", messages[0])
        self.assertNotIn("attachment_names", messages[1])
        self.assertEqual([message["id"] for message in self.service.list()], [first["id"], second["id"], third["id"]])

    def test_list_is_read_only_and_does_not_publish_events(self) -> None:
        self.service.add("user", "existing")
        events_before = self.events.since()
        with self.database_manager.reader() as db:
            count_before = db.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]

        self.service.list()

        with self.database_manager.reader() as db:
            count_after = db.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
        self.assertEqual(count_after, count_before)
        self.assertEqual(self.events.since(), events_before)

    def test_failure_before_commit_does_not_publish_event(self) -> None:
        failing_service = CoachMessageService(
            FailBeforeCommitDatabaseManager(self.database_manager),
            ChatRepository(lambda: NOW),
            self.events,
        )

        with self.assertRaisesRegex(RuntimeError, "synthetic pre-commit failure"):
            failing_service.add("user", "rolled back")

        with self.database_manager.reader() as db:
            count = db.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
        self.assertEqual(count, 0)
        self.assertEqual(self.events.since()["events"], [])


if __name__ == "__main__":
    unittest.main()
