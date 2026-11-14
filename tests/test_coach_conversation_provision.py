"""Provider-fake tests for Coach conversation ID provisioning."""

import sqlite3
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch

from support import temp_database

from backend.coach.conversation import CoachConversationProvisionService
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError


class CoachConversationProvisionTests(unittest.TestCase):
    def setUp(self):
        self.database_manager = temp_database(
            self,
            "coach.sqlite3",
            row_factory=lambda cursor, row: sqlite3.Row(cursor, row),
        )
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
        self.openai.create_conversation.assert_not_called()

    def test_openai_creates_id_with_existing_metadata_contract(self):
        self.openai.create_conversation.return_value = "conv-created"

        self.assertEqual(self.service.ensure(), "conv-created")
        self.assertEqual(self.stored("openai_conversation_id"), "conv-created")
        self.openai.create_conversation.assert_called_once_with(
            {"app": "intervals-coach", "purpose": "personal-coach"}
        )

    def test_openai_request_holds_no_database_transaction(self):
        with self.outside_transaction() as service:
            self.assertEqual(service.ensure(), "conv-outside-lock")

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

    def _service(self, logger=None):
        return CoachConversationProvisionService(
            self.database_manager,
            self.key_values,
            self.openai,
            lambda: self.uuid,
            logger=logger,
        )

    def _used_conversation(self):
        """Store conv-old as the current conversation, already used by an earlier turn."""
        self.save("openai_conversation_id", "conv-old")
        self._command("earlier", "conv-old")
        self._command("turn-1", "conv-old")
        self.openai.create_conversation.return_value = "conv-new"

    @contextmanager
    def outside_transaction(self):
        """Yield a service whose provider call holds no transaction."""
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
            self.assertEqual(transaction_depth, 0)
            return "conv-outside-lock"

        self.openai.create_conversation.side_effect = create_conversation
        with patch.object(self.database_manager, "unit_of_work", tracked_unit_of_work):
            yield self._service()
        self.assertEqual(transaction_depth, 0)

    def test_binding_is_local_per_chat_generation_without_provider_call(self):
        self.assertEqual(self.service.binding(), "local-initial")
        self.save("chat_generation", "gen-two")

        self.assertEqual(self.service.binding(), "local-gen-two")
        self.openai.create_conversation.assert_not_called()
        self.assertIsNone(self.stored("openai_conversation_id"))

    def test_binding_prefers_the_stored_remote_conversation(self):
        self.save("openai_conversation_id", "conv-existing")

        self.assertEqual(self.service.binding(), "conv-existing")
        self.openai.create_conversation.assert_not_called()

    def test_bind_remote_creates_conversation_and_rebinds_the_turn(self):
        self._command("turn-1", "local-initial")
        self.openai.create_conversation.return_value = "conv-created"

        self.assertEqual(
            self.service.bind_remote("turn-1", "local-initial"), "conv-created"
        )

        self.assertEqual(self.stored("openai_conversation_id"), "conv-created")
        self.assertEqual(self._receipt_flag("turn-1"), (None, "conv-created"))

    def test_bind_remote_keeps_a_remote_binding_without_provider_call(self):
        self.assertEqual(self.service.bind_remote("turn-1", "conv-old"), "conv-old")
        self.openai.create_conversation.assert_not_called()

    def test_rotate_from_local_binding_creates_remote_without_deleting(self):
        self._command("turn-1", "local-initial")
        self.openai.create_conversation.return_value = "conv-new"

        self.assertEqual(self.service.rotate("turn-1", "local-initial"), "conv-new")

        self.openai.delete_conversation.assert_not_called()
        self.assertEqual(self.stored("openai_conversation_id"), "conv-new")
        self.assertEqual(self._receipt_flag("turn-1"), (1, "conv-new"))

    def test_rotate_keeps_unused_conversation_without_provider_call(self):
        self.save("openai_conversation_id", "conv-current")
        self._command("turn-1", "conv-current")

        self.assertEqual(self.service.rotate("turn-1", "conv-current"), "conv-current")

        self.openai.create_conversation.assert_not_called()
        self.openai.delete_conversation.assert_not_called()
        self.assertEqual(self._receipt_flag("turn-1"), (1, "conv-current"))
        self.assertEqual(self.stored("openai_conversation_id"), "conv-current")

    def test_rotate_replaces_used_conversation_and_deletes_old_remotely(self):
        self._used_conversation()

        self.assertEqual(self.service.rotate("turn-1", "conv-old"), "conv-new")
        self.service.remote_delete_thread.join(timeout=5)

        self.openai.create_conversation.assert_called_once_with(
            {"app": "intervals-coach", "purpose": "personal-coach"}
        )
        self.openai.delete_conversation.assert_called_once_with("conv-old")
        self.assertEqual(self.stored("openai_conversation_id"), "conv-new")
        self.assertEqual(self._receipt_flag("turn-1"), (1, "conv-new"))
        self.assertEqual(self._receipt_flag("earlier"), (None, "conv-old"))

    def test_rotate_remote_delete_failure_only_logs_a_warning(self):
        self._used_conversation()
        self.openai.delete_conversation.side_effect = RuntimeError("synthetic")
        logger = Mock()
        service = self._service(logger=logger)

        self.assertEqual(service.rotate("turn-1", "conv-old"), "conv-new")
        service.remote_delete_thread.join(timeout=5)

        logger.warning.assert_called_once()
        self.assertEqual(
            logger.warning.call_args.kwargs["extra"],
            {"event": "openai_rotation_remote_delete_failed"},
        )
        self.assertEqual(self.stored("openai_conversation_id"), "conv-new")

    def test_rotate_invalid_id_is_502_and_persists_nothing(self):
        self._used_conversation()
        self.openai.create_conversation.side_effect = AppError(502, "synthetic")

        with self.assertRaises(AppError) as raised:
            self.service.rotate("turn-1", "conv-old")

        self.assertEqual(raised.exception.status, 502)
        self.openai.delete_conversation.assert_not_called()
        self.assertEqual(self.stored("openai_conversation_id"), "conv-old")
        self.assertEqual(self._receipt_flag("turn-1"), (None, "conv-old"))

    def test_rotate_creates_conversation_outside_a_transaction(self):
        self._used_conversation()
        with self.outside_transaction() as service:
            self.assertEqual(service.rotate("turn-1", "conv-old"), "conv-outside-lock")
            service.remote_delete_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
