import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.coach.conversation import GeminiConversationHistoryService


class _FailingCallNamesRepository(KeyValueRepository):
    def set(self, db, key, value):
        if key == "gemini_call_names":
            raise RuntimeError("call names write failed")
        super().set(db, key, value)


class GeminiConversationHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "gemini-history.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: "2026-09-23T00:00:00+00:00")
        self.service = GeminiConversationHistoryService(self.database_manager, self.key_values)

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def _set(self, key, value):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def _get(self, key):
        with self.database_manager.reader() as db:
            return self.key_values.get(db, key)

    def test_load_treats_corrupt_json_as_empty_history(self):
        self._set("gemini_conversation_history", "{broken")

        self.assertEqual(self.service.load(), [])

    def test_load_retains_latest_sixty_entries_at_complete_exchange_boundary(self):
        history = [
            {"role": role, "parts": [{"text": f"{role} {index}"}]}
            for index in range(35)
            for role in ("user", "model")
        ]
        self._set("gemini_conversation_history", json.dumps(history))

        loaded = self.service.load()

        self.assertEqual(len(loaded), 60)
        self.assertEqual(loaded[0]["parts"][0]["text"], "user 5")
        self.assertEqual(loaded[-1]["parts"][0]["text"], "model 34")

    def test_save_sanitizes_inline_and_fit_raw_media_and_preserves_other_values(self):
        history = [{"role": "user", "parts": [
            {"text": "Keep this prompt"},
            {"inlineData": {"mimeType": "image/png", "data": "secret"}},
            {"text": '{"untrusted_fit_raw_base64":"secret"}'},
            {"text": '{"untrusted_attachment_name":"route.fit"}'},
        ]}]
        self._set("unrelated_setting", "leave me alone")

        self.service.save(history)

        self.assertEqual(
            json.loads(self._get("gemini_conversation_history")),
            [{"role": "user", "parts": [
                {"text": "Keep this prompt"},
                {"text": '{"untrusted_attachment_name":"route.fit"}'},
            ]}],
        )
        self.assertEqual(self._get("unrelated_setting"), "leave me alone")

    def test_repair_drops_only_unexecuted_trailing_call_and_clears_names(self):
        history = [
            {"role": "user", "parts": [{"text": "Save this"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "save", "args": {}}}]},
        ]
        self._set("gemini_conversation_history", json.dumps(history))
        self._set("gemini_call_names", '{"call-1":"save"}')

        with self.database_manager.unit_of_work() as db:
            self.service.repair_incomplete(db)

        self.assertEqual(json.loads(self._get("gemini_conversation_history")), history[:1])
        self.assertEqual(self._get("gemini_call_names"), "{}")

    def test_repair_rolls_back_both_writes_if_call_names_write_fails(self):
        history = [
            {"role": "user", "parts": [{"text": "Save this"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "save", "args": {}}}]},
        ]
        history_json = json.dumps(history)
        call_names_json = '{"call-1":"save"}'
        self._set("gemini_conversation_history", history_json)
        self._set("gemini_call_names", call_names_json)
        service = GeminiConversationHistoryService(
            self.database_manager,
            _FailingCallNamesRepository(lambda: "2026-09-23T00:00:00+00:00"),
        )

        with self.assertRaisesRegex(RuntimeError, "call names write failed"):
            with self.database_manager.unit_of_work() as db:
                service.repair_incomplete(db)

        self.assertEqual(self._get("gemini_conversation_history"), history_json)
        self.assertEqual(self._get("gemini_call_names"), call_names_json)

    def test_repair_leaves_completed_tool_exchange_unchanged(self):
        history = [
            {"role": "user", "parts": [{"text": "Save this"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "save", "args": {}}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "save", "response": {"ok": True}}}]},
            {"role": "model", "parts": [{"text": "Saved"}]},
        ]
        history_json = json.dumps(history)
        call_names_json = '{"call-1":"save"}'
        self._set("gemini_conversation_history", history_json)
        self._set("gemini_call_names", call_names_json)

        with self.database_manager.unit_of_work() as db:
            self.service.repair_incomplete(db)

        self.assertEqual(self._get("gemini_conversation_history"), history_json)
        self.assertEqual(self._get("gemini_call_names"), call_names_json)


if __name__ == "__main__":
    unittest.main()
