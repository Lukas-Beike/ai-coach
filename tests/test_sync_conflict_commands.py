"""Focused tests for Coach sync-conflict command orchestration."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.db.manager import DatabaseManager
from backend.sync.conflict_commands import SyncConflictCommandService


class SyncConflictCommandServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "conflicts.sqlite",
            sqlite3,
            row_factory=sqlite3.Row,
        )
        self.addCleanup(self.database_manager.close)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY NOT NULL)"
            )
            db.execute(
                "INSERT INTO planned_units(local_id) VALUES (?)", ("planned-1",)
            )

        self.planned_units = Mock()
        self.competitions = Mock()
        self.job_queue = Mock()
        self.service = SyncConflictCommandService(
            self.database_manager,
            self.planned_units,
            self.competitions,
            self.job_queue,
        )

    def test_resolves_planned_unit_and_preserves_default_strategy(self) -> None:
        self.planned_units.resolve_conflict.return_value = {
            "status": "resolved",
            "planned_unit": {"id": "planned-1"},
        }

        result = self.service.resolve_local(" planned-1 ")

        self.planned_units.resolve_conflict.assert_called_once_with(
            "planned-1", "keep_local"
        )
        self.competitions.resolve_conflict.assert_not_called()
        self.assertEqual(
            result,
            {
                "ok": True,
                "status": "resolved",
                "planned_unit": {"id": "planned-1"},
            },
        )

    def test_resolves_competition_when_no_planned_unit_matches(self) -> None:
        self.competitions.resolve_conflict.return_value = {
            "status": "resolved",
            "competition": {"id": "competition-1"},
        }

        result = self.service.resolve_local("competition-1", " ADOPT_REMOTE ")

        self.competitions.resolve_conflict.assert_called_once_with(
            "competition-1", "adopt_remote"
        )
        self.planned_units.resolve_conflict.assert_not_called()
        self.assertEqual(result["competition"], {"id": "competition-1"})

    def test_missing_local_id_is_delegated_to_competition_owner(self) -> None:
        self.competitions.resolve_conflict.return_value = {"status": "resolved"}

        self.service.resolve_local("missing-local-id")

        self.competitions.resolve_conflict.assert_called_once_with(
            "missing-local-id", "keep_local"
        )

    def test_job_state_is_queue_owned(self) -> None:
        expected = {"id": "job-1", "provider": "garmin", "type": "refresh"}
        self.job_queue.state.return_value = expected

        result = self.service.job_state(" job-1 ")

        self.job_queue.state.assert_called_once_with("job-1")
        self.assertIs(result, expected)

    def test_preserves_push_and_refresh_job_classification(self) -> None:
        self.assertTrue(
            SyncConflictCommandService.is_push_job({"type": "plan_push"})
        )
        self.assertTrue(
            SyncConflictCommandService.is_push_job({"type": "competition_push"})
        )
        self.assertFalse(
            SyncConflictCommandService.is_push_job({"type": "refresh"})
        )

    def test_retry_uses_explicit_queue_retry_action_and_preserves_result(self) -> None:
        queued = {"id": "job-1", "status": "queued"}
        self.job_queue.resolve.return_value = queued

        result = self.service.retry_job(" job-1 ")

        self.job_queue.resolve.assert_called_once_with(
            "job-1", {"action": "retry"}
        )
        self.assertEqual(
            result,
            {"ok": True, "status": "queued", "job": queued},
        )


if __name__ == "__main__":
    unittest.main()
