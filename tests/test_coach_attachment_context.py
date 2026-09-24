from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.coach.conversation import CoachAttachmentContextService
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema


class CoachAttachmentContextServiceTests(unittest.TestCase):
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
            self.database_path, sqlite3, row_factory=row_factory, persist_connections=False
        )
        self.service = CoachAttachmentContextService(self.database_manager)

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temp_dir.cleanup()

    def _message(self, message_id: int, attachments: list[dict[str, object]]) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(id, role, content, created_at, attachments) VALUES (?, 'user', '', '', ?)",
                (message_id, json.dumps(attachments)),
            )

    def _command(self, command_id: str, receipt: dict[str, object]) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands(id, client_turn_id, intent, target_system, status, receipt, created_at, updated_at) "
                "VALUES (?, ?, '{}', 'none', 'completed', ?, '', '')",
                (command_id, command_id, json.dumps(receipt)),
            )

    def test_loads_current_attachments_and_detects_prior_openai_attachments(self) -> None:
        attachment = {"type": "image", "name": "today.png", "data": "raw"}
        self._message(1, [{"type": "gpx", "name": "route.gpx"}])
        self._message(2, [attachment])
        self._command("prior", {"ai_provider": "openai", "user_message_id": 1})

        attachments, has_prior = self.service.load_for_receipt({"user_message_id": 2})

        self.assertEqual(attachments, [attachment])
        self.assertTrue(has_prior)

    def test_excludes_non_openai_receipts_from_prior_attachment_detection(self) -> None:
        self._message(1, [{"type": "fit", "name": "ride.fit"}])
        self._message(2, [])
        self._command("prior", {"ai_provider": "gemini", "user_message_id": 1})

        _, has_prior = self.service.load_for_receipt({"user_message_id": 2})

        self.assertFalse(has_prior)

    def test_adds_only_attachment_metadata_and_gpx_fit_summaries(self) -> None:
        gpx = {"type": "gpx", "name": "route.gpx", "summary": {"distance_km": 12.3}, "data": "raw-gpx"}
        fit = {"type": "fit", "name": "ride.fit", "summary": {"duration_s": 3600}, "data": "raw-fit"}
        image = {"type": "image", "name": "photo.jpg", "summary": "ignored", "data": "raw-image"}
        self._message(1, [gpx, fit, image])
        context = {"messages": [{"id": 1}, {"id": 999}]}

        self.service.add_evidence(context)

        self.assertEqual(context["attachment_evidence"], [
            {"source_message_id": 1, "type": "gpx", "untrusted_attachment_name": "route.gpx", "gpx": gpx["summary"]},
            {"source_message_id": 1, "type": "fit", "untrusted_attachment_name": "ride.fit", "fit": fit["summary"]},
            {"source_message_id": 1, "type": "image", "untrusted_attachment_name": "photo.jpg"},
        ])
        self.assertNotIn("data", json.dumps(context["attachment_evidence"]))

    def test_missing_current_message_returns_empty_attachments(self) -> None:
        self.assertEqual(self.service.load_for_receipt({"user_message_id": 404}), ([], False))

    def test_malformed_attachment_json_and_item_types_propagate(self) -> None:
        self._message(1, [])
        with self.database_manager.unit_of_work() as db:
            db.execute("UPDATE messages SET attachments = ? WHERE id = 1", ("{",))

        with self.assertRaises(json.JSONDecodeError):
            self.service.load_for_receipt({"user_message_id": 1})
        with self.assertRaises(json.JSONDecodeError):
            self.service.add_evidence({"messages": [{"id": 1}]})

        with self.database_manager.unit_of_work() as db:
            db.execute("UPDATE messages SET attachments = ? WHERE id = 1", ('["invalid-item"]',))
        with self.assertRaises(AttributeError):
            self.service.add_evidence({"messages": [{"id": 1}]})


if __name__ == "__main__":
    unittest.main()
