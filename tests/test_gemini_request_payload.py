import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.coach import conversation
from backend.coach.conversation import (
    GeminiConversationHistoryService,
    GeminiConversationResponseService,
    GeminiLocalChatHistoryService,
    GeminiRequestPayloadService,
)
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.db.schema import initialize_schema


class GeminiRequestPayloadServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temp_dir.name) / "coach.sqlite",
            sqlite3,
            row_factory=row_factory,
            persist_connections=False,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: "2026-09-23T08:00:00+00:00")
        self.chat_repository = ChatRepository(lambda: "2026-09-23T08:00:00+00:00")
        self.conversation_history = GeminiConversationHistoryService(
            self.database_manager, self.key_values
        )
        self.local_history = GeminiLocalChatHistoryService(
            self.database_manager, self.chat_repository
        )
        self.service = GeminiRequestPayloadService(
            self.conversation_history,
            self.local_history,
            self.database_manager,
            self.key_values,
        )

    def tearDown(self):
        self.database_manager.close()
        self.temp_dir.cleanup()

    def add_message(self, role, content, attachments=None):
        with self.database_manager.unit_of_work() as db:
            message = self.chat_repository.add(db, role, content)
            if attachments is not None:
                db.execute(
                    "UPDATE messages SET attachments=? WHERE id=?",
                    (json.dumps(attachments), message["id"]),
                )
        return message

    def set_value(self, key, value):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, key, value)

    def get_value(self, key):
        with self.database_manager.reader() as db:
            return self.key_values.get(db, key)

    def build(self, payload):
        return self.service.build(
            payload,
            "gemini-3.8-flash",
            default_max_output_tokens=6000,
            default_thinking_level="medium",
            json_media_type="application/json",
        )

    def test_text_rebuilds_shared_history_without_duplicating_last_user_message(self):
        self.conversation_history.save([
            {"role": "user", "parts": [{"text": "Stale Gemini question"}]},
        ])
        self.add_message("user", "What was my last focus?")
        self.add_message("assistant", "Threshold work.")
        self.add_message("user", "And next?")

        request, history, persistent = self.build({
            "conversation": "coach-dialogue",
            "input": "And next?",
        })

        self.assertTrue(persistent)
        self.assertEqual(
            [entry["parts"][0]["text"] for entry in history],
            ["What was my last focus?", "Threshold work.", "And next?"],
        )
        self.assertEqual(request["contents"], history)

    def test_text_replay_mutates_payload_with_transient_attachment_media(self):
        image = "aGVsbG8="
        self.add_message(
            "user",
            "What is in this image?",
            [{"type": "image", "name": "chart.png", "mime": "image/png", "data": image}],
        )
        payload = {"conversation": "coach-dialogue", "input": "What is in this image?"}

        request, history, _ = self.build(payload)

        self.assertEqual(
            payload["_gemini_transient_images"],
            [{"mime": "image/png", "data": image}],
        )
        self.assertEqual(
            history[-1]["parts"][-1],
            {"inlineData": {"mimeType": "image/png", "data": image}},
        )
        self.assertEqual(request["contents"], history)

    def test_current_image_attachment_becomes_inline_data_in_request(self):
        image = "aGVsbG8="
        request, history, persistent = self.build({
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe this chart."},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{image}"},
                ],
            }],
        })

        self.assertFalse(persistent)
        self.assertEqual(history[-1]["parts"], [
            {"text": "Describe this chart."},
            {"inlineData": {"mimeType": "image/png", "data": image}},
        ])
        self.assertEqual(request["contents"], history)

    def test_tool_followup_resolves_call_name_and_saves_before_provider_payload(self):
        prior_history = [
            {"role": "user", "parts": [{"text": "Save this"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "save_checkin", "args": {}}}]},
        ]
        self.conversation_history.save(prior_history)
        self.set_value("gemini_call_names", json.dumps({"gemini_call-1": "save_checkin"}))
        original_request_payload = conversation.gemini_provider.request_payload
        observed = {}

        def inspect_saved_state(payload, **kwargs):
            observed["history"] = self.conversation_history.load()
            return original_request_payload(payload, **kwargs)

        with patch.object(
            conversation.gemini_provider,
            "request_payload",
            side_effect=inspect_saved_state,
        ):
            request, history, persistent = self.build({
                "conversation": "coach-dialogue",
                "input": [{
                    "type": "function_call_output",
                    "call_id": "gemini_call-1",
                    "output": '{"ok":true}',
                }],
            })

        response_part = {
            "functionResponse": {
                "name": "save_checkin",
                "response": {"ok": True},
            }
        }
        self.assertTrue(persistent)
        self.assertEqual(history[-1], {"role": "user", "parts": [response_part]})
        self.assertEqual(observed["history"], history)
        self.assertEqual(request["contents"], history)
        self.assertEqual(json.loads(self.get_value("gemini_conversation_history")), history)


class GeminiConversationResponseServiceTests(unittest.TestCase):
    def test_model_setting_is_read_only_when_request_model_is_missing(self):
        payload_service = Mock()
        payload_service.build.return_value = ({"contents": []}, [], False)
        normalization_service = Mock()
        normalization_service.normalize.side_effect = (
            lambda _payload, _history, _persistent, result: result
        )
        json_client = Mock()
        json_client.generate.return_value = {"path": "json"}
        stream_client = Mock()
        stream_client.stream.return_value = {"path": "stream"}
        settings_service = Mock()
        settings_service.selected_model.return_value = "configured-gemini"
        service = GeminiConversationResponseService(
            payload_service,
            normalization_service,
            json_client,
            stream_client,
            settings_service,
            default_thinking_level="medium",
            default_max_output_tokens=6000,
            json_media_type="application/json",
        )

        self.assertEqual(service.request({"model": "explicit-gemini"}), {"path": "json"})
        settings_service.selected_model.assert_not_called()
        json_client.generate.assert_called_once_with(
            "explicit-gemini",
            {"contents": []},
            operation="generate_content",
            cancel_event=None,
        )

        settings_service.reset_mock()
        json_client.reset_mock()
        self.assertEqual(service.request({}), {"path": "json"})
        settings_service.selected_model.assert_called_once_with("gemini")
        json_client.generate.assert_called_once_with(
            "configured-gemini",
            {"contents": []},
            operation="generate_content",
            cancel_event=None,
        )

        settings_service.reset_mock()
        self.assertEqual(service.stream({"model": "explicit-gemini"}, lambda _delta: None), {"path": "stream"})
        settings_service.selected_model.assert_not_called()
        stream_client.stream.assert_called_once()
        self.assertEqual(stream_client.stream.call_args.args[:2], ("explicit-gemini", {"contents": []}))

        settings_service.reset_mock()
        stream_client.reset_mock()
        self.assertEqual(service.stream({}, lambda _delta: None), {"path": "stream"})
        settings_service.selected_model.assert_called_once_with("gemini")
        self.assertEqual(stream_client.stream.call_args.args[:2], ("configured-gemini", {"contents": []}))


if __name__ == "__main__":
    unittest.main()
