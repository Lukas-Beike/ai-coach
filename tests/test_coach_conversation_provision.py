"""Provider-fake tests for Coach conversation ID provisioning."""

import sqlite3
import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from backend.coach.conversation import CoachConversationProvisionService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError


class _TrackingLock:
    def __init__(self):
        self.held = False

    def __enter__(self):
        self.held = True

    def __exit__(self, *_args):
        self.held = False


class CoachConversationProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "coach.sqlite3",
            sqlite3,
            row_factory=lambda cursor, row: sqlite3.Row(cursor, row),
        )
        self.addCleanup(self.database_manager.close)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
        self.key_values = KeyValueRepository(lambda: "synthetic-now")
        self.openai = Mock()
        self.uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        self.service = CoachConversationProvisionService(
            self.database_manager,
            self.key_values,
            self.openai,
            threading.RLock(),
            lambda: self.uuid,
        )

    def stored(self, key):
        with self.database_manager.reader() as db:
            return self.key_values.get(db, key)

    def save(self, key, value):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def test_openai_reuses_existing_id_without_provider_lookup(self):
        self.save("openai_conversation_id", "conv-existing")

        self.assertEqual(self.service.ensure(), "conv-existing")
        self.openai.request.assert_not_called()

    def test_openai_creates_id_with_existing_metadata_contract(self):
        self.openai.request.return_value = {"id": "conv-created"}

        self.assertEqual(self.service.ensure(), "conv-created")
        self.assertEqual(self.stored("openai_conversation_id"), "conv-created")
        self.openai.request.assert_called_once_with(
            "/conversations",
            {"metadata": {"app": "intervals-coach", "purpose": "personal-coach"}},
        )

    def test_openai_request_holds_neither_database_transaction_nor_db_lock(self):
        lock = _TrackingLock()
        transaction_depth = 0
        original_unit_of_work = self.database_manager.unit_of_work

        @contextmanager
        def tracked_unit_of_work():
            nonlocal transaction_depth
            transaction_depth += 1
            try:
                with original_unit_of_work() as db:
                    yield db
            finally:
                transaction_depth -= 1

        def create_conversation(*_args):
            self.assertFalse(lock.held)
            self.assertEqual(transaction_depth, 0)
            return {"id": "conv-outside-lock"}

        self.openai.request.side_effect = create_conversation
        service = CoachConversationProvisionService(
            self.database_manager,
            self.key_values,
            self.openai,
            lock,
            lambda: self.uuid,
        )
        with patch.object(self.database_manager, "unit_of_work", tracked_unit_of_work):
            self.assertEqual(service.ensure(), "conv-outside-lock")
        self.assertEqual(transaction_depth, 0)

    def test_openai_invalid_id_is_502_and_not_persisted(self):
        self.openai.request.return_value = {"id": None}

        with self.assertRaises(AppError) as raised:
            self.service.ensure()

        self.assertEqual(raised.exception.status, 502)
        self.assertIsNone(self.stored("openai_conversation_id"))

    def _command(self, client_turn_id, conversation_id):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS coach_commands (id TEXT PRIMARY KEY, "
                "client_turn_id TEXT, conversation_id TEXT, receipt TEXT)"
            )
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, conversation_id, receipt) "
                "VALUES (?, ?, ?, '{}')",
                (client_turn_id, client_turn_id, conversation_id),
            )

    def _receipt_flag(self, client_turn_id):
        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT json_extract(receipt, '$.openai_conversation_rotated') AS flag, "
                "conversation_id FROM coach_commands WHERE client_turn_id=?",
                (client_turn_id,),
            ).fetchone()
        return row["flag"], row["conversation_id"]

    def test_rotate_keeps_unused_conversation_without_provider_call(self):
        self.save("openai_conversation_id", "conv-current")
        self._command("turn-1", "conv-current")

        self.assertEqual(self.service.rotate("turn-1", "conv-current"), "conv-current")

        self.openai.request.assert_not_called()
        self.openai.delete_conversation.assert_not_called()
        self.assertEqual(self._receipt_flag("turn-1"), (1, "conv-current"))
        self.assertEqual(self.stored("openai_conversation_id"), "conv-current")

    def test_rotate_replaces_used_conversation_and_deletes_old_remotely(self):
        self.save("openai_conversation_id", "conv-old")
        self._command("earlier", "conv-old")
        self._command("turn-1", "conv-old")
        self.openai.request.return_value = {"id": "conv-new"}

        self.assertEqual(self.service.rotate("turn-1", "conv-old"), "conv-new")
        self.service.remote_delete_thread.join(timeout=5)

        self.openai.request.assert_called_once_with(
            "/conversations",
            {"metadata": {"app": "intervals-coach", "purpose": "personal-coach"}},
        )
        self.openai.delete_conversation.assert_called_once_with("conv-old")
        self.assertEqual(self.stored("openai_conversation_id"), "conv-new")
        self.assertEqual(self._receipt_flag("turn-1"), (1, "conv-new"))
        self.assertEqual(self._receipt_flag("earlier"), (None, "conv-old"))

    def test_rotate_remote_delete_failure_only_logs_a_warning(self):
        self.save("openai_conversation_id", "conv-old")
        self._command("earlier", "conv-old")
        self._command("turn-1", "conv-old")
        self.openai.request.return_value = {"id": "conv-new"}
        self.openai.delete_conversation.side_effect = RuntimeError("synthetic")
        logger = Mock()
        service = CoachConversationProvisionService(
            self.database_manager,
            self.key_values,
            self.openai,
            threading.RLock(),
            lambda: self.uuid,
            logger=logger,
        )

        self.assertEqual(service.rotate("turn-1", "conv-old"), "conv-new")
        service.remote_delete_thread.join(timeout=5)

        logger.warning.assert_called_once()
        self.assertEqual(
            logger.warning.call_args.kwargs["extra"],
            {"event": "openai_rotation_remote_delete_failed"},
        )
        self.assertEqual(self.stored("openai_conversation_id"), "conv-new")

    def test_rotate_invalid_id_is_502_and_persists_nothing(self):
        self.save("openai_conversation_id", "conv-old")
        self._command("earlier", "conv-old")
        self._command("turn-1", "conv-old")
        self.openai.request.return_value = {"id": None}

        with self.assertRaises(AppError) as raised:
            self.service.rotate("turn-1", "conv-old")

        self.assertEqual(raised.exception.status, 502)
        self.openai.delete_conversation.assert_not_called()
        self.assertEqual(self.stored("openai_conversation_id"), "conv-old")
        self.assertEqual(self._receipt_flag("turn-1"), (None, "conv-old"))

    def test_rotate_creates_conversation_outside_database_lock(self):
        self.save("openai_conversation_id", "conv-old")
        self._command("earlier", "conv-old")
        self._command("turn-1", "conv-old")
        lock = _TrackingLock()
        transaction_depth = 0
        original_unit_of_work = self.database_manager.unit_of_work

        @contextmanager
        def tracked_unit_of_work():
            nonlocal transaction_depth
            transaction_depth += 1
            try:
                with original_unit_of_work() as db:
                    yield db
            finally:
                transaction_depth -= 1

        def create_conversation(*_args):
            self.assertFalse(lock.held)
            self.assertEqual(transaction_depth, 0)
            return {"id": "conv-outside-lock"}

        self.openai.request.side_effect = create_conversation
        service = CoachConversationProvisionService(
            self.database_manager,
            self.key_values,
            self.openai,
            lock,
            lambda: self.uuid,
        )
        with patch.object(self.database_manager, "unit_of_work", tracked_unit_of_work):
            self.assertEqual(service.rotate("turn-1", "conv-old"), "conv-outside-lock")
        service.remote_delete_thread.join(timeout=5)
        self.assertEqual(transaction_depth, 0)


if __name__ == "__main__":
    unittest.main()
