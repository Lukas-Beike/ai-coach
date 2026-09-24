"""Focused unit tests for the authenticated chat cancellation POST route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.http_api.chat_cancel_post import ChatCancelPostRoutes


class ChatCancelPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cancellation_service = Mock()
        self.cancellation_service.cancel.return_value = {"cancelled": True}
        self.routes = ChatCancelPostRoutes(lambda: self.cancellation_service)
        self.handler = SimpleNamespace(
            read_json=Mock(return_value={"operation_id": "op-456"}),
            send_json=Mock(),
        )
        self.session = {"csrf_hash": "session-csrf-hash"}

    def test_success_dispatches_csrf_hash_and_operation_id(self) -> None:
        handled = self.routes.handle(self.handler, "/api/chat/cancel", self.session)
        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with()
        self.cancellation_service.cancel.assert_called_once_with(
            "session-csrf-hash", "op-456"
        )
        self.handler.send_json.assert_called_once_with(200, {"cancelled": True})

    def test_wrong_path_returns_false_without_side_effects(self) -> None:
        handled = self.routes.handle(self.handler, "/api/other", self.session)
        self.assertFalse(handled)
        self.handler.read_json.assert_not_called()
        self.cancellation_service.cancel.assert_not_called()
        self.handler.send_json.assert_not_called()
