from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend import change_history
from backend.http_api.history_get import HistoryGetRoutes


class HistoryGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = Mock()
        self.history = Mock()
        self.history.list.return_value = [{"id": "fake-change"}]
        self.auth_factory = Mock(return_value=self.auth)
        self.history_factory = Mock(return_value=self.history)
        self.routes = HistoryGetRoutes(self.auth_factory, self.history_factory)

    def handler(self, path: str) -> Mock:
        handler = Mock()
        handler.path = path
        return handler

    def test_returns_change_history_after_authentication(self) -> None:
        handler = self.handler("/api/change-history")

        self.assertTrue(self.routes.handle(handler, "/api/change-history"))

        self.auth.require_auth.assert_called_once_with(handler)
        self.history.list.assert_called_once_with(100)
        handler.send_json.assert_called_once_with(
            200, {"changes": [{"id": "fake-change"}]}
        )

    def test_query_limit_defaults_clamps_and_uses_first_value(self) -> None:
        cases = (
            ("/api/change-history", 100),
            ("/api/change-history?limit=0", 1),
            (f"/api/change-history?limit={change_history.MAX_ROWS + 5}", change_history.MAX_ROWS),
            ("/api/change-history?limit=7&limit=19", 7),
            ("/api/change-history?limit=invalid", 100),
        )
        for request_path, expected in cases:
            with self.subTest(request_path=request_path):
                self.history.list.reset_mock()
                self.routes.handle(self.handler(request_path), "/api/change-history")
                self.history.list.assert_called_once_with(expected)

    def test_auth_failure_prevents_query_parsing_and_service_access(self) -> None:
        denied = RuntimeError("unauthorized")
        self.auth.require_auth.side_effect = denied

        class Handler:
            @property
            def path(self) -> str:
                raise AssertionError("query must not be parsed before auth")

        with self.assertRaises(RuntimeError) as caught:
            self.routes.handle(Handler(), "/api/change-history")

        self.assertIs(caught.exception, denied)
        self.history_factory.assert_not_called()

    def test_unknown_path_does_not_resolve_factories(self) -> None:
        handler = self.handler("/api/change-history?limit=5")

        self.assertFalse(self.routes.handle(handler, "/api/unknown"))

        self.auth_factory.assert_not_called()
        self.history_factory.assert_not_called()
        handler.send_json.assert_not_called()

    def test_keep_alive_requests_resolve_current_auth_service_each_time(self) -> None:
        auth_instances = [Mock(), Mock()]
        auth_factory = Mock(side_effect=auth_instances)
        routes = HistoryGetRoutes(auth_factory, self.history_factory)

        for _ in range(2):
            routes.handle(self.handler("/api/change-history"), "/api/change-history")

        self.assertEqual(auth_factory.call_count, 2)
        for auth in auth_instances:
            auth.require_auth.assert_called_once()


if __name__ == "__main__":
    unittest.main()
