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
            db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        self.key_values = KeyValueRepository(lambda: "synthetic-now")
        self.settings = Mock()
        self.settings.selected_ai_provider.return_value = "openai"
        self.openai = Mock()
        self.uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        self.service = CoachConversationProvisionService(
            self.settings,
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

    def test_gemini_reuses_existing_id(self):
        self.save("gemini_conversation_id", "gemini-existing")

        self.assertEqual(self.service.ensure("gemini"), "gemini-existing")
        self.settings.selected_ai_provider.assert_not_called()
        self.openai.request.assert_not_called()

    def test_gemini_creates_and_persists_expected_id(self):
        conversation_id = self.service.ensure("gemini")

        self.assertEqual(conversation_id, "gemini_12345678123456781234567812345678")
        self.assertEqual(self.stored("gemini_conversation_id"), conversation_id)
        self.settings.selected_ai_provider.assert_not_called()
        self.openai.request.assert_not_called()

    def test_openai_reuses_existing_id_without_provider_lookup(self):
        self.save("openai_conversation_id", "conv-existing")

        self.assertEqual(self.service.ensure("openai"), "conv-existing")
        self.settings.selected_ai_provider.assert_not_called()
        self.openai.request.assert_not_called()

    def test_openai_creates_id_with_existing_metadata_contract(self):
        self.openai.request.return_value = {"id": "conv-created"}

        self.assertEqual(self.service.ensure("openai"), "conv-created")
        self.assertEqual(self.stored("openai_conversation_id"), "conv-created")
        self.openai.request.assert_called_once_with(
            "/conversations",
            {"metadata": {"app": "intervals-coach", "purpose": "personal-coach"}},
        )
        self.settings.selected_ai_provider.assert_not_called()

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
            self.settings,
            self.database_manager,
            self.key_values,
            self.openai,
            lock,
            lambda: self.uuid,
        )
        with patch.object(self.database_manager, "unit_of_work", tracked_unit_of_work):
            self.assertEqual(service.ensure("openai"), "conv-outside-lock")
        self.assertEqual(transaction_depth, 0)

    def test_openai_invalid_id_is_502_and_not_persisted(self):
        self.openai.request.return_value = {"id": None}

        with self.assertRaises(AppError) as raised:
            self.service.ensure("openai")

        self.assertEqual(raised.exception.status, 502)
        self.assertIsNone(self.stored("openai_conversation_id"))

    def test_missing_provider_uses_settings_selection(self):
        self.settings.selected_ai_provider.return_value = "gemini"

        conversation_id = self.service.ensure()

        self.assertTrue(conversation_id.startswith("gemini_"))
        self.settings.selected_ai_provider.assert_called_once_with()
        self.assertEqual(self.stored("gemini_conversation_id"), conversation_id)


if __name__ == "__main__":
    unittest.main()
