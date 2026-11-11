"""Focused tests for Coach sync-conflict command orchestration."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.sync.conflict_commands import SyncConflictCommandService


class SyncConflictCommandServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.competitions = Mock()
        self.job_queue = Mock()
        self.service = SyncConflictCommandService(self.competitions, self.job_queue)

    def test_resolves_competition_with_normalized_strategy(self) -> None:
        self.competitions.resolve_conflict.return_value = {
            "status": "resolved",
            "competition": {"id": "competition-1"},
        }

        result = self.service.resolve_local(" competition-1 ", " ADOPT_REMOTE ")

        self.competitions.resolve_conflict.assert_called_once_with(
            "competition-1", "adopt_remote"
        )
        self.assertEqual(
            result,
            {"ok": True, "status": "resolved", "competition": {"id": "competition-1"}},
        )

    def test_missing_strategy_keeps_local(self) -> None:
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
        self.assertTrue(SyncConflictCommandService.is_push_job({"type": "plan_push"}))
        self.assertTrue(
            SyncConflictCommandService.is_push_job({"type": "competition_push"})
        )
        self.assertTrue(
            SyncConflictCommandService.is_push_job({"type": "nutrition_sync"})
        )
        self.assertFalse(SyncConflictCommandService.is_push_job({"type": "refresh"}))

    def test_retry_uses_explicit_queue_retry_action_and_preserves_result(self) -> None:
        queued = {"id": "job-1", "status": "queued"}
        self.job_queue.resolve.return_value = queued

        result = self.service.retry_job(" job-1 ")

        self.job_queue.resolve.assert_called_once_with("job-1", {"action": "retry"})
        self.assertEqual(
            result,
            {"ok": True, "status": "queued", "job": queued},
        )


if __name__ == "__main__":
    unittest.main()
