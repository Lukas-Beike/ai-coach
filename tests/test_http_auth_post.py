"""Focused unit tests for login and logout POST routes."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from support import dispatch_route

from backend.http_api.auth_post import AuthPostRoutes


class AuthPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth_service = Mock()
        self.auth_service.login_user.return_value = {
            "status": "ok",
            "session_token": "token-xyz",
            "csrf": "csrf-abc",
        }
        self.auth_service.session_cookie_headers.side_effect = lambda *args, **kwargs: (
            ["ic_session=clear", "ic_csrf=clear"]
            if kwargs.get("clear")
            else ["ic_session=token-xyz", "ic_csrf=csrf-abc"]
        )

        self.maintenance_gate = MagicMock()
        self.maintenance_gate.operation.return_value.__enter__ = Mock(return_value=None)
        self.maintenance_gate.operation.return_value.__exit__ = Mock(return_value=None)

        self.routes = AuthPostRoutes(
            lambda: self.auth_service,
            self.maintenance_gate,
        )
        self.handler = SimpleNamespace(
            read_json=Mock(return_value={"password": "secret-password"}),
            send_json=Mock(),
        )

    def test_login_success_dispatches_password_and_sets_cookies(self) -> None:
        handled = dispatch_route(self.routes, self.handler, "/api/login", method="POST")
        self.assertTrue(handled)
        self.handler.read_json.assert_not_called()
        self.auth_service.login_user.assert_called_once_with(self.handler)
        self.handler.send_json.assert_called_once_with(
            200,
            {"status": "ok", "csrf": "csrf-abc"},
            {"Set-Cookie": ["ic_session=token-xyz", "ic_csrf=csrf-abc"]},
        )

    def test_logout_success_operates_gate_and_clears_cookies(
        self,
    ) -> None:
        handled = dispatch_route(
            self.routes, self.handler, "/api/logout", method="POST"
        )
        self.assertTrue(handled)
        self.maintenance_gate.operation.assert_called_once_with()
        self.auth_service.logout_user.assert_called_once_with(self.handler)
        self.handler.send_json.assert_called_once_with(
            200,
            {"status": "ok"},
            {"Set-Cookie": ["ic_session=clear", "ic_csrf=clear"]},
        )

    def test_wrong_path_returns_false_without_side_effects(self) -> None:
        handled = dispatch_route(self.routes, self.handler, "/api/other", method="POST")
        self.assertFalse(handled)
        self.auth_service.login_user.assert_not_called()
        self.auth_service.logout_user.assert_not_called()
        self.handler.send_json.assert_not_called()
