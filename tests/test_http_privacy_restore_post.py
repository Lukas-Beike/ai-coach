"""Focused unit tests for the authenticated privacy restore POST route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.http_api.privacy_restore_post import PrivacyRestorePostRoutes


class PrivacyRestorePostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth_service = Mock()
        self.auth_service.require_auth.return_value = {"user": "athlete"}
        self.auth_service.session_cookie_headers.return_value = ["cookie1=clear", "cookie2=clear"]
        self.restore_service = Mock()
        self.restore_service.restore.return_value = {"restored": True}
        self.routes = PrivacyRestorePostRoutes(
            lambda: self.auth_service,
            lambda: self.restore_service,
            max_backup_bytes=10_000,
        )
        self.handler = SimpleNamespace(
            read_body=Mock(return_value=b"synthetic-backup-data"),
            send_json=Mock(),
        )

    def test_success_authenticates_reads_body_restores_and_clears_cookies(self) -> None:
        handled = self.routes.handle(self.handler, "/api/privacy/restore")
        self.assertTrue(handled)
        self.auth_service.require_auth.assert_called_once_with(self.handler)
        self.auth_service.require_csrf.assert_called_once_with(self.handler, {"user": "athlete"})
        self.handler.read_body.assert_called_once_with(10_000)
        self.restore_service.restore.assert_called_once_with(b"synthetic-backup-data")
        self.auth_service.session_cookie_headers.assert_called_once_with(clear=True)
        self.handler.send_json.assert_called_once_with(
            200,
            {"restored": True},
            {"Set-Cookie": ["cookie1=clear", "cookie2=clear"]},
        )

    def test_wrong_path_returns_false_without_side_effects(self) -> None:
        handled = self.routes.handle(self.handler, "/api/other")
        self.assertFalse(handled)
        self.auth_service.require_auth.assert_not_called()
        self.restore_service.restore.assert_not_called()
        self.handler.send_json.assert_not_called()
