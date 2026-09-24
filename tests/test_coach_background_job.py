"""Direct boundaries for durable Coach job execution and stream publication."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import Mock

from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.streams import ChatStreamRegistry
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class CoachBackgroundJobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = Mock()
        self.jobs.cancel_requested.return_value = False
        self.jobs.message.return_value = "synthetic message"
        self.chat = Mock()
        self.chat.run.return_value = {"status": "completed", "message": {"content": "synthetic"}}
        self.sessions = Mock()
        self.sessions.restore_coach_session_csrf_hash.return_value = "synthetic-session"
        self.streams = ChatStreamRegistry()
        self.morning = Mock()
        self.completion = Mock()
        self.failures = Mock()
        self.gate = MaintenanceGate()
        self.redactor = Mock()
        self.redactor.redact_text.return_value = "safe message"
        self.runner = CoachBackgroundJobRunner(
            self.jobs, lambda: self.chat, lambda: self.sessions, self.streams,
            lambda: self.morning, lambda: self.completion, lambda: self.failures,
            self.gate, self.redactor,
            logging.getLogger("test.coach.background-job"),
        )

    def job(self, operation_id: str, **receipt: object) -> dict[str, object]:
        return {
            "_maintenance_generation": self.gate.current_generation(),
            "client_turn_id": "synthetic-turn",
            "receipt": {"operation_id": operation_id, "session_key": "synthetic-key", **receipt},
        }

    def test_invalidated_generation_never_restores_session_or_writes_failure(self) -> None:
        job = self.job("synthetic-operation")
        chat_factory = Mock(return_value=self.chat)
        session_factory = Mock(return_value=self.sessions)
        self.runner._chat_turn = chat_factory
        self.runner._sessions = session_factory
        with self.gate.restore():
            pass

        self.runner.run(job)

        chat_factory.assert_not_called()
        session_factory.assert_not_called()
        self.sessions.restore_coach_session_csrf_hash.assert_not_called()
        self.chat.run.assert_not_called()
        self.failures.persist.assert_not_called()

    def test_persisted_cancellation_is_seen_by_turn_and_event_is_cleaned(self) -> None:
        self.jobs.cancel_requested.return_value = True
        operation_id, _ = self.streams.register("synthetic-session")
        try:
            self.runner.run(self.job(operation_id))

            cancel_event = self.chat.run.call_args.kwargs["cancel_event"]
            self.assertTrue(cancel_event.is_set())
            self.assertIsNone(self.streams.get_background_event(operation_id))
            self.assertEqual(self.jobs.cancel_requested.call_args.args, ("synthetic-turn",))
            event, receipt = self.streams.events("synthetic-session", operation_id).get_nowait()
            self.assertEqual(event, "completed")
            self.assertEqual(receipt["message"]["content"], "synthetic")
        finally:
            self.streams.unregister("synthetic-session", operation_id)

    def test_queue_contention_requeues_and_emits_background_status(self) -> None:
        self.chat.run.side_effect = AppError(429, "busy", reason="chat_queue_full")
        operation_id, _ = self.streams.register("synthetic-session")
        try:
            self.runner.run(self.job(operation_id))

            self.jobs.requeue.assert_called_once_with("synthetic-turn", "chat_queue_full")
            self.failures.persist.assert_not_called()
            self.assertEqual(
                self.streams.events("synthetic-session", operation_id).get_nowait(),
                ("background", {"status": "queued", "mode": "background", "operation_id": operation_id}),
            )
            self.assertIsNone(self.streams.get_background_event(operation_id))
        finally:
            self.streams.unregister("synthetic-session", operation_id)

    def test_morning_completion_requires_final_message_without_clarification(self) -> None:
        self.completion.complete.return_value = {"status": "completed", "coach_quick_actions": {}}
        operation_id, _ = self.streams.register("synthetic-session")
        try:
            self.runner.run(self.job(operation_id, request_kind="morning_checkin"))
            self.morning.prepare.assert_called_once_with()
            self.completion.complete.assert_called_once_with("synthetic-turn")
            event, receipt = self.streams.events("synthetic-session", operation_id).get_nowait()
            self.assertEqual((event, receipt), ("completed", {"status": "completed", "coach_quick_actions": {}}))
        finally:
            self.streams.unregister("synthetic-session", operation_id)

        self.completion.reset_mock()
        self.chat.run.return_value = {"status": "completed", "message": {"content": "synthetic"}, "awaiting_clarification": True}
        self.runner.run(self.job("unattached-operation", request_kind="morning_checkin"))
        self.completion.complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
