"""Tests for the HTTP route table and the request handler's route order."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.handler import RequestHandler
from backend.http_api.route_table import Access, Route, RouteTable

SESSION = {"csrf_hash": "synthetic-csrf-hash"}


def route(method: str, path: str, access: Access = Access.SESSION_CSRF, **kw) -> Route:
    return Route(method, path, access, Mock(), **kw)


class RouteTableTests(unittest.TestCase):
    def test_match_finds_exact_and_parameter_routes_by_method(self) -> None:
        exact = route("GET", "/api/items", Access.SESSION)
        by_id = route("GET", "/api/items/{id}", Access.SESSION)
        by_name = route("POST", "/api/items/{id:[a-z]+}/rename")
        table = RouteTable([exact, by_id, by_name])

        for method, path, expected, params in (
            ("GET", "/api/items", exact, {}),
            ("GET", "/api/items/7", by_id, {"id": "7"}),
            ("POST", "/api/items/abc/rename", by_name, {"id": "abc"}),
            ("POST", "/api/items/ABC/rename", None, None),
            ("GET", "/api/items/7/extra", None, None),
            ("POST", "/api/items", None, None),
        ):
            with self.subTest(method=method, path=path):
                found = table.match(method, path)
                self.assertEqual(
                    found, None if expected is None else (expected, params)
                )

    def test_invalid_registrations_are_rejected(self) -> None:
        for build in (
            lambda: RouteTable([route("PUT", "/api/a"), route("PUT", "/api/a")]),
            lambda: RouteTable(
                [route("PUT", "/api/a/{id}"), route("PUT", "/api/a/{id}")]
            ),
            lambda: route("POST", "/api/unreviewed", Access.PUBLIC),
            lambda: route("PUT", "/api/login", Access.PUBLIC),
            lambda: route("POST", "/api/login", Access.SESSION_CSRF),
            lambda: route("GET", "/api/items", Access.SESSION_CSRF),
        ):
            with self.subTest(build=build), self.assertRaises(ValueError):
                build()


class RequestHandlerRouteOrderTests(unittest.TestCase):
    """What runs, in which order, around a route handler."""

    def make_handler(self, path: str, events: list[str]) -> Any:
        def recorded(name: str, result: Any = None) -> Any:
            def record(*_: Any) -> Any:
                events.append(name)
                return result

            return record

        @contextmanager
        def gate():
            events.append("gate")
            try:
                yield
            finally:
                events.append("gate end")

        def make(method: str, path: str, access: Access, **kw) -> Route:
            return Route(
                method, path, access, lambda *_: events.append(f"route {path}"), **kw
            )

        auth = Mock(
            require_auth=Mock(side_effect=recorded("auth", SESSION)),
            require_csrf=Mock(side_effect=recorded("csrf")),
            authenticated_session=Mock(side_effect=recorded("revalidate", SESSION)),
        )
        handler: Any = RequestHandler.__new__(RequestHandler)
        handler.path = path
        handler.headers = {}
        handler.dependencies = SimpleNamespace(
            session_auth_service=lambda: auth,
            route_table=RouteTable(
                [
                    make("POST", "/api/login", Access.PUBLIC, gated=False),
                    make("POST", "/api/ungated", Access.SESSION_CSRF, gated=False),
                    make("POST", "/api/gated", Access.SESSION_CSRF),
                    make("PUT", "/api/put", Access.SESSION_CSRF),
                ]
            ),
            maintenance_gate=SimpleNamespace(operation=gate),
            logger=Mock(),
            internal_server_error="internal",
        )
        handler._send_app_error = Mock()
        return handler

    def test_authentication_and_the_maintenance_gate_wrap_each_route(self) -> None:
        checked = ["auth", "csrf"]
        for verb, path, expected in (
            ("POST", "/api/login", ["route /api/login"]),
            ("POST", "/api/ungated", [*checked, "route /api/ungated"]),
            (
                "POST",
                "/api/gated",
                [
                    *checked,
                    "gate",
                    "revalidate",
                    "csrf",
                    "route /api/gated",
                    "gate end",
                ],
            ),
            (
                "POST",
                "/api/unknown",
                [*checked, "gate", "revalidate", "csrf", "gate end"],
            ),
            ("PUT", "/api/put", ["gate", *checked, "route /api/put", "gate end"]),
            ("PUT", "/api/unknown", ["gate", *checked, "gate end"]),
        ):
            with self.subTest(verb=verb, path=path):
                events: list[str] = []
                handler = self.make_handler(path, events)
                getattr(handler, f"do_{verb}")()
                self.assertEqual(events, expected)
                if path == "/api/unknown":
                    error = handler._send_app_error.call_args.args[0]
                    self.assertIsInstance(error, AppError)
                    self.assertEqual(error.status, 404)
                else:
                    handler._send_app_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
