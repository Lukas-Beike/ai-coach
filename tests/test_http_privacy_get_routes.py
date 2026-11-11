from __future__ import annotations

import unittest
from unittest.mock import Mock

from support import dispatch_route

from backend.http_api.privacy_get import PrivacyGetRoutes


class PrivacyGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = Mock()
        self.delete_service = Mock()
        self.delete_service.preview.return_value = {"status": "preview"}
        self.transport_factory = Mock(return_value=self.transport)
        self.delete_factory = Mock(return_value=self.delete_service)
        self.routes = PrivacyGetRoutes(self.transport_factory, self.delete_factory)

    def handler(self, path: str = "/") -> Mock:
        handler = Mock()
        handler.path = path
        return handler

    def test_export_and_backup_use_existing_stream_transport(self) -> None:
        cases = (
            ("/api/privacy/export", "stream_privacy_export"),
            ("/api/privacy/backup", "stream_database_backup"),
        )
        for path, method in cases:
            with self.subTest(path=path):
                handler = self.handler(path)

                self.assertTrue(dispatch_route(self.routes, handler, path))

                getattr(self.transport, method).assert_called_once_with(handler)
                self.transport_factory.assert_called_once_with()
                self.delete_factory.assert_not_called()
                self.transport.reset_mock()
                self.transport_factory.reset_mock()

    def test_preview_returns_service_payload_and_status(self) -> None:
        handler = self.handler("/api/privacy/delete/preview")

        self.assertTrue(dispatch_route(self.routes, handler, "/api/privacy/delete/preview"))

        self.delete_factory.assert_called_once_with()
        self.delete_service.preview.assert_called_once_with()
        handler.send_json.assert_called_once_with(200, {"status": "preview"})
        self.transport_factory.assert_not_called()

    def test_unknown_path_does_not_resolve_privacy_services(self) -> None:
        handler = self.handler("/api/unknown")

        self.assertFalse(dispatch_route(self.routes, handler, "/api/unknown"))

        self.transport_factory.assert_not_called()
        self.delete_factory.assert_not_called()
        handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
