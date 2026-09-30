from __future__ import annotations

import unittest
from unittest.mock import Mock

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

        for path in ("/api/logs/delete", "/api/logs/clear"):
            with self.subTest(path=path):
                self.handler.reset_mock()
                self.logs_service.clear.reset_mock()
                self.assertTrue(self.routes.handle(self.handler, path))
                self.logs_service.clear.assert_called_once_with()
                self.handler.send_json.assert_called_once_with(
                    200, {"ok": True, "cleared": True}
                )

    def test_diagnostics_delete_calls_service_and_returns_payload(self) -> None:
        self.report_service.clear.return_value = {"ok": True, "entries": 0}

        for path in ("/api/diagnostics/delete", "/api/diagnostics/clear"):
            with self.subTest(path=path):
                self.handler.reset_mock()
                self.report_service.clear.reset_mock()
                self.assertTrue(self.routes.handle(self.handler, path))
                self.report_service.clear.assert_called_once_with()
                self.handler.send_json.assert_called_once_with(
                    200, {"ok": True, "entries": 0}
                )

    def test_logs_delete_failure_raises_500_app_error(self) -> None:
        self.logs_service.clear.side_effect = OSError("disk full")
        with self.assertRaises(AppError) as raised:
            self.routes.handle(self.handler, "/api/logs/delete")
        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(
            raised.exception.message, "Logs konnten nicht gelöscht werden."
        )

    def test_diagnostics_delete_failure_raises_500_app_error(self) -> None:
        self.report_service.clear.side_effect = RuntimeError("database failure")
        with self.assertRaises(AppError) as raised:
            self.routes.handle(self.handler, "/api/diagnostics/delete")
        self.assertEqual(raised.exception.status, 500)
        self.assertEqual(
            raised.exception.message, "Diagnose konnte nicht gelöscht werden."
        )

    def test_unknown_path_returns_false_without_invoking_services(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/logs"))
        self.assertFalse(self.routes.handle(self.handler, "/api/diagnostics"))
        self.assertFalse(self.routes.handle(self.handler, "/api/other/delete"))
        self.factories["logs"].assert_not_called()
        self.factories["report"].assert_not_called()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
