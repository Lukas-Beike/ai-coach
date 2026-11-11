from __future__ import annotations

import unittest
from unittest.mock import Mock

from support import dispatch_route

from backend.errors import AppError
from backend.http_api.diagnostics_delete_post import DiagnosticsDeletePostRoutes


class DiagnosticsDeletePostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.logs_service = Mock()
        self.report_service = Mock()
        self.factories = {
            "logs": Mock(return_value=self.logs_service),
            "report": Mock(return_value=self.report_service),
        }
        self.routes = DiagnosticsDeletePostRoutes(
            self.factories["logs"],
            self.factories["report"],
        )

    def test_logs_delete_calls_service_and_returns_payload(self) -> None:
        self.logs_service.clear.return_value = {"ok": True, "cleared": True}

        self.assertTrue(
            dispatch_route(self.routes, self.handler, "/api/logs/delete", method="POST")
        )
        self.logs_service.clear.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "cleared": True}
        )

    def test_diagnostics_delete_calls_service_and_returns_payload(self) -> None:
        self.report_service.clear.return_value = {"ok": True, "entries": 0}

        self.assertTrue(
            dispatch_route(
                self.routes, self.handler, "/api/diagnostics/delete", method="POST"
            )
        )
        self.report_service.clear.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, {"ok": True, "entries": 0})

    def test_logs_delete_failure_raises_500_app_error(self) -> None:
        self.logs_service.clear.side_effect = OSError("disk full")
        with self.assertRaises(AppError) as raised:
            dispatch_route(self.routes, self.handler, "/api/logs/delete", method="POST")
        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(
            raised.exception.message, "Logs konnten nicht gelöscht werden."
        )

    def test_diagnostics_delete_failure_raises_500_app_error(self) -> None:
        self.report_service.clear.side_effect = RuntimeError("database failure")
        with self.assertRaises(AppError) as raised:
            dispatch_route(
                self.routes, self.handler, "/api/diagnostics/delete", method="POST"
            )
        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(
            raised.exception.message, "Diagnose konnte nicht gelöscht werden."
        )

    def test_unknown_path_returns_false_without_invoking_services(self) -> None:
        self.assertFalse(
            dispatch_route(self.routes, self.handler, "/api/logs", method="POST")
        )
        self.assertFalse(
            dispatch_route(self.routes, self.handler, "/api/diagnostics", method="POST")
        )
        self.assertFalse(
            dispatch_route(self.routes, self.handler, "/api/logs/clear", method="POST")
        )
        self.assertFalse(
            dispatch_route(
                self.routes, self.handler, "/api/diagnostics/clear", method="POST"
            )
        )
        self.assertFalse(
            dispatch_route(
                self.routes, self.handler, "/api/other/delete", method="POST"
            )
        )
        self.factories["logs"].assert_not_called()
        self.factories["report"].assert_not_called()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
