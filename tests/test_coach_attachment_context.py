from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

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
            self.database_path,
            sqlite3,
            row_factory=row_factory,
            persist_connections=False,
        )
        self.service = CoachAttachmentContextService(self.database_manager)

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temp_dir.cleanup()

    def _message(self, message_id: int, attachments: list[dict[str, Any]]) -> None:
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

    def test_loads_current_attachments_and_detects_prior_openai_attachments(
        self,
    ) -> None:
        attachment = {"type": "image", "name": "today.png", "data": "raw"}
        self._message(1, [{"type": "gpx", "name": "route.gpx"}])
        self._message(2, [attachment])
        self._command(
            "prior",
            {
                "ai_provider": "openai",
                "user_message_id": 1,
                "openai_response_id": "resp-1",
            },
        )

        attachments, has_prior, within_window = self.service.load_for_receipt(
            {"user_message_id": 2}
        )

        self.assertEqual(attachments, [attachment])
        self.assertTrue(has_prior)
        self.assertTrue(within_window)

    def test_excludes_non_openai_receipts_from_prior_attachment_detection(self) -> None:
        self._message(1, [{"type": "fit", "name": "ride.fit"}])
        self._message(2, [])
        self._command("prior", {"ai_provider": "unknown", "user_message_id": 1})

        _, has_prior, within_window = self.service.load_for_receipt(
            {"user_message_id": 2}
        )

        self.assertFalse(has_prior)
        self.assertFalse(within_window)

    def test_retention_window_counts_user_messages_after_latest_attachment_turn(
        self,
    ) -> None:
        self._message(1, [{"type": "image", "name": "old.png"}])
        self._command(
            "prior",
            {
                "ai_provider": "openai",
                "user_message_id": 1,
                "openai_response_id": "resp-1",
            },
        )
        for message_id in (2, 3, 4, 5):
            self._message(message_id, [])
        # The newest message is the attachment turn itself and counts too.
        self._message(6, [{"type": "image", "name": "new.png"}])
        self._command(
            "newer",
            {
                "ai_provider": "openai",
                "user_message_id": 6,
                "openai_response_id": "resp-6",
            },
        )
        self._message(7, [])
        self._message(8, [])
        self._message(9, [])
        self._message(10, [])

        # Latest earlier attachment turn is 6: messages 7, 8, 9 are in window.
        self.assertTrue(self.service.load_for_receipt({"user_message_id": 9})[2])
        # Message 10 is the fourth user message after the attachment turn.
        self.assertFalse(self.service.load_for_receipt({"user_message_id": 10})[2])

    def test_retention_window_boundary_at_one_and_three_and_outside_at_four(
        self,
    ) -> None:
        self._message(1, [{"type": "image", "name": "old.png"}])
        self._command(
            "prior",
            {
                "ai_provider": "openai",
                "user_message_id": 1,
                "openai_response_id": "resp-1",
            },
        )
        for message_id in (2, 3, 4, 5):
            self._message(message_id, [])

        self.assertTrue(self.service.load_for_receipt({"user_message_id": 2})[2])
        self.assertTrue(self.service.load_for_receipt({"user_message_id": 4})[2])
        self.assertFalse(self.service.load_for_receipt({"user_message_id": 5})[2])
        self.assertTrue(self.service.load_for_receipt({"user_message_id": 5})[1])

    def test_retention_window_ignores_attachment_turns_that_never_reached_openai(
        self,
    ) -> None:
        self._message(1, [{"type": "image", "name": "failed.png"}])
        self._command("failed", {"ai_provider": "openai", "user_message_id": 1})
        self._message(2, [])

        self.assertEqual(
            self.service.load_for_receipt({"user_message_id": 2}), ([], False, False)
        )

    def test_retention_window_ignores_other_provider_attachment_turns(self) -> None:
        self._message(1, [{"type": "image", "name": "other.png"}])
        self._message(2, [])
        self._command("other", {"ai_provider": "unknown", "user_message_id": 1})

        self.assertEqual(
            self.service.load_for_receipt({"user_message_id": 2}), ([], False, False)
        )

    def test_prior_detection_skips_malformed_later_and_non_integer_receipts(
        self,
    ) -> None:
        self._message(1, [{"type": "image", "name": "old.png"}])
        self._message(2, [])
        self._message(3, [{"type": "image", "name": "later.png"}])
        self._command(
            "later",
            {
                "ai_provider": "openai",
                "user_message_id": 3,
                "openai_response_id": "resp-3",
            },
        )
        self._command("text-id", {"ai_provider": "openai", "user_message_id": "1"})
        self._command("no-id", {"ai_provider": "openai"})
        self._command("list", {"ai_provider": "openai"})
        with self.database_manager.unit_of_work() as db:
            db.execute("UPDATE coach_commands SET receipt='{' WHERE id='no-id'")
            db.execute("UPDATE coach_commands SET receipt='[1]' WHERE id='list'")

        _, has_prior, _ = self.service.load_for_receipt({"user_message_id": 2})

        self.assertFalse(has_prior)
        self._command(
            "prior",
            {
                "ai_provider": "openai",
                "user_message_id": 1,
                "openai_response_id": "resp-1",
            },
        )
        self.assertTrue(self.service.load_for_receipt({"user_message_id": 2})[1])

    def test_prior_detection_ignores_a_prior_message_without_attachments(
        self,
    ) -> None:
        self._message(1, [])
        self._message(2, [])
        self._command(
            "prior",
            {
                "ai_provider": "openai",
                "user_message_id": 1,
                "openai_response_id": "resp-1",
            },
        )

        self.assertEqual(
            self.service.load_for_receipt({"user_message_id": 2}), ([], False, False)
        )

    def test_adds_only_attachment_metadata_and_gpx_fit_summaries(self) -> None:
        gpx = {
            "type": "gpx",
            "name": "route.gpx",
            "summary": {"distance_km": 12.3},
            "data": "raw-gpx",
        }
        fit = {
            "type": "fit",
            "name": "ride.fit",
            "summary": {"duration_s": 3600},
            "data": "raw-fit",
        }
        image = {
            "type": "image",
            "name": "photo.jpg",
            "summary": "ignored",
            "data": "raw-image",
        }
        self._message(1, [gpx, fit, image])
        context = {"messages": [{"id": 1}, {"id": 999}]}

        self.service.add_evidence(context)

        self.assertEqual(
            context["attachment_evidence"],
            [
                {
                    "source_message_id": 1,
                    "type": "gpx",
                    "untrusted_attachment_name": "route.gpx",
                    "gpx": gpx["summary"],
                },
                {
                    "source_message_id": 1,
                    "type": "fit",
                    "untrusted_attachment_name": "ride.fit",
                    "fit": fit["summary"],
                },
                {
                    "source_message_id": 1,
                    "type": "image",
                    "untrusted_attachment_name": "photo.jpg",
                },
            ],
        )
        self.assertNotIn("data", json.dumps(context["attachment_evidence"]))

    def test_missing_current_message_returns_empty_attachments(self) -> None:
        self.assertEqual(
            self.service.load_for_receipt({"user_message_id": 404}), ([], False, False)
        )

    def test_malformed_attachment_json_and_item_types_propagate(self) -> None:
        self._message(1, [])
        with self.database_manager.unit_of_work() as db:
            db.execute("UPDATE messages SET attachments = ? WHERE id = 1", ("{",))

        self.assertEqual(
            self.service.load_for_receipt({"user_message_id": 1}), ([], False, False)
        )
        context = {"messages": [{"id": 1}]}
        self.service.add_evidence(context)
        self.assertEqual(context["attachment_evidence"], [])

        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE messages SET attachments = ? WHERE id = 1",
                ('["invalid-item"]',),
            )
        with self.assertRaises(AttributeError):
            self.service.add_evidence({"messages": [{"id": 1}]})


if __name__ == "__main__":
    unittest.main()
