from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.diagnostics_post import DiagnosticsCapturePostRoutes


class DiagnosticsCapturePostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capture = Mock()
        self.handler = Mock()
        self.routes = DiagnosticsCapturePostRoutes(self.capture)

    def test_enabled_payload_is_applied_once_and_returned(self) -> None:
        result = {"active": True}
        self.handler.read_json.return_value = {"enabled": True}
        self.capture.set_enabled.return_value = result

        handled = self.routes.handle(self.handler, "/api/diagnostics/capture")

        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with()
        self.capture.set_enabled.assert_called_once_with(True)
        self.handler.send_json.assert_called_once_with(200, result)

    def test_disabled_payload_is_applied_and_returned(self) -> None:
        result = {"active": False}
        self.handler.read_json.return_value = {"enabled": False}
        self.capture.set_enabled.return_value = result

        handled = self.routes.handle(self.handler, "/api/diagnostics/capture")

        self.assertTrue(handled)
        self.capture.set_enabled.assert_called_once_with(False)
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/diagnostics"))

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        self.capture.set_enabled.assert_not_called()

    def test_capture_failure_propagates_without_response(self) -> None:
        self.handler.read_json.return_value = {"enabled": True}
        self.capture.set_enabled.side_effect = RuntimeError("synthetic capture failure")

        with self.assertRaisesRegex(RuntimeError, "synthetic capture failure"):
            self.routes.handle(self.handler, "/api/diagnostics/capture")

        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_not_called()

    def test_non_boolean_payload_value_is_forwarded_unchanged(self) -> None:
        result = {"active": False}
        self.handler.read_json.return_value = {"enabled": "synthetic-value"}
        self.capture.set_enabled.return_value = result

        self.routes.handle(self.handler, "/api/diagnostics/capture")

        self.capture.set_enabled.assert_called_once_with("synthetic-value")
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)


if __name__ == "__main__":
    unittest.main()
