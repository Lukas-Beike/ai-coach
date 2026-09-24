from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.public_get import PublicGetRoutes


class PublicGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.handler.path = "/api/bootstrap"
        self.maintenance_gate = Mock()
        self.maintenance_gate.state.return_value = {"active": False}
        self.readiness = Mock()
        self.readiness.state.return_value = {"ready": True, "status": "ready"}
        self.auth = Mock()
        self.auth.authenticated_session.return_value = None
        self.bootstrap = Mock()
        self.bootstrap.read.return_value = {"schema_version": 3}
        self.readiness_factory = Mock(return_value=self.readiness)
        self.auth_factory = Mock(return_value=self.auth)
        self.bootstrap_factory = Mock(return_value=self.bootstrap)
        self.routes = PublicGetRoutes(
            self.maintenance_gate,
            self.readiness_factory,
            self.auth_factory,
            self.bootstrap_factory,
        )

    def test_health_returns_live_maintenance_state(self) -> None:
        self.maintenance_gate.state.side_effect = [
            {"active": False},
            {"active": True},
        ]

        self.assertTrue(self.routes.handle(self.handler, "/api/health"))
        self.assertTrue(self.routes.handle(self.handler, "/api/health"))

        self.assertEqual(
            self.handler.send_json.call_args_list,
            [
                unittest.mock.call(200, {"status": "ok", "maintenance": {"active": False}}),
                unittest.mock.call(200, {"status": "ok", "maintenance": {"active": True}}),
            ],
        )
        self.readiness_factory.assert_not_called()
        self.auth_factory.assert_not_called()
        self.bootstrap_factory.assert_not_called()

    def test_readiness_uses_ready_boolean_for_http_status_and_preserves_json(self) -> None:
        ready = {"ready": True, "status": "ready", "details": {"database": True}}
        not_ready = {"ready": False, "status": "not_ready", "details": {"database": False}}
        self.readiness.state.side_effect = [ready, not_ready]

        self.assertTrue(self.routes.handle(self.handler, "/api/readiness"))
        self.assertTrue(self.routes.handle(self.handler, "/api/readiness"))

        self.assertEqual(
            self.handler.send_json.call_args_list,
            [unittest.mock.call(200, ready), unittest.mock.call(503, not_ready)],
        )
        self.readiness_factory.assert_has_calls([unittest.mock.call(), unittest.mock.call()])

    def test_auth_status_uses_optional_authenticated_session_and_live_gate(self) -> None:
        self.auth.authenticated_session.side_effect = [None, {"csrf_hash": "fake"}]
        self.maintenance_gate.state.side_effect = [
            {"active": False},
            {"active": True},
        ]

        self.assertTrue(self.routes.handle(self.handler, "/api/auth/status"))
        self.assertTrue(self.routes.handle(self.handler, "/api/auth/status"))

        self.assertEqual(
            self.handler.send_json.call_args_list,
            [
                unittest.mock.call(
                    200,
                    {"authenticated": False, "maintenance": {"active": False}},
                ),
                unittest.mock.call(
                    200,
                    {"authenticated": True, "maintenance": {"active": True}},
                ),
            ],
        )
        self.auth.authenticated_session.assert_has_calls(
            [unittest.mock.call(self.handler), unittest.mock.call(self.handler)]
        )
        self.auth.require_auth.assert_not_called()

    def test_bootstrap_authenticates_before_read_and_returns_json(self) -> None:
        events: list[str] = []
        self.auth.require_auth.side_effect = lambda _handler: events.append("auth")
        self.bootstrap.read.side_effect = lambda: events.append("read") or {"schema_version": 3}

        self.assertTrue(self.routes.handle(self.handler, "/api/bootstrap"))

        self.assertEqual(events, ["auth", "read"])
        self.handler.send_json.assert_called_once_with(200, {"schema_version": 3})
        self.auth.authenticated_session.assert_not_called()

    def test_bootstrap_auth_error_propagates_before_bootstrap_factory(self) -> None:
        error = RuntimeError("auth failed")
        self.auth.require_auth.side_effect = error

        with self.assertRaisesRegex(RuntimeError, "auth failed") as raised:
            self.routes.handle(self.handler, "/api/bootstrap")

        self.assertIs(raised.exception, error)
        self.bootstrap_factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_unknown_path_does_not_resolve_factories_or_gate(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/not-public"))

        self.maintenance_gate.state.assert_not_called()
        self.readiness_factory.assert_not_called()
        self.auth_factory.assert_not_called()
        self.bootstrap_factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_auth_service_is_resolved_for_each_keep_alive_request(self) -> None:
        first_auth = Mock()
        second_auth = Mock()
        first_auth.authenticated_session.return_value = {"csrf_hash": "first"}
        second_auth.authenticated_session.return_value = None
        self.auth_factory.side_effect = [first_auth, second_auth]

        self.assertTrue(self.routes.handle(self.handler, "/api/auth/status"))
        self.assertTrue(self.routes.handle(self.handler, "/api/auth/status"))

        self.assertEqual(self.auth_factory.call_count, 2)
        first_auth.authenticated_session.assert_called_once_with(self.handler)
        second_auth.authenticated_session.assert_called_once_with(self.handler)
        self.assertEqual(
            [call.args[1]["authenticated"] for call in self.handler.send_json.call_args_list],
            [True, False],
        )


if __name__ == "__main__":
    unittest.main()
