"""Session and restart contracts for Coach cancellation orchestration."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import Mock

from backend.coach.cancellation import CoachCancellationService
from backend.coach.streams import ChatStreamRegistry
from backend.errors import AppError


class CoachCancellationServiceTests(unittest.TestCase):
    def setUp(self):
        self.submissions = Mock()
        self.jobs = Mock()
        self.streams = ChatStreamRegistry()
        self.service = CoachCancellationService(
            self.submissions, self.jobs, self.streams
        )

    def test_attached_cancel_closes_provider_and_rejects_wrong_operation(self):
        operation_id, event = self.streams.register("session")
        response = Mock()
        event._provider_response = response
        try:
            with self.assertRaises(AppError) as raised:
                self.service.cancel("session", "wrong")
            self.assertEqual(raised.exception.status, 409)
            self.assertFalse(event.is_set())
            self.assertEqual(
                self.service.cancel("session", operation_id),
                {"status": "cancelling", "operation_id": operation_id},
            )
            self.assertTrue(event.is_set())
            response.close.assert_called_once_with()
            self.submissions.active.assert_not_called()
        finally:
            self.streams.unregister("session", operation_id)

    def test_background_cancel_persists_before_signalling_and_does_not_recreate_event(self):
        operation_id = "durable-operation"
        self.submissions.active.return_value = {
            "client_turn_id": "turn-1",
            "receipt": {"operation_id": operation_id},
        }
        self.jobs.merge_receipt.side_effect = lambda *_: self.assertFalse(
            event.is_set()
        )
        event = threading.Event()
        response = Mock()
        event._provider_response = response
        self.streams.set_background_event(operation_id, event)

        self.assertEqual(
            self.service.cancel("session", operation_id),
            {"status": "cancelling", "operation_id": operation_id},
        )
        self.submissions.active.assert_called_once_with("session", operation_id)
        self.jobs.merge_receipt.assert_called_once_with(
            "turn-1", {"cancel_requested": True, "phase": "cancelling"}
        )
        self.assertTrue(event.is_set())
        response.close.assert_called_once_with()

        self.streams.clear_state()
        self.jobs.reset_mock()
        self.jobs.merge_receipt.side_effect = None
        self.assertEqual(self.service.cancel("session", operation_id)["status"], "cancelling")
        self.jobs.merge_receipt.assert_called_once()
        self.assertIsNone(self.streams.get_background_event(operation_id))

    def test_no_active_job_does_not_create_or_write_cancel_state(self):
        self.submissions.active.return_value = None
        self.assertEqual(self.service.cancel("session"), {"status": "not_running"})
        self.submissions.active.assert_called_once_with("session", None)
        self.jobs.merge_receipt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
