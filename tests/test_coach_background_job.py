"""Direct boundaries for durable Coach job execution and stream publication."""

from __future__ import annotations

import logging
import unittest
from datetime import date
from unittest.mock import Mock

from backend.coach.background_job import CoachBackgroundJobRunner
from backend.coach.job_store import MAX_FAILED_ATTEMPTS
from backend.coach.streams import ChatStreamRegistry
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate


class CoachBackgroundJobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = Mock()
        self.jobs.cancel_requested.return_value = False
        self.jobs.message.return_value = "synthetic message"
        self.chat = Mock()
        self.chat.run.return_value = {
            "status": "completed",
            "message": {"content": "synthetic"},
            "session_key": "must-not-leave-server",
        }
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
            self.jobs,
            lambda: self.chat,
            lambda: self.sessions,
            self.streams,
            lambda: self.morning,
            lambda: self.completion,
            lambda: self.failures,
            self.gate,
            self.redactor,
            logging.getLogger("test.coach.background-job"),
        )

    def job(self, operation_id: str, **receipt: object) -> dict[str, object]:
        return {
            "_maintenance_generation": self.gate.current_generation(),
            "client_turn_id": "synthetic-turn",
            "receipt": {
                "operation_id": operation_id,
                "session_key": "synthetic-key",
                **receipt,
            },
        }

    def test_invalidated_generation_never_restores_session_or_writes_failure(
        self,
    ) -> None:
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
            self.assertEqual(
                self.jobs.cancel_requested.call_args.args, ("synthetic-turn",)
            )
            event, receipt = self.streams.events(
                "synthetic-session", operation_id
            ).get_nowait()
            self.assertEqual(event, "completed")
            self.assertEqual(receipt["message"]["content"], "synthetic")
            self.assertNotIn("session_key", receipt)
        finally:
            self.streams.unregister("synthetic-session", operation_id)

    def test_queue_contention_requeues_and_emits_background_status(self) -> None:
        self.chat.run.side_effect = AppError(429, "busy", reason="chat_queue_full")
        operation_id, _ = self.streams.register("synthetic-session")
        try:
            self.runner.run(self.job(operation_id))

            self.jobs.requeue.assert_called_once_with(
                "synthetic-turn", "chat_queue_full"
            )
            self.failures.persist.assert_not_called()
            self.assertEqual(
                self.streams.events("synthetic-session", operation_id).get_nowait(),
                (
                    "background",
                    {
                        "status": "queued",
                        "mode": "background",
                        "operation_id": operation_id,
                    },
                ),
            )
            self.assertIsNone(self.streams.get_background_event(operation_id))
        finally:
            self.streams.unregister("synthetic-session", operation_id)

    def test_handled_failure_does_not_count_as_an_escaped_attempt(self) -> None:
        self.chat.run.side_effect = RuntimeError("synthetic")
        self.failures.persist.return_value = {"status": "failed"}

        self.runner.run(self.job("synthetic-operation"))

        self.jobs.record_failed_attempt.assert_not_called()
        self.failures.persist.assert_called_once()

    def test_escaped_failure_below_the_bound_is_counted_and_retried(self) -> None:
        self.chat.run.side_effect = RuntimeError("synthetic")
        self.failures.persist.side_effect = RuntimeError("synthetic persist failure")
        self.jobs.record_failed_attempt.return_value = MAX_FAILED_ATTEMPTS - 1

        with self.assertRaises(RuntimeError):
            self.runner.run(self.job("synthetic-operation"))

        self.jobs.record_failed_attempt.assert_called_once_with("synthetic-turn")
        self.failures.persist.assert_called_once()

    def test_job_that_keeps_failing_is_ended_with_a_terminal_failure(self) -> None:
        self.chat.run.side_effect = RuntimeError("synthetic")
        self.failures.persist.side_effect = [
            RuntimeError("synthetic persist failure"),
            {"status": "failed", "error": "ended"},
        ]
        self.jobs.record_failed_attempt.return_value = MAX_FAILED_ATTEMPTS
        operation_id, _ = self.streams.register("synthetic-session")
        try:
            with self.assertRaises(RuntimeError):
                self.runner.run(self.job(operation_id))

            ended = self.failures.persist.call_args_list[1]
            self.assertEqual(ended.args[:2], ("synthetic-turn", {}))
            self.assertEqual(ended.args[2].reason, "background_job_exhausted")
            events = self.streams.events("synthetic-session", operation_id)
            assert events is not None
            self.assertEqual(
                events.get_nowait(),
                ("completed", {"status": "failed", "error": "ended"}),
            )
        finally:
            self.streams.unregister("synthetic-session", operation_id)

    def test_failure_while_ending_a_job_keeps_the_original_error(self) -> None:
        self.sessions.restore_coach_session_csrf_hash.side_effect = RuntimeError(
            "original"
        )
        self.jobs.record_failed_attempt.side_effect = OSError("database gone")

        with self.assertRaises(RuntimeError) as raised:
            self.runner.run(self.job("synthetic-operation"))

        self.assertEqual(str(raised.exception), "original")

    def test_invalidated_or_requeued_jobs_never_count_as_failed_attempts(self) -> None:
        self.chat.run.side_effect = AppError(429, "busy", reason="chat_queue_full")
        self.runner.run(self.job("synthetic-operation"))
        stale = self.job("synthetic-operation")
        with self.gate.restore():
            pass
        self.runner.run(stale)

        self.jobs.requeue.assert_called_once()
        self.jobs.record_failed_attempt.assert_not_called()

    def test_morning_completion_requires_final_message_without_clarification(
        self,
    ) -> None:
        self.completion.complete.return_value = {
            "status": "completed",
            "coach_quick_actions": {},
        }
        self.morning.prepare.return_value = date(2026, 9, 23)
        operation_id, _ = self.streams.register("synthetic-session")
        try:
            self.runner.run(self.job(operation_id, request_kind="morning_checkin"))
            self.morning.prepare.assert_called_once_with()
            # The day prepared for is kept for the marker (#2134, E-014).
            self.jobs.merge_receipt.assert_any_call(
                "synthetic-turn", {"morning_checkin_date": "2026-09-23"}
            )
            self.completion.complete.assert_called_once_with("synthetic-turn")
            event, receipt = self.streams.events(
                "synthetic-session", operation_id
            ).get_nowait()
            self.assertEqual(
                (event, receipt),
                ("completed", {"status": "completed", "coach_quick_actions": {}}),
            )
        finally:
            self.streams.unregister("synthetic-session", operation_id)

        self.completion.reset_mock()
        self.chat.run.return_value = {
            "status": "completed",
            "message": {"content": "synthetic"},
            "awaiting_clarification": True,
        }
        self.runner.run(
            self.job("unattached-operation", request_kind="morning_checkin")
        )
        self.completion.complete.assert_not_called()

    def test_sleep_not_ready_waits_a_quarter_hour_without_starting_the_turn(
        self,
    ) -> None:
        self.morning.prepare.side_effect = AppError(
            503, "Garmin sleep is not ready", reason="garmin_sleep_not_ready"
        )

        self.runner.run(self.job("op-wait", request_kind="morning_checkin"))

        self.jobs.requeue.assert_called_once_with(
            "synthetic-turn", "garmin_sleep_not_ready", wait_seconds=900, max_waits=8
        )
        self.chat.run.assert_not_called()
        self.failures.persist.assert_not_called()
        self.jobs.requeue.return_value = False
        self.failures.persist.return_value = {"status": "failed"}
        self.runner.run(self.job("op-gave-up", request_kind="morning_checkin"))
        self.failures.persist.assert_called_once()
        self.chat.run.assert_not_called()

    def test_cancel_before_morning_prepare_skips_the_garmin_sync(self) -> None:
        self.failures.persist.return_value = {"status": "cancelled"}
        self.jobs.cancel_requested.return_value = True

        self.runner.run(self.job("op-before", request_kind="morning_checkin"))

        self.morning.prepare.assert_not_called()
        self.chat.run.assert_not_called()
        persisted = self.failures.persist.call_args.args[2]
        self.assertEqual(persisted.reason, "chat_cancelled")

    def test_cancel_during_morning_prepare_stops_before_the_turn(self) -> None:
        operation_id = "op-during"
        self.failures.persist.return_value = {"status": "cancelled"}
        self.morning.prepare.side_effect = lambda: self.streams.cancel_background_event(
            operation_id
        )

        self.runner.run(self.job(operation_id, request_kind="morning_checkin"))

        self.morning.prepare.assert_called_once_with()
        self.chat.run.assert_not_called()
        persisted = self.failures.persist.call_args.args[2]
        self.assertEqual(persisted.reason, "chat_cancelled")

    def test_rerequested_morning_turn_does_not_repeat_the_sync(self) -> None:
        self.completion.complete.return_value = {"status": "completed"}
        self.runner.run(
            self.job(
                "op-rerequest",
                request_kind="morning_checkin",
                morning_checkin_date="2026-09-07",
            )
        )

        self.morning.prepare.assert_not_called()
        self.chat.run.assert_called_once()

    def test_attached_stream_gets_deltas_until_the_turn_was_requested_once(
        self,
    ) -> None:
        for reached in (False, True):
            with self.subTest(reached=reached):
                self.chat.run.reset_mock()
                self.jobs.merge_receipt.reset_mock()
                session = f"synthetic-session-{reached}"
                self.sessions.restore_coach_session_csrf_hash.return_value = session
                operation_id, _ = self.streams.register(session)

                self.runner.run(self.job(operation_id, openai_reached=reached))

                # A checkpointed phase is not reset to "preparing".
                self.jobs.merge_receipt.assert_called_once_with(
                    "synthetic-turn",
                    {"status": "running"}
                    if reached
                    else {"status": "running", "phase": "preparing"},
                )
                publish = self.chat.run.call_args.kwargs["on_text_delta"]
                if reached:
                    # The first attempt may have shown text already.
                    self.assertIsNone(publish)
                    continue
                publish("Hallo")
                events = self.streams.events(session, operation_id)
                assert events is not None
                self.assertEqual(events.get_nowait()[0], "completed")
                self.assertEqual(events.get_nowait(), ("delta", {"text": "Hallo"}))


if __name__ == "__main__":
    unittest.main()
