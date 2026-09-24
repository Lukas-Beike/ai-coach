"""Tests for ordered POST route dispatch."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.post_dispatch import HttpPostDispatcher


class HttpPostDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.routes = [Mock() for _ in range(14)]
        for route in self.routes:
            route.handle.return_value = False
        self.dispatcher = HttpPostDispatcher(*self.routes)
        self.handler = Mock()
        self.session = {"csrf_hash": "synthetic-session"}

    def test_public_route_order_stops_after_auth_or_restore(self) -> None:
        auth, restore = self.routes[:2]
        auth.handle.return_value = True

        self.assertTrue(self.dispatcher.handle_before_auth(self.handler, "/api/login"))

        auth.handle.assert_called_once_with(self.handler, "/api/login")
        restore.handle.assert_not_called()

        auth.handle.return_value = False
        restore.handle.return_value = True
        self.assertTrue(
            self.dispatcher.handle_before_auth(self.handler, "/api/privacy/restore")
        )
        restore.handle.assert_called_once_with(self.handler, "/api/privacy/restore")

    def test_cancellation_is_a_separate_pre_maintenance_route(self) -> None:
        cancel = self.routes[2]
        cancel.handle.return_value = True

        self.assertTrue(
            self.dispatcher.handle_before_maintenance(
                self.handler, "/api/chat/cancel", self.session
            )
        )

        cancel.handle.assert_called_once_with(
            self.handler, "/api/chat/cancel", self.session
        )

    def test_authenticated_route_order_short_circuits(self) -> None:
        coach_actions, chat = self.routes[3:5]
        coach_actions.handle.return_value = False
        chat.handle.return_value = True

        self.dispatcher.handle_authenticated(
            self.handler, "/api/chat", self.session
        )

        coach_actions.handle.assert_called_once_with(
            self.handler, "/api/chat", self.session
        )
        chat.handle.assert_called_once_with(self.handler, "/api/chat", self.session)
        for route in self.routes[5:]:
            route.handle.assert_not_called()

    def test_unmatched_authenticated_route_remains_a_404(self) -> None:
        with self.assertRaises(AppError) as raised:
            self.dispatcher.handle_authenticated(
                self.handler, "/api/not-found", self.session
            )
        self.assertEqual(raised.exception.status, 404)

    def test_chat_stream_is_dispatched_only_after_regular_coach_routes(self) -> None:
        self.dispatcher.handle_authenticated(
            self.handler, "/api/chat/stream", self.session
        )

        for route in self.routes[3:8]:
            route.handle.assert_called_once()
            self.assertFalse(route.handle.return_value)
        self.routes[8].handle.assert_called_once_with(self.handler, self.session)
        for route in self.routes[9:]:
            route.handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
