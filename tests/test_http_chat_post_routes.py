from __future__ import annotations

import unittest
from unittest.mock import Mock, call

from support import dispatch_route

from backend.errors import AppError
from backend.http_api.chat_post import ChatPostRoutes


class ChatPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reset_service = Mock()
        self.reset_factory = Mock(return_value=self.reset_service)
        self.handler = Mock()
        self.routes = ChatPostRoutes(self.reset_factory, max_request_bytes=12345)

    def test_chat_reset_requires_confirmation_before_the_service_runs(self) -> None:
        for body in ({}, {"confirmed": False}, {"confirmed": "true"}, {"confirmed": 1}):
            with self.subTest(body=body):
                self.handler.reset_mock()
                self.reset_factory.reset_mock()
                self.handler.read_json.return_value = body

                with self.assertRaises(AppError) as caught:
                    dispatch_route(
                        self.routes, self.handler, "/api/chat/reset", method="POST"
                    )

                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(caught.exception.reason, "confirmation_required")
                self.reset_factory.assert_not_called()
                self.handler.send_json.assert_not_called()

    def test_confirmed_chat_reset_returns_service_result(self) -> None:
        result = {"status": "reset"}
        self.reset_service.reset.return_value = result
        self.handler.read_json.return_value = {"confirmed": True}

        handled = dispatch_route(
            self.routes, self.handler, "/api/chat/reset", method="POST"
        )

        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with(12345)
        self.reset_factory.assert_called_once_with()
        self.reset_service.reset.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        # The removed submission route is no longer handled either.
        handled = dispatch_route(self.routes, self.handler, "/api/chat", method="POST")

        self.assertFalse(handled)
        self.handler.read_json.assert_not_called()
        self.reset_factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_reset_error_propagates_without_response(self) -> None:
        error = RuntimeError("synthetic reset failure")
        self.handler.read_json.return_value = {"confirmed": True}
        self.reset_service.reset.side_effect = error

        with self.assertRaises(RuntimeError) as caught:
            dispatch_route(self.routes, self.handler, "/api/chat/reset", method="POST")

        self.assertIs(caught.exception, error)
        self.handler.send_json.assert_not_called()
        self.reset_factory.assert_called_once_with()
        self.reset_service.reset.assert_called_once_with()

    def test_factory_is_resolved_per_request(self) -> None:
        first_reset, second_reset = Mock(), Mock()
        self.reset_factory.side_effect = [first_reset, second_reset]
        self.handler.read_json.side_effect = [{"confirmed": True}, {"confirmed": True}]

        dispatch_route(self.routes, self.handler, "/api/chat/reset", method="POST")
        dispatch_route(self.routes, self.handler, "/api/chat/reset", method="POST")

        self.reset_factory.assert_has_calls([call(), call()])
        first_reset.reset.assert_called_once_with()
        second_reset.reset.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
