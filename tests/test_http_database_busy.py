"""A busy local database answers with a retryable 503, never a 500."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from backend.errors import DATABASE_BUSY_MESSAGE, AppError, DatabaseBusyError
from backend.http_api import handler as handler_module
from backend.http_api.handler import RequestHandler
from backend.runtime.maintenance import MaintenanceGate


class DatabaseBusyResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth_service = Mock()
        self.auth_service.require_auth.return_value = {"csrf_hash": "synthetic"}
        self.auth_service.authenticated_session.return_value = {
            "csrf_hash": "synthetic"
        }
        self.routes = Mock()
        self.posts = Mock()
        self.posts.handle_before_auth.return_value = False
        self.posts.handle_before_maintenance.return_value = False
        self.logger = Mock()

        # A bare handler stub: only the attributes the verb methods read are set.
        handler: Any = RequestHandler.__new__(RequestHandler)
        handler.path = "/api/synthetic"
        handler.headers = {}
        handler.dependencies = SimpleNamespace(
            session_auth_service=lambda: self.auth_service,
            route_dispatcher=self.routes,
            post_dispatcher=self.posts,
            maintenance_gate=MaintenanceGate(),
            logger=self.logger,
            internal_server_error="internal",
            redact_text=lambda text: text,
        )
        handler.send_json = Mock()
        self.handler = handler

    def assert_busy_response(self) -> None:
        self.handler.send_json.assert_called_once()
        status, payload, headers = self.handler.send_json.call_args.args
        self.assertEqual(status, 503)
        self.assertEqual(
            payload,
            {
                "error": DATABASE_BUSY_MESSAGE,
                "reason": "database_busy",
                "request_id": self.handler.request_id,
                "retry_after_seconds": handler_module.DATABASE_BUSY_RETRY_AFTER_SECONDS,
            },
        )
        self.assertEqual(
            headers,
            {"Retry-After": str(handler_module.DATABASE_BUSY_RETRY_AFTER_SECONDS)},
        )
        # The busy resource is internal detail and never reaches the client.
        self.assertNotIn("writer", repr(payload))
        self.logger.exception.assert_not_called()

    def test_busy_writer_during_login_is_a_retryable_503(self) -> None:
        self.posts.handle_before_auth.side_effect = DatabaseBusyError("writer")
        self.handler.do_POST()
        self.assert_busy_response()

    def test_busy_database_on_an_authenticated_post_is_a_retryable_503(self) -> None:
        self.posts.handle_authenticated.side_effect = DatabaseBusyError("writer")
        self.handler.do_POST()
        self.assert_busy_response()

    def test_busy_reader_on_get_is_a_retryable_503(self) -> None:
        self.routes.handle_get.side_effect = DatabaseBusyError("reader")
        self.handler.do_GET()
        self.assert_busy_response()

    def test_busy_writer_on_put_is_a_retryable_503(self) -> None:
        self.routes.handle_put.side_effect = DatabaseBusyError("writer")
        self.handler.do_PUT()
        self.assert_busy_response()

    def test_other_failures_stay_an_internal_500(self) -> None:
        self.routes.handle_get.side_effect = RuntimeError("synthetic failure")
        self.handler.do_GET()
        self.handler.send_json.assert_called_once_with(500, {"error": "internal"})

    def test_rate_limit_errors_also_send_retry_after(self) -> None:
        self.routes.handle_get.side_effect = AppError(
            429, "limited", reason="rate_limited", retry_after_seconds=42
        )
        self.handler.do_GET()
        status, _, headers = self.handler.send_json.call_args.args
        self.assertEqual(status, 429)
        self.assertEqual(headers, {"Retry-After": "42"})


if __name__ == "__main__":
    unittest.main()
