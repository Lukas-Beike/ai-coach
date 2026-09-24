from __future__ import annotations

import unittest
from unittest.mock import Mock, call

from backend.errors import AppError
from backend.http_api.chat_post import ChatPostRoutes


class ChatPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.submission_service = Mock()
        self.reset_service = Mock()
        self.submission_factory = Mock(return_value=self.submission_service)
        self.reset_factory = Mock(return_value=self.reset_service)
        self.handler = Mock()
        self.session = {"csrf_hash": "synthetic-session-hash"}
        self.routes = ChatPostRoutes(
            self.submission_factory, self.reset_factory, max_request_bytes=12345
        )

    def test_chat_submission_uses_bounded_body_and_expected_service_arguments(self) -> None:
        result = {"job_id": "synthetic-job", "status": "queued"}
        self.handler.read_json.return_value = {
            "client_turn_id": "  synthetic-turn-id  ",
            "message": 123,
            "request_kind": "synthetic-kind",
            "attachments": [{"id": "synthetic-attachment"}],
        }
        self.submission_service.enqueue.return_value = result

        handled = self.routes.handle(self.handler, "/api/chat", self.session)

        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with(12345)
        self.submission_factory.assert_called_once_with()
        self.reset_factory.assert_not_called()
        self.submission_service.enqueue.assert_called_once_with(
            "123", "synthetic-turn-id", "synthetic-session-hash",
            request_kind="synthetic-kind",
            attachments=[{"id": "synthetic-attachment"}],
        )
        self.handler.send_json.assert_called_once_with(202, result)

    def test_empty_or_falsy_turn_ids_raise_before_service_factory(self) -> None:
        for invalid_turn_id in (None, "", "   ", 0, False):
            with self.subTest(client_turn_id=invalid_turn_id):
                self.handler.reset_mock()
                self.submission_factory.reset_mock()
                self.handler.read_json.return_value = {
                    "client_turn_id": invalid_turn_id,
                }

                with self.assertRaises(AppError) as caught:
                    self.routes.handle(self.handler, "/api/chat", self.session)

                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(
                    caught.exception.message,
                    "client_turn_id ist für Coach-Nachrichten erforderlich.",
                )
                self.assertEqual(caught.exception.reason, "invalid_client_turn")
                self.handler.read_json.assert_called_once_with(12345)
                self.submission_factory.assert_not_called()
                self.handler.send_json.assert_not_called()

    def test_chat_reset_has_no_body_and_returns_service_result(self) -> None:
        result = {"status": "reset"}
        self.reset_service.reset.return_value = result

        handled = self.routes.handle(self.handler, "/api/chat/reset", self.session)

        self.assertTrue(handled)
        self.handler.read_json.assert_not_called()
        self.submission_factory.assert_not_called()
        self.reset_factory.assert_called_once_with()
        self.reset_service.reset.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        handled = self.routes.handle(self.handler, "/api/chat/other", self.session)

        self.assertFalse(handled)
        self.handler.read_json.assert_not_called()
        self.submission_factory.assert_not_called()
        self.reset_factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_service_errors_propagate_without_response(self) -> None:
        error = RuntimeError("synthetic submission failure")
        self.handler.read_json.return_value = {"client_turn_id": "synthetic-turn"}
        self.submission_service.enqueue.side_effect = error

        with self.assertRaises(RuntimeError) as caught:
            self.routes.handle(self.handler, "/api/chat", self.session)

        self.assertIs(caught.exception, error)
        self.submission_factory.assert_called_once_with()
        self.handler.send_json.assert_not_called()

    def test_reset_error_propagates_without_body_or_response(self) -> None:
        error = RuntimeError("synthetic reset failure")
        self.reset_service.reset.side_effect = error

        with self.assertRaises(RuntimeError) as caught:
            self.routes.handle(self.handler, "/api/chat/reset", self.session)

        self.assertIs(caught.exception, error)
        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        self.submission_factory.assert_not_called()
        self.reset_factory.assert_called_once_with()
        self.reset_service.reset.assert_called_once_with()

    def test_factories_are_resolved_per_request(self) -> None:
        first, second = Mock(), Mock()
        self.submission_factory.side_effect = [first, second]
        first_reset, second_reset = Mock(), Mock()
        self.reset_factory.side_effect = [first_reset, second_reset]
        self.handler.read_json.side_effect = [
            {"client_turn_id": "first-turn"},
            {"client_turn_id": "second-turn"},
        ]

        self.routes.handle(self.handler, "/api/chat", self.session)
        self.routes.handle(self.handler, "/api/chat", self.session)
        self.routes.handle(self.handler, "/api/chat/reset", self.session)
        self.routes.handle(self.handler, "/api/chat/reset", self.session)

        self.submission_factory.assert_has_calls([call(), call()])
        first.enqueue.assert_called_once_with(
            "", "first-turn", "synthetic-session-hash",
            request_kind=None, attachments=None,
        )
        second.enqueue.assert_called_once_with(
            "", "second-turn", "synthetic-session-hash",
            request_kind=None, attachments=None,
        )
        self.reset_factory.assert_has_calls([call(), call()])
        first_reset.reset.assert_called_once_with()
        second_reset.reset.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
