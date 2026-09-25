from __future__ import annotations

import queue
import threading
import unittest
from unittest.mock import Mock, call

from backend.errors import INTERNAL_SERVER_ERROR, AppError, ClientDisconnected
from backend.http_api.chat_stream import CoachChatStreamTransport


class CoachChatStreamTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cancel_event = threading.Event()
        self.registry = Mock()
        self.registry.register.return_value = ("new-operation", self.cancel_event)
        self.events = queue.Queue()
        self.registry.events.return_value = self.events
        self.submission = Mock()
        self.submission.enqueue.return_value = {"operation_id": "new-operation"}
        self.submission_factory = Mock(return_value=self.submission)
        self.receipts = Mock()
        self.receipt_factory = Mock(return_value=self.receipts)
        self.redact = Mock(side_effect=lambda value: f"redacted:{value}")
        self.logger = Mock()
        self.handler = Mock()
        self.handler.request_id = "synthetic-request"
        self.handler.read_json.return_value = {
            "message": "synthetic message",
            "client_turn_id": "  synthetic-turn  ",
            "request_kind": "synthetic-kind",
            "attachments": [{"id": "synthetic-attachment"}],
        }
        self.session = {"csrf_hash": "synthetic-session"}
        self.transport = CoachChatStreamTransport(
            self.registry,
            self.submission_factory,
            self.receipt_factory,
            self.redact,
            self.logger,
            max_request_bytes=12345,
            response_timeout_seconds=180,
        )

    def test_stream_relays_events_and_unregisters_after_terminal_event(self) -> None:
        self.events.put(("delta", {"text": "hello"}))
        self.events.put(("completed", {"status": "done"}))

        self.transport.handle(self.handler, self.session)

        self.handler.read_json.assert_called_once_with(12345)
        self.registry.register.assert_called_once_with("synthetic-session")
        self.handler.connection.settimeout.assert_called_once_with(210)
        self.handler.send_sse_headers.assert_called_once_with(persistent=False)
        self.submission.enqueue.assert_called_once_with(
            "synthetic message",
            "synthetic-turn",
            "synthetic-session",
            operation_id="new-operation",
            cancel_event=self.cancel_event,
            request_kind="synthetic-kind",
            attachments=[{"id": "synthetic-attachment"}],
        )
        self.handler.send_sse_event.assert_has_calls(
            [
                call("started", {"operation_id": "new-operation"}),
                call("delta", {"text": "hello"}),
                call("completed", {"status": "done"}),
            ]
        )
        self.assertEqual(self.handler.send_sse_event.call_count, 3)
        self.registry.unregister.assert_called_once_with(
            "synthetic-session", "new-operation"
        )
        self.assertTrue(self.handler.close_connection)
        self.assertFalse(self.cancel_event.is_set())

    def test_disconnect_does_not_cancel_or_stop_durable_submission(self) -> None:
        self.handler.send_sse_event.side_effect = ClientDisconnected()
        self.events.put(("completed", {"status": "done"}))

        self.transport.handle(self.handler, self.session)

        self.submission.enqueue.assert_called_once()
        self.handler.send_sse_event.assert_called_once_with(
            "started", {"operation_id": "new-operation"}
        )
        self.assertFalse(self.cancel_event.is_set())
        self.registry.unregister.assert_called_once()
        self.assertTrue(self.handler.close_connection)

    def test_header_disconnect_still_submits_without_further_events(self) -> None:
        self.handler.send_sse_headers.side_effect = ClientDisconnected()
        self.events.put(("completed", {"status": "done"}))

        self.transport.handle(self.handler, self.session)

        self.submission.enqueue.assert_called_once()
        self.handler.send_sse_event.assert_not_called()
        self.registry.unregister.assert_called_once()
        self.assertFalse(self.cancel_event.is_set())

    def test_restart_replay_returns_original_job_as_background(self) -> None:
        original_job = {"operation_id": "original-operation", "status": "running"}
        self.submission.enqueue.return_value = original_job

        self.transport.handle(self.handler, self.session)

        self.registry.events.assert_not_called()
        self.handler.send_sse_event.assert_has_calls(
            [
                call("started", {"operation_id": "new-operation"}),
                call("background", original_job),
            ]
        )
        self.registry.unregister.assert_called_once()

    def test_detached_queue_returns_background_receipt(self) -> None:
        self.registry.events.return_value = None

        self.transport.handle(self.handler, self.session)

        self.handler.send_sse_event.assert_any_call(
            "background", {"operation_id": "new-operation"}
        )
        self.registry.unregister.assert_called_once()

    def test_timeout_heartbeats_while_active_then_reads_final_receipt(self) -> None:
        self.events = Mock()
        self.events.get.side_effect = [queue.Empty(), queue.Empty()]
        self.registry.events.return_value = self.events
        self.submission.active.side_effect = [{"status": "running"}, None]
        self.receipts.read.return_value = {"status": "completed"}

        self.transport.handle(self.handler, self.session)

        self.assertEqual(self.events.get.call_args_list, [call(timeout=15), call(timeout=15)])
        self.handler.send_sse_event.assert_has_calls(
            [
                call("started", {"operation_id": "new-operation"}),
                call("heartbeat", {"operation_id": "new-operation"}),
                call("completed", {"status": "completed"}),
            ]
        )
        self.receipts.read.assert_called_once_with(
            "synthetic-turn", "synthetic-session"
        )
        self.registry.unregister.assert_called_once()

    def test_app_error_is_redacted_and_cleanup_is_preserved(self) -> None:
        self.submission.enqueue.side_effect = AppError(409, "synthetic private detail", reason="conflict")

        self.transport.handle(self.handler, self.session)

        self.handler.send_sse_event.assert_any_call(
            "error", {"reason": "conflict", "message": "redacted:synthetic private detail"}
        )
        self.registry.unregister.assert_called_once()
        self.assertTrue(self.handler.close_connection)

    def test_receipt_failure_is_redacted_after_queue_detaches(self) -> None:
        self.events = Mock()
        self.events.get.side_effect = queue.Empty()
        self.registry.events.return_value = self.events
        self.submission.active.return_value = None
        self.receipts.read.side_effect = AppError(404, "synthetic private receipt", reason="receipt_missing")

        self.transport.handle(self.handler, self.session)

        self.handler.send_sse_event.assert_any_call(
            "error", {"reason": "receipt_missing", "message": "redacted:synthetic private receipt"}
        )
        self.registry.unregister.assert_called_once()

    def test_invalid_turn_rejects_before_registration_or_response(self) -> None:
        self.handler.read_json.return_value = {"client_turn_id": "  "}

        with self.assertRaises(AppError) as caught:
            self.transport.handle(self.handler, self.session)

        self.assertEqual((caught.exception.status, caught.exception.reason), (400, "invalid_client_turn"))
        self.registry.register.assert_not_called()
        self.submission_factory.assert_not_called()
        self.handler.send_sse_headers.assert_not_called()

    def test_unexpected_error_logs_and_sends_only_safe_error(self) -> None:
        self.submission.enqueue.side_effect = RuntimeError("synthetic private detail")

        self.transport.handle(self.handler, self.session)

        self.handler.send_sse_event.assert_any_call(
            "error", {"reason": "internal_error", "message": INTERNAL_SERVER_ERROR}
        )
        self.logger.exception.assert_called_once()
        self.assertEqual(
            self.logger.exception.call_args.kwargs["extra"]["context"],
            {"request_id": "synthetic-request"},
        )
        self.registry.unregister.assert_called_once()


if __name__ == "__main__":
    unittest.main()
