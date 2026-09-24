"""Tests for session-owned Coach action proposal creation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from backend.coach.proposals import (
    COACH_ACTION_TTL_SECONDS,
    CoachProposalCreationService,
    coach_action_hash,
)
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError


class CoachProposalCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "coach-proposals.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self.sync_state_repository = Mock()

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temporary_directory.cleanup()

    def _service(self, **overrides: object) -> CoachProposalCreationService:
        options = {
            "now": lambda: 100.0,
            "utc_now": lambda: "2026-09-23T10:11:12+00:00",
            "uuid_factory": lambda: UUID("abc12345-6789-4abc-8def-0123456789ab"),
        }
        options.update(overrides)
        return CoachProposalCreationService(
            self.database_manager,
            self.sync_state_repository,
            **options,
        )

    def _undo(self) -> dict[str, object]:
        return {
            "action_type": "undo_change",
            "target_system": "local",
            "object_ids": ["change-1"],
            "diff": [{"type": "restore", "label": "Änderung"}],
            "payload": {"change_id": "change-1", "secret": "private"},
        }

    @staticmethod
    def _duplicate_snapshot(synced_at: str) -> dict[str, object]:
        return {
            "synced_at": synced_at,
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "wahoo-1",
                        "source": "Wahoo",
                        "type": "Ride",
                        "start_date_local": "2026-08-29T07:00:00",
                        "moving_time": 7200,
                        "distance": 60000,
                    },
                    {
                        "activityId": "garmin-1",
                        "source": "Garmin",
                        "type": "Ride",
                        "start_date_local": "2026-08-29T07:05:00",
                        "moving_time": 7160,
                        "distance": 59800,
                    },
                ]
            },
        }

    @staticmethod
    def _delete_duplicate(synced_at: str) -> dict[str, object]:
        return {
            "action_type": "delete_duplicate_intervals_activity",
            "target_system": "intervals",
            "object_ids": {
                "keep_activity_id": "wahoo-1",
                "delete_activity_id": "garmin-1",
            },
            "diff": [{"type": "delete", "id": "garmin-1", "name": "Garmin"}],
            "payload": {
                "canonical_id": "wahoo-1",
                "duplicate_id": "garmin-1",
                "snapshot_synced_at": synced_at,
            },
        }

    def _rows(self) -> list[dict[str, object]]:
        with self.database_manager.reader() as db:
            return db.execute("SELECT * FROM coach_action_proposals").fetchall()

    def test_undo_creation_persists_session_ttl_hash_and_safe_view(self) -> None:
        payload = self._undo()["payload"]
        result = self._service().create(self._undo(), "session-csrf-hash")

        self.assertEqual(COACH_ACTION_TTL_SECONDS, 600)
        self.assertEqual(result["status"], "preview")
        self.assertEqual(
            result["proposed_action"],
            {
                "id": "abc12345-6789-4abc-8def-0123456789ab",
                "action_type": "undo_change",
                "target_system": "local",
                "object_ids": ["change-1"],
                "diff": [{"type": "restore", "label": "Änderung"}],
                "payload_hash": coach_action_hash(payload),
                "expires_at": 100 + COACH_ACTION_TTL_SECONDS,
                "status": "preview",
            },
        )
        self.assertNotIn("payload", result["proposed_action"])
        row = self._rows()[0]
        self.assertEqual(row["session_csrf_hash"], "session-csrf-hash")
        expected_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(row["payload_hash"], expected_hash)
        self.assertEqual(row["payload"], '{"change_id":"change-1","secret":"private"}')
        self.assertEqual(row["diff"], '[{"type":"restore","label":"Änderung"}]')
        self.assertEqual(row["created_at"], "2026-09-23T10:11:12+00:00")
        self.assertNotIn("private", repr(result))
        self.sync_state_repository.latest_snapshot.assert_not_called()

    def test_distinct_session_keys_own_distinct_proposals(self) -> None:
        self._service().create(self._undo(), "session-a")
        other_id = UUID("def12345-6789-4abc-8def-0123456789ab")
        self._service(uuid_factory=lambda: other_id).create(self._undo(), "session-b")

        self.assertEqual(
            {row["session_csrf_hash"] for row in self._rows()}, {"session-a", "session-b"}
        )

    def test_duplicate_delete_validates_against_fresh_snapshot_before_persisting(self) -> None:
        current_time = "2026-08-29T10:00:00+00:00"
        self.sync_state_repository.latest_snapshot.return_value = self._duplicate_snapshot(
            current_time
        )
        result = self._service().create(self._delete_duplicate(current_time), "session")

        self.assertEqual(
            result["proposed_action"]["action_type"],
            "delete_duplicate_intervals_activity",
        )
        self.assertEqual(len(self._rows()), 1)
        self.sync_state_repository.latest_snapshot.assert_called_once_with()

    def test_stale_duplicate_snapshot_rejects_before_id_clock_or_insert(self) -> None:
        self.sync_state_repository.latest_snapshot.return_value = self._duplicate_snapshot(
            "2026-08-29T10:01:00+00:00"
        )
        uuid_factory = Mock(return_value=UUID("abc12345-6789-4abc-8def-0123456789ab"))
        now = Mock(return_value=100.0)
        utc_now = Mock(return_value="now")

        with self.assertRaises(AppError) as error:
            self._service(uuid_factory=uuid_factory, now=now, utc_now=utc_now).create(
                self._delete_duplicate("2026-08-29T10:00:00+00:00"), "session"
            )

        self.assertEqual(error.exception.status, 409)
        uuid_factory.assert_not_called()
        now.assert_not_called()
        utc_now.assert_not_called()
        self.assertEqual(self._rows(), [])

    def test_invalid_inputs_reject_before_snapshot_or_insert(self) -> None:
        invalid_values = [
            None,
            {},
            {**self._undo(), "diff": []},
            {**self._undo(), "target_system": "intervals"},
        ]
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(AppError):
                    self._service().create(values, "session")

        self.sync_state_repository.latest_snapshot.assert_not_called()
        self.assertEqual(self._rows(), [])

    def test_database_failure_rolls_back_insert(self) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER reject_proposal BEFORE INSERT ON coach_action_proposals "
                "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self._service().create(self._undo(), "session")

        self.assertEqual(self._rows(), [])


if __name__ == "__main__":
    unittest.main()
