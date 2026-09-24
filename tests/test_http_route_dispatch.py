"""Tests for shared HTTP route ordering and fallback behavior."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.route_dispatch import HttpRouteDispatcher


class HttpRouteDispatcherTests(unittest.TestCase):
    def test_get_stops_after_first_route_and_does_not_serve_static(self) -> None:
        handler = Mock()
        first = Mock()
        first.handle.return_value = False
        second = Mock()
        second.handle.return_value = True
        third = Mock()
        dispatcher = HttpRouteDispatcher((first, second, third), ())

        dispatcher.handle_get(handler, "/api/known")

        first.handle.assert_called_once_with(handler, "/api/known")
        second.handle.assert_called_once_with(handler, "/api/known")
        third.handle.assert_not_called()
        handler.send_static.assert_not_called()

    def test_get_sends_non_api_fallback_to_static(self) -> None:
        handler = Mock()
        route = Mock()
        route.handle.return_value = False

        HttpRouteDispatcher((route,), ()).handle_get(handler, "/offline.html")

        handler.send_static.assert_called_once_with("/offline.html")

    def test_unmatched_api_path_returns_404(self) -> None:
        handler = Mock()
        route = Mock()
        route.handle.return_value = False

        with self.assertRaises(AppError) as raised:
            HttpRouteDispatcher((route,), ()).handle_get(handler, "/api/missing")

        self.assertEqual(raised.exception.status, 404)
        handler.send_static.assert_not_called()

    def test_put_uses_ordered_concrete_routes_and_returns_404(self) -> None:
        handler = Mock()
        first, second = Mock(), Mock()
        first.handle.return_value = False
        second.handle.return_value = True
        dispatcher = HttpRouteDispatcher((), (first, second))

        dispatcher.handle_put(handler, "/api/profile")

        first.handle.assert_called_once_with(handler, "/api/profile")
        second.handle.assert_called_once_with(handler, "/api/profile")

        second.handle.return_value = False
        with self.assertRaises(AppError) as raised:
            dispatcher.handle_put(handler, "/api/missing")
        self.assertEqual(raised.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
