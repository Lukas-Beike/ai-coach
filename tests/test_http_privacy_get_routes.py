from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.privacy_get import PrivacyGetRoutes


class PrivacyGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = Mock()
        self.transport = Mock()
        self.delete_service = Mock()
        self.delete_service.preview.return_value = {"status": "preview"}
        self.auth_factory = Mock(return_value=self.auth)
        self.transport_factory = Mock(return_value=self.transport)
        self.delete_factory = Mock(return_value=self.delete_service)
        self.routes = PrivacyGetRoutes(
            self.auth_factory, self.transport_factory, self.delete_factory
        )

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

                self.assertTrue(self.routes.handle(handler, path))

                self.auth.require_auth.assert_called_once_with(handler)
                getattr(self.transport, method).assert_called_once_with(handler)
                self.transport_factory.assert_called_once_with()
                self.delete_factory.assert_not_called()
                self.auth.reset_mock()
                self.transport.reset_mock()
                self.transport_factory.reset_mock()

    def test_preview_returns_service_payload_and_status(self) -> None:
        handler = self.handler("/api/privacy/delete/preview")

        self.assertTrue(self.routes.handle(handler, "/api/privacy/delete/preview"))

        self.auth.require_auth.assert_called_once_with(handler)
        self.delete_factory.assert_called_once_with()
        self.delete_service.preview.assert_called_once_with()
        handler.send_json.assert_called_once_with(200, {"status": "preview"})
        self.transport_factory.assert_not_called()

    def test_auth_denial_precedes_all_privacy_services(self) -> None:
        for path in (
            "/api/privacy/export",
            "/api/privacy/delete/preview",
            "/api/privacy/backup",
        ):
            with self.subTest(path=path):
                denied = RuntimeError("unauthorized")
                auth = Mock()
                auth.require_auth.side_effect = denied
                auth_factory = Mock(return_value=auth)
                transport = Mock()
                transport_factory = Mock(return_value=transport)
                delete_service = Mock()
                delete_factory = Mock(return_value=delete_service)
                handler = self.handler(path)
                routes = PrivacyGetRoutes(
                    auth_factory, transport_factory, delete_factory
                )

                with self.assertRaises(RuntimeError) as caught:
                    routes.handle(handler, path)

                self.assertIs(caught.exception, denied)
                auth.require_auth.assert_called_once_with(handler)
                auth_factory.assert_called_once_with()
                transport_factory.assert_not_called()
                delete_factory.assert_not_called()
                transport.stream_privacy_export.assert_not_called()
                transport.stream_database_backup.assert_not_called()
                delete_service.preview.assert_not_called()
                handler.send_json.assert_not_called()

    def test_unknown_path_does_not_resolve_auth_or_privacy_services(self) -> None:
        handler = self.handler("/api/unknown")

        self.assertFalse(self.routes.handle(handler, "/api/unknown"))

        self.auth_factory.assert_not_called()
        self.transport_factory.assert_not_called()
        self.delete_factory.assert_not_called()
        handler.send_json.assert_not_called()

    def test_repeated_requests_resolve_the_current_auth_service(self) -> None:
        auth_instances = [Mock(), Mock()]
        auth_factory = Mock(side_effect=auth_instances)
        routes = PrivacyGetRoutes(
            auth_factory, self.transport_factory, self.delete_factory
        )

        for _ in auth_instances:
            routes.handle(self.handler("/api/privacy/delete/preview"), "/api/privacy/delete/preview")

        self.assertEqual(auth_factory.call_count, 2)
        for auth in auth_instances:
            auth.require_auth.assert_called_once()


if __name__ == "__main__":
    unittest.main()
