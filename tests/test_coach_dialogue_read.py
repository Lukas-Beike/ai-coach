"""Direct service-contract tests for local Coach dialogue reads."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, tzinfo
from pathlib import Path

from backend.athlete.profile import ProfileService
from backend.coach.conversation import CoachMessageService
from backend.coach.dialogue import CoachDialogueReadService
from backend.db import DatabaseManager, row_factory
from backend.db.repositories import ChatRepository, KeyValueRepository, ProfileRepository
from backend.db.schema import initialize_schema
from backend.runtime.events import StateEventBuffer


NOW = "2026-09-23T08:00:00+00:00"


class ReadOnlyDatabaseManager:
    def __init__(self, manager):
        self._manager = manager

    def reader(self):
        return self._manager.reader()

    def unit_of_work(self):
        raise AssertionError("dialogue read service attempted a write transaction")


class CoachDialogueReadServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temp_dir.name) / "coach.sqlite",
            sqlite3,
            row_factory=row_factory,
            persist_connections=False,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.chat_repository = ChatRepository(lambda: NOW)
        self.messages = CoachMessageService(
            self.database_manager, self.chat_repository, StateEventBuffer()
        )
        self.profile = ProfileService(
            self.database_manager,
            ProfileRepository(self.key_values),
            self.key_values,
        )

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temp_dir.cleanup()

    def service(self, clock=None) -> CoachDialogueReadService:
        return CoachDialogueReadService(
            self.database_manager,
            self.messages,
            self.key_values,
            self.profile,
            local_clock=clock or datetime.now,
        )

    def add_message(self, role: str, content: str, turn_id: str | None = None):
        with self.database_manager.unit_of_work() as db:
            return self.chat_repository.add(
                db, role, content, client_turn_id=turn_id
            )

    def test_context_returns_current_id_pending_persisted_message_and_local_date(self):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, "profile", '{"timezone":"Asia/Tokyo"}')
        messages = [
            self.add_message("user", f"message {index}", "current" if index == 25 else None)
            for index in range(26)
        ]
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(
                db,
                "coach_pending_request",
                json.dumps({"source_message_ids": [messages[0]["id"], 999_999]}),
            )

        result = self.service(
            lambda timezone: datetime(2026, 9, 23, 0, 30, tzinfo=timezone)
        ).context("current")

        self.assertEqual(result["timezone"], "Asia/Tokyo")
        self.assertEqual(result["local_date"], "2026-09-23")
        self.assertEqual(result["current_user_message_id"], messages[25]["id"])
        self.assertEqual(
            [item["id"] for item in result["messages"]],
            [messages[0]["id"], *[item["id"] for item in messages[2:]]],
        )
        self.assertEqual(result["pending_request"]["source_message_ids"], [messages[0]["id"], 999_999])

    def test_context_limits_messages_and_projects_only_bounded_fields(self):
        long_message = self.add_message("user", "x" * 4500, "long-turn")

        result = self.service().context("absent-turn")

        self.assertIsNone(result["current_user_message_id"])
        self.assertEqual(len(result["messages"]), 1)
        self.assertEqual(result["messages"][0], {
            "id": long_message["id"], "role": "user", "content": "x" * 4000,
        })

    def test_context_propagates_invalid_persisted_pending_json(self):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, "coach_pending_request", "{")

        with self.assertRaises(json.JSONDecodeError):
            self.service().context("missing")

    def test_context_propagates_truthy_non_object_pending_json(self):
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, "coach_pending_request", '["source"]')

        with self.assertRaises(AttributeError):
            self.service().context("missing")

    def test_context_preserves_falsy_pending_value_without_extra_messages(self):
        message = self.add_message("user", "recent")
        with self.database_manager.unit_of_work() as db:
            self.key_values.set(db, "coach_pending_request", "[]")

        result = self.service().context("missing")

        self.assertEqual(result["pending_request"], [])
        self.assertEqual([item["id"] for item in result["messages"]], [message["id"]])

    def test_reads_use_reader_connections_only(self):
        self.add_message("user", "read-only")
        read_only_manager = ReadOnlyDatabaseManager(self.database_manager)
        message_service = CoachMessageService(
            read_only_manager,
            self.chat_repository,
            StateEventBuffer(),
        )
        service = CoachDialogueReadService(
            read_only_manager,
            message_service,
            self.key_values,
            self.profile,
        )

        self.assertEqual(service.context("missing")["messages"][0]["content"], "read-only")
        self.assertEqual(service.artifact_refs(), [])

    def test_context_bounds_confirmed_receipts_and_excludes_unbacked_commands(self):
        for index in range(13):
            turn_id = f"turn-{index}"
            self.add_message("user", turn_id, turn_id)
            receipt = {
                "status": "completed",
                "sync_job_ids": [f"job-{item}" for item in range(45)],
                "command_receipts": [
                    {
                        "tool": f"tool-{item}",
                        "result": {"ok": True, "status": "done", "reason": "ok", "artifact_id": "artifact"},
                        "request": {"scope": list(range(45))},
                    }
                    for item in range(45)
                ],
            }
            with self.database_manager.unit_of_work() as db:
                db.execute(
                    "INSERT INTO coach_commands "
                    "(id, client_turn_id, intent, target_system, status, receipt, created_at, updated_at) "
                    "VALUES (?, ?, '', '', 'completed', ?, ?, ?)",
                    (turn_id, turn_id, json.dumps(receipt), f"2026-09-23T00:{index:02d}:00Z", NOW),
                )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_commands "
                "(id, client_turn_id, intent, target_system, status, receipt, created_at, updated_at) "
                "VALUES ('orphan', 'orphan', '', '', 'completed', '{}', ?, ?)",
                (NOW, NOW),
            )

        results = self.service().context("missing")['confirmed_results']

        self.assertEqual(len(results), 12)
        self.assertEqual(results[0]["client_turn_id"], "turn-12")
        self.assertEqual(len(results[0]["sync_job_ids"]), 40)
        self.assertEqual(len(results[0]["steps"]), 40)
        self.assertEqual(len(results[0]["steps"][0]["scope"]), 40)
        self.assertTrue(results[0]["steps"][0]["scope_truncated"])
        self.assertEqual(results[0]["steps"][0]["artifact_id"], "artifact")
        self.assertNotIn("orphan", [item["client_turn_id"] for item in results])

    def test_artifact_refs_require_chat_evidence_and_are_limited_to_newest_20(self):
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_plan_artifacts "
                "(id, client_turn_id, base_revision, status, payload, created_at, updated_at) "
                "VALUES ('orphan', 'orphan-turn', 0, 'draft', '{}', ?, ?)",
                (NOW, NOW),
            )
        for index in range(21):
            turn_id = f"draft-{index:02d}"
            user = self.add_message("user", "evidence", turn_id)
            with self.database_manager.unit_of_work() as db:
                db.execute(
                    "INSERT INTO coach_plan_artifacts "
                    "(id, client_turn_id, base_revision, status, payload, created_at, updated_at) "
                    "VALUES (?, ?, 3, 'draft', ?, ?, ?)",
                    (turn_id, turn_id, '{"plan_name":"Synthetic plan"}', f"2026-09-23T00:{index:02d}:00Z", NOW),
                )
                if index == 20:
                    db.execute(
                        "UPDATE messages SET role='assistant' WHERE id=?", (user["id"],)
                    )

        refs = self.service().artifact_refs()

        self.assertEqual(len(refs), 20)
        self.assertEqual(refs[0]["id"], "draft-20")
        self.assertNotIn("orphan", [item["id"] for item in refs])
        oldest_included = next(item for item in refs if item["id"] == "draft-01")
        self.assertEqual(oldest_included["source_message_id"], self.message_id("draft-01"))
        self.assertNotIn("draft-00", [item["id"] for item in refs])
        self.assertIsNone(refs[0]["source_message_id"])
        self.assertEqual(oldest_included["name"], "Synthetic plan")
        self.assertEqual(set(oldest_included), {
            "id", "status", "base_revision", "created_at", "source_message_id", "name",
        })

    def message_id(self, turn_id: str) -> int:
        with self.database_manager.reader() as db:
            return db.execute(
                "SELECT id FROM messages WHERE client_turn_id=?", (turn_id,)
            ).fetchone()["id"]


if __name__ == "__main__":
    unittest.main()
