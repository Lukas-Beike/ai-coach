"""Direct approval-boundary regression tests for adaptive Coach application."""

import threading
import unittest
from contextlib import contextmanager
from unittest.mock import Mock

from backend.coach.adaptive_apply import CoachAdaptiveApplyService
from backend.errors import AppError


class CoachAdaptiveApplyTests(unittest.TestCase):
    def setUp(self):
        self.preview = Mock()
        self.illness_sync = Mock()
        self.db = Mock()
        self.manager = Mock()

        @contextmanager
        def unit_of_work():
            yield self.db

        self.manager.unit_of_work.side_effect = unit_of_work
        self.service = CoachAdaptiveApplyService(
            self.preview, self.illness_sync, self.manager, threading.RLock()
        )
        self.intent = {
            "operation": "apply_adaptive_replan",
            "target_system": "local",
            "authorization_scope": ["adaptive_replan:adjustment-1"],
            "request": {"source_message_ids": [20]},
        }
        self.preview.latest_preview.return_value = {
            "id": "adjustment-1", "status": "preview", "published_message_id": 10,
        }
        self.db.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"id": 20})),
            Mock(fetchone=Mock(return_value={"id": 10})),
        ]
        self.illness_sync.apply.return_value = {"updated": 1}

    def test_later_turn_apply_succeeds_without_remote_sync(self):
        self.assertEqual(
            self.service.apply({"adjustment_id": "adjustment-1"}, self.intent, "turn-2"),
            {"ok": True, "updated": 1},
        )
        self.illness_sync.apply.assert_called_once_with(
            "adjustment-1", sync_illness_to_intervals=False
        )

    def test_same_turn_or_missing_provenance_cannot_apply(self):
        self.db.execute.side_effect = [
            Mock(fetchone=Mock(return_value={"id": 10})),
            Mock(fetchone=Mock(return_value={"id": 10})),
        ]
        with self.assertRaises(AppError) as raised:
            self.service.apply({"adjustment_id": "adjustment-1"}, self.intent, "turn-1")
        self.assertEqual(raised.exception.reason, "adaptive_approval_required")
        self.illness_sync.apply.assert_not_called()

    def test_remote_sync_requires_target_and_explicit_scope_before_db_read(self):
        with self.assertRaises(AppError) as raised:
            self.service.apply(
                {"adjustment_id": "adjustment-1", "sync_illness_to_intervals": True},
                self.intent, "turn-2",
            )
        self.assertEqual(raised.exception.reason, "intent_scope_denied")
        self.preview.latest_preview.assert_not_called()
        self.db.execute.assert_not_called()
        self.illness_sync.apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
