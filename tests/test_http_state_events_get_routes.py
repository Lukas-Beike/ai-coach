"""Direct contract tests for authenticated state-event GET dispatch."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import ANY, Mock

from support import dispatch_route

from backend.http_api.state_events_get import (
    StateEventsGetRoutes,
    client_is_connected,
)


class StateEventsGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.handler.path = "/api/state/events?since=17"
        self.auth = Mock()
        self.auth_factory = Mock(return_value=self.auth)
        self.transport = Mock()
        self.routes = StateEventsGetRoutes(self.auth_factory, self.transport)

    def test_recognized_path_forwards_exact_transport_callbacks(
        self,
    ) -> None:
        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/state/events"))
        self.auth_factory.assert_not_called()
        self.transport.handle.assert_called_once_with(
            self.handler.path,
            send_headers=self.handler.send_sse_headers,
            send_event=self.handler.send_sse_event,
            set_connection_timeout=self.handler.connection.settimeout,
            client_is_connected=ANY,
            session_is_active=ANY,
        )

    def test_session_callback_reflects_authenticated_session_lookup(self) -> None:
        dispatch_route(self.routes, self.handler, "/api/state/events")
        session_is_active = self.transport.handle.call_args.kwargs["session_is_active"]

        self.auth.authenticated_session.return_value = {
            "csrf_hash": "fake-csrf-hash",
            "expires_at": 4102444800.0,
        }
        self.assertTrue(session_is_active())
        self.auth.authenticated_session.return_value = None
        self.assertFalse(session_is_active())

        self.assertEqual(self.auth.authenticated_session.call_count, 2)
        self.auth.authenticated_session.assert_called_with(self.handler)
        self.auth.require_auth.assert_not_called()

    def test_client_is_connected_sees_a_closed_peer_and_keeps_pending_bytes(
        self,
    ) -> None:
        server_side, client_side = socket.socketpair()
        self.addCleanup(server_side.close)
        self.addCleanup(client_side.close)
        self.assertTrue(client_is_connected(server_side))
        client_side.sendall(b"x")
        self.assertTrue(client_is_connected(server_side))
        self.assertEqual(server_side.recv(1), b"x")
        client_side.close()
        self.assertFalse(client_is_connected(server_side))

    def test_client_is_connected_is_false_for_a_closed_local_socket(self) -> None:
        server_side, client_side = socket.socketpair()
        self.addCleanup(client_side.close)
        server_side.close()
        self.assertFalse(client_is_connected(server_side))

    def test_unknown_path_returns_false_without_resolving_dependencies(self) -> None:
        self.assertFalse(dispatch_route(self.routes, self.handler, "/api/state/events/extra"))
        self.auth_factory.assert_not_called()
        self.transport.handle.assert_not_called()
        self.handler.connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
