import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from backend.coach.conversation import (
    GeminiConversationHistoryService,
    GeminiResponseNormalizationService,
)
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError


class GeminiResponseNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "gemini-response.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: "2026-09-23T00:00:00+00:00")
        self.history_service = GeminiConversationHistoryService(self.database_manager, self.key_values)
        self.ids = iter(uuid.UUID(int=value) for value in (1, 2, 3))
        self.service = GeminiResponseNormalizationService(
            self.history_service,
            self.database_manager,
            self.key_values,
            lambda: next(self.ids),
        )

    def tearDown(self):
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def _get(self, key):
        with self.database_manager.reader() as db:
            return self.key_values.get(db, key)

    def test_missing_response_raises_502_without_persisting_history(self):
        with self.assertRaises(AppError) as raised:
            self.service.normalize({}, [{"role": "user", "parts": [{"text": "Question"}]}], True, {})

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.reason, "invalid_response")
        self.assertIsNone(self._get("gemini_conversation_history"))

    def test_parallel_tool_calls_rejected_before_history_or_call_name_persistence(self):
        history = [{"role": "user", "parts": [{"text": "Do these"}]}]
        result = {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "first", "args": {}}},
            {"functionCall": {"name": "second", "args": {}}},
        ]}}]}

        with self.assertRaises(AppError) as raised:
            self.service.normalize({"parallel_tool_calls": False}, history, True, result)

        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(raised.exception.reason, "parallel_tool_calls_unsupported")
        self.assertIsNone(self._get("gemini_conversation_history"))
        self.assertIsNone(self._get("gemini_call_names"))

    def test_text_and_function_calls_preserve_persistence_id_order_and_usage(self):
        history = [{"role": "user", "parts": [{"text": "Save"}]}]
        model_content = {"role": "model", "parts": [
            {"text": "Saved locally."},
            {"functionCall": {"name": " save_checkin ", "args": {"day_form": "good"}}},
            {"functionCall": {"name": "get_profile", "args": {}}},
        ]}
        result = {
            "candidates": [{"content": model_content}],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7, "totalTokenCount": 18},
        }

        normalized = self.service.normalize({}, history, True, result)

        self.assertEqual(normalized["output_text"], "Saved locally.")
        self.assertEqual(normalized["output"][0], {
            "type": "message",
            "content": [{"type": "output_text", "text": "Saved locally."}],
        })
        calls = normalized["output"][1:]
        self.assertEqual([call["call_id"] for call in calls], [
            "gemini_" + uuid.UUID(int=1).hex,
            "gemini_" + uuid.UUID(int=2).hex,
        ])
        self.assertEqual([call["name"] for call in calls], ["save_checkin", "get_profile"])
        self.assertEqual(calls[0]["arguments"], '{"day_form": "good"}')
        self.assertEqual(calls[1]["arguments"], "{}")
        self.assertEqual(normalized["id"], "gemini_" + uuid.UUID(int=3).hex)
        self.assertEqual(normalized["usage"], {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        })
        self.assertEqual(json.loads(self._get("gemini_conversation_history")), [
            {"role": "user", "parts": [{"text": "Save"}]},
            model_content,
        ])
        self.assertEqual(json.loads(self._get("gemini_call_names")), {
            calls[0]["call_id"]: "save_checkin",
            calls[1]["call_id"]: "get_profile",
        })

    def test_missing_usage_fields_default_to_zero_without_remote_writes(self):
        result = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Done"}]}}]}

        normalized = self.service.normalize({}, [], False, result)

        self.assertEqual(normalized["usage"], {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
        self.assertIsNone(self._get("gemini_conversation_history"))
        self.assertIsNone(self._get("gemini_call_names"))


if __name__ == "__main__":
    unittest.main()
