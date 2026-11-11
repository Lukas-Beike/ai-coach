"""POST handler re-validates the session after entering the maintenance gate."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.handler import RequestHandler
from backend.http_api.route_table import Access, Route, RouteRequest, RouteTable
from backend.runtime.maintenance import MaintenanceGate

SESSION = {"csrf_hash": "synthetic-csrf-hash", "expires_at": 4_102_444_800.0}


class PostReauthenticatesInsideMaintenanceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = MaintenanceGate()
        self.auth_service = Mock()
        self.auth_service.require_auth.return_value = SESSION
        self.auth_service.require_csrf.return_value = None
        self.auth_service.authenticated_session.return_value = SESSION
        self.route, self.ungated_route = Mock(), Mock()

        # A bare handler stub: only the attributes do_POST reads are set.
        handler: Any = RequestHandler.__new__(RequestHandler)
        handler.command = "POST"
        handler.path = "/api/synthetic"
        handler.headers = {"X-CSRF-Token": "synthetic-token"}
        handler.dependencies = SimpleNamespace(
            session_auth_service=lambda: self.auth_service,
            route_table=RouteTable(
                [
                    Route("POST", "/api/synthetic", Access.SESSION_CSRF, self.route),
                    Route(
                        "POST",
                        "/api/ungated",
                        Access.SESSION_CSRF,
                        self.ungated_route,
                        gated=False,
                    ),
                ]
            ),
            maintenance_gate=self.gate,
            logger=Mock(),
            internal_server_error="internal",
        )
        handler._send_app_error = Mock()
        handler.send_json = Mock()
        self.handler = handler

    def test_valid_session_is_checked_again_and_dispatched_once_authenticated(
        self,
    ) -> None:
        self.handler.do_POST()

        self.auth_service.require_auth.assert_called_once_with(self.handler)
        self.auth_service.authenticated_session.assert_called_once_with(self.handler)
        self.auth_service.require_csrf.assert_called_with(self.handler, SESSION)
        self.route.assert_called_once_with(
            self.handler, RouteRequest("/api/synthetic", {}, {}, SESSION)
        )
        self.handler._send_app_error.assert_not_called()

    def test_session_revoked_by_restore_before_gate_is_rejected(self) -> None:
        def restore_then_session_is_gone(handler: object) -> dict | None:
            # Simulates a restore that completes after the first auth check and
            # deletes every session before the POST enters the gate.
            with self.gate.restore():
                pass
            return None

        self.auth_service.authenticated_session.side_effect = (
            restore_then_session_is_gone
        )

        self.handler.do_POST()

        self.route.assert_not_called()
        # The pre-gate CSRF check ran with the first session; the revoked
        # session must never reach the CSRF check or the dispatcher.
        self.auth_service.require_csrf.assert_called_once_with(self.handler, SESSION)
        self.handler._send_app_error.assert_called_once()
        error = self.handler._send_app_error.call_args.args[0]
        self.assertIsInstance(error, AppError)
        self.assertEqual(error.status, 401)
        self.assertEqual(self.handler._send_app_error.call_args.args[1], "POST")

    def test_pre_gate_routes_still_use_the_first_session_and_skip_the_gate(
        self,
    ) -> None:
        self.handler.path = "/api/ungated"

        self.handler.do_POST()

        self.ungated_route.assert_called_once_with(
            self.handler, RouteRequest("/api/ungated", {}, {}, SESSION)
        )
        self.auth_service.authenticated_session.assert_not_called()
        self.route.assert_not_called()


if __name__ == "__main__":
    unittest.main()
