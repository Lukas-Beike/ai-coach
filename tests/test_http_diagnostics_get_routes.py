from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.diagnostics_get import DiagnosticsGetRoutes


class DiagnosticsGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.handler.path = "/api/logs"
        self.auth = Mock()
        self.logs = Mock()
        self.report = Mock()
        self.capture = Mock()
        self.factories = {
            "auth": Mock(return_value=self.auth),
            "logs": Mock(return_value=self.logs),
            "report": Mock(return_value=self.report),
        }
        self.routes = DiagnosticsGetRoutes(
            self.factories["auth"],
            self.factories["logs"],
            self.factories["report"],
            self.capture,
        )

    def test_routes_preserve_their_payloads(self) -> None:
        self.logs.list.return_value = ["recent"]
        self.report.report.return_value = {"status": "ok"}
        self.capture.status.return_value = {"enabled": False}
        cases = (
            ("/api/logs", {"entries": ["recent"]}),
            ("/api/diagnostics", {"status": "ok"}),
            ("/api/diagnostics/capture", {"enabled": False}),
        )
        for path, payload in cases:
            with self.subTest(path=path):
                self.handler.reset_mock()
                self.assertTrue(self.routes.handle(self.handler, path))
                self.handler.send_json.assert_called_once_with(200, payload)

    def test_log_limit_defaults_clamps_and_uses_first_query_value(self) -> None:
        cases = (
            ("/api/logs", 200),
            ("/api/logs?limit=0", 1),
            ("/api/logs?limit=900", 500),
            ("/api/logs?limit=bad", 200),
            ("/api/logs?limit=17&limit=499", 17),
        )
        for request_path, expected_limit in cases:
            with self.subTest(request_path=request_path):
                self.handler.path = request_path
                self.logs.list.reset_mock()
                self.assertTrue(self.routes.handle(self.handler, "/api/logs"))
                self.logs.list.assert_called_once_with(expected_limit)

    def test_auth_failure_precedes_every_service_and_capture_action(self) -> None:
        denied = PermissionError("unauthorized")
        self.auth.require_auth.side_effect = denied
        for path in (
            "/api/logs",
            "/api/diagnostics",
            "/api/diagnostics/capture",
        ):
            with self.subTest(path=path):
                with self.assertRaises(PermissionError) as caught:
                    self.routes.handle(self.handler, path)
                self.assertIs(caught.exception, denied)
        self.factories["logs"].assert_not_called()
        self.factories["report"].assert_not_called()
        self.capture.status.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_unknown_route_does_not_resolve_factories_or_capture(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/diagnostics/unknown"))
        for factory in self.factories.values():
            factory.assert_not_called()
        self.capture.status.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_keep_alive_requests_resolve_auth_service_for_each_request(self) -> None:
        first_auth = Mock()
        second_auth = Mock()
        self.factories["auth"].side_effect = (first_auth, second_auth)

        self.assertTrue(self.routes.handle(self.handler, "/api/logs"))
        self.assertTrue(self.routes.handle(self.handler, "/api/diagnostics"))

        self.assertEqual(self.factories["auth"].call_count, 2)
        first_auth.require_auth.assert_called_once_with(self.handler)
        second_auth.require_auth.assert_called_once_with(self.handler)


if __name__ == "__main__":
    unittest.main()
