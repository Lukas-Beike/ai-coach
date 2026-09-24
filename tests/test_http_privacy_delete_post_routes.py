from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.privacy_delete_post import PrivacyDeletePostRoutes


class PrivacyDeletePostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock()
        self.service.delete.return_value = {"status": "ok"}
        self.factory = Mock(return_value=self.service)
        self.routes = PrivacyDeletePostRoutes(self.factory)

    def handler(self, payload: object = None) -> Mock:
        handler = Mock()
        handler.read_json.return_value = payload or {"confirm": "LOKALE DATEN LÖSCHEN"}
        return handler

    def test_valid_request_reads_body_once_and_sends_service_result(self) -> None:
        handler = self.handler({"confirm": "LOKALE DATEN LÖSCHEN"})

        self.assertTrue(self.routes.handle(handler, "/api/privacy/delete"))

        handler.read_json.assert_called_once_with()
        self.factory.assert_called_once_with()
        self.service.delete.assert_called_once_with("LOKALE DATEN LÖSCHEN")
        handler.send_json.assert_called_once_with(200, {"status": "ok"})

    def test_service_error_propagates_without_sending_response(self) -> None:
        error = ValueError("confirmation rejected")
        self.service.delete.side_effect = error
        handler = self.handler({"confirm": "wrong"})

        with self.assertRaises(ValueError) as caught:
            self.routes.handle(handler, "/api/privacy/delete")

        self.assertIs(caught.exception, error)
        handler.read_json.assert_called_once_with()
        handler.send_json.assert_not_called()

    def test_unknown_path_has_no_side_effects(self) -> None:
        handler = self.handler()

        self.assertFalse(self.routes.handle(handler, "/api/privacy/delete/preview"))

        handler.read_json.assert_not_called()
        self.factory.assert_not_called()
        handler.send_json.assert_not_called()

    def test_each_request_resolves_service(self) -> None:
        handlers = [self.handler(), self.handler()]
        for handler in handlers:
            self.assertTrue(self.routes.handle(handler, "/api/privacy/delete"))

        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(self.service.delete.call_count, 2)


if __name__ == "__main__":
    unittest.main()
