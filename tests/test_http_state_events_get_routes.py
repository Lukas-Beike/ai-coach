"""Direct contract tests for authenticated state-event GET dispatch."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.state_events_get import StateEventsGetRoutes


class StateEventsGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.handler.path = "/api/state/events?since=17"
        self.auth = Mock()
        self.auth_factory = Mock(return_value=self.auth)
        self.transport = Mock()
        self.routes = StateEventsGetRoutes(self.auth_factory, self.transport)

    def test_recognized_path_authenticates_then_forwards_exact_transport_callbacks(self) -> None:
        self.assertTrue(self.routes.handle(self.handler, "/api/state/events"))
        self.auth_factory.assert_called_once_with()
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.transport.handle.assert_called_once_with(
            self.handler.path,
            send_headers=self.handler.send_sse_headers,
            send_event=self.handler.send_sse_event,
            set_connection_timeout=self.handler.connection.settimeout,
        )

    def test_auth_denial_precedes_connection_and_transport_access(self) -> None:
        denied = RuntimeError("denied")
        self.auth.require_auth.side_effect = denied
        with self.assertRaisesRegex(RuntimeError, "denied") as caught:
            self.routes.handle(self.handler, "/api/state/events")
        self.assertIs(caught.exception, denied)
        self.handler.connection.assert_not_called()
        self.transport.handle.assert_not_called()
        self.handler.send_sse_headers.assert_not_called()
        self.handler.send_sse_event.assert_not_called()

    def test_unknown_path_returns_false_without_resolving_dependencies(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/state/events/extra"))
        self.auth_factory.assert_not_called()
        self.transport.handle.assert_not_called()
        self.handler.connection.assert_not_called()

    def test_auth_factory_is_resolved_for_each_request(self) -> None:
        second_auth = Mock()
        self.auth_factory.side_effect = [self.auth, second_auth]
        self.routes.handle(self.handler, "/api/state/events")
        self.routes.handle(self.handler, "/api/state/events")
        self.assertEqual(self.auth_factory.call_count, 2)
        self.auth.require_auth.assert_called_once_with(self.handler)
        second_auth.require_auth.assert_called_once_with(self.handler)


if __name__ == "__main__":
    unittest.main()
