"""Tests for the session-scoped Coach proposal read service."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.coach.proposals import (
    CoachProposalReadService,
    coach_action_hash,
    coach_action_view,
    prune_expired_coach_proposals,
)


class CoachProposalReadServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "coach-proposals.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def _insert(
        self,
        proposal_id: str,
        *,
        session: str = "session-a",
        status: str = "preview",
        expires_at: float = 200.0,
        created_at: str = "2026-09-23T00:00:00Z",
    ) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO coach_action_proposals "
                "(id, session_csrf_hash, action_type, target_system, object_ids, "
                "diff, payload, payload_hash, action_token_hash, status, expires_at, "
                "created_at, used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal_id,
                    session,
                    "undo_change",
                    "local",
                    '["object-1"]',
                    '{"safe":"diff"}',
                    '{"private":"payload-secret"}',
                    "fake-payload-hash",
                    "private-action-token-hash",
                    status,
                    expires_at,
                    created_at,
                    None,
                ),
            )

    def test_empty_session_returns_without_touching_database(self) -> None:
        manager = Mock()

        self.assertEqual(CoachProposalReadService(manager).current(""), [])
        manager.unit_of_work.assert_not_called()

    def test_current_is_session_scoped_and_excludes_expired_and_consumed(self) -> None:
        self._insert("mine", expires_at=101)
        self._insert("theirs", session="session-b")
        self._insert("expired", expires_at=100)
        self._insert("consumed", status="consumed")
        self._insert("cancelled", status="cancelled")

        proposals = CoachProposalReadService(
            self.database_manager, now=lambda: 100
        ).current("session-a")

        self.assertEqual([proposal["id"] for proposal in proposals], ["mine"])
        with self.database_manager.reader() as db:
            expired = db.execute(
                "SELECT id FROM coach_action_proposals WHERE id='expired'"
            ).fetchone()
        self.assertIsNone(expired)

    def test_prune_and_select_use_separate_clock_reads(self) -> None:
        self._insert("still-stored-but-no-longer-current", expires_at=150)
        now = Mock(side_effect=[100, 200])

        proposals = CoachProposalReadService(
            self.database_manager, now=now
        ).current("session-a")

        self.assertEqual(proposals, [])
        self.assertEqual(now.call_count, 2)
        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT id FROM coach_action_proposals "
                "WHERE id='still-stored-but-no-longer-current'"
            ).fetchone()
        self.assertIsNotNone(row)

    def test_returns_newest_30_and_never_exposes_payload_or_action_token(self) -> None:
        for index in range(35):
            self._insert(
                f"proposal-{index:02d}",
                status="ready" if index % 2 else "preview",
                created_at=f"2026-09-23T00:{index:02d}:00Z",
            )

        proposals = CoachProposalReadService(
            self.database_manager, now=lambda: 100
        ).current("session-a")

        self.assertEqual(len(proposals), 30)
        self.assertEqual(proposals[0]["id"], "proposal-34")
        self.assertEqual(proposals[-1]["id"], "proposal-05")
        self.assertEqual(
            set(proposals[0]),
            {
                "id",
                "action_type",
                "target_system",
                "object_ids",
                "diff",
                "payload_hash",
                "expires_at",
                "status",
            },
        )
        self.assertNotIn("payload", proposals[0])
        self.assertNotIn("action_token_hash", proposals[0])
        self.assertNotIn("payload-secret", repr(proposals))

    def test_action_hash_preserves_canonical_json_semantics(self) -> None:
        payload = {"z": "ä", "a": [1, 2]}
        expected = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(coach_action_hash(payload), expected)
        self.assertEqual(
            coach_action_hash({"a": [1, 2], "z": "ä"}), expected
        )
        self.assertEqual(
            coach_action_hash({"value": date(2026, 9, 23)}),
            coach_action_hash({"value": "2026-09-23"}),
        )

    def test_action_view_and_prune_helpers_preserve_field_and_boundary_semantics(self) -> None:
        row = {
            "id": "visible",
            "action_type": "undo_change",
            "target_system": "local",
            "object_ids": '["object-1"]',
            "diff": '{"safe":"diff"}',
            "payload": '{"private":"payload-secret"}',
            "payload_hash": "fake-payload-hash",
            "expires_at": 200.0,
            "status": "preview",
        }
        self.assertEqual(
            coach_action_view(row),
            {
                "id": "visible",
                "action_type": "undo_change",
                "target_system": "local",
                "object_ids": ["object-1"],
                "diff": {"safe": "diff"},
                "payload_hash": "fake-payload-hash",
                "expires_at": 200.0,
                "status": "preview",
            },
        )
        self._insert("boundary-expired", expires_at=100)
        self._insert("boundary-live", expires_at=101)
        with self.database_manager.unit_of_work() as db:
            self.assertEqual(prune_expired_coach_proposals(db, 100), 1)
        with self.database_manager.reader() as db:
            live = db.execute(
                "SELECT id FROM coach_action_proposals WHERE id='boundary-live'"
            ).fetchone()
        self.assertIsNotNone(live)


if __name__ == "__main__":
    unittest.main()
