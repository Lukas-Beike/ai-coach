"""Focused unit tests for the authenticated privacy restore POST route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from support import dispatch_route

from backend.http_api.privacy_restore_post import PrivacyRestorePostRoutes


class PrivacyRestorePostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth_service = Mock()
        self.auth_service.session_cookie_headers.return_value = [
            "cookie1=clear",
            "cookie2=clear",
        ]
        self.restore_service = Mock()
        self.restore_service.restore.return_value = {"restored": True}
        self.routes = PrivacyRestorePostRoutes(
            lambda: self.auth_service,
            lambda: self.restore_service,
            max_backup_bytes=10_000,
        )
        self.body_chunks = iter([b"synthetic-", b"backup-data"])
        self.handler = SimpleNamespace(
            read_body_stream=Mock(return_value=self.body_chunks),
            read_body=Mock(side_effect=AssertionError("restore must stream")),
            send_json=Mock(),
        )

    def test_success_reads_body_restores_and_clears_cookies(self) -> None:
        handled = dispatch_route(
            self.routes, self.handler, "/api/privacy/restore", method="POST"
        )
        self.assertTrue(handled)
        self.handler.read_body_stream.assert_called_once_with(10_000)
        self.handler.read_body.assert_not_called()
        self.restore_service.restore.assert_called_once_with(self.body_chunks)
        self.auth_service.session_cookie_headers.assert_called_once_with(clear=True)
        self.handler.send_json.assert_called_once_with(
            200,
            {"restored": True},
            {"Set-Cookie": ["cookie1=clear", "cookie2=clear"]},
        )

    def test_wrong_path_returns_false_without_side_effects(self) -> None:
        handled = dispatch_route(self.routes, self.handler, "/api/other", method="POST")
        self.assertFalse(handled)
        self.restore_service.restore.assert_not_called()
        self.handler.send_json.assert_not_called()
