"""Tests for shared HTTP route ordering and fallback behavior."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.route_dispatch import HttpRouteDispatcher


class HttpRouteDispatcherTests(unittest.TestCase):
    def test_put_uses_ordered_concrete_routes_and_returns_404(self) -> None:
        handler = Mock()
        first, second = Mock(), Mock()
        first.handle.return_value = False
        second.handle.return_value = True
        dispatcher = HttpRouteDispatcher((first, second))

        dispatcher.handle_put(handler, "/api/profile")

        first.handle.assert_called_once_with(handler, "/api/profile")
        second.handle.assert_called_once_with(handler, "/api/profile")

        second.handle.return_value = False
        with self.assertRaises(AppError) as raised:
            dispatcher.handle_put(handler, "/api/missing")
        self.assertEqual(raised.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
