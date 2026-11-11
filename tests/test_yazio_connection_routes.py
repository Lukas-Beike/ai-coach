"""Focused route contract for the local Yazio status and check."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from support import dispatch_route

from backend.errors import AppError
from backend.http_api.handler import RequestHandler
from backend.http_api.nutrition import NutritionGetRoutes, NutritionPostRoutes
from backend.http_api.route_table import RouteTable
from backend.runtime.maintenance import MaintenanceGate


class YazioRouteTests(unittest.TestCase):
    def test_check_requires_session_and_csrf_before_dispatch(self):
        auth = Mock()
        session = {"csrf_hash": "synthetic"}
        auth.require_auth.return_value = session
        auth.authenticated_session.return_value = session
        food = Mock()
        nutrition = NutritionPostRoutes(
            Mock(), lambda: SimpleNamespace(food_database=food)
        )
        handler = RequestHandler.__new__(RequestHandler)
        handler.path = "/api/nutrition/yazio/check"
        handler.headers = {}
        handler.dependencies = SimpleNamespace(
            session_auth_service=lambda: auth,
            route_table=RouteTable(nutrition.routes()),
            maintenance_gate=MaintenanceGate(),
            logger=Mock(),
            internal_server_error="internal",
        )
        handler._send_app_error = Mock()
        handler.read_json = Mock(return_value={})
        handler.send_json = Mock()
        for failed in ("session", "csrf"):
            with self.subTest(failed=failed):
                auth.require_auth.side_effect = (
                    AppError(401, "unauthorized") if failed == "session" else None
                )
                auth.require_csrf.side_effect = (
                    AppError(403, "forbidden") if failed == "csrf" else None
                )
                handler.do_POST()
                food.check_yazio_connection.assert_not_called()
        auth.require_csrf.side_effect = None
        handler.do_POST()
        food.check_yazio_connection.assert_called_once()

    def test_status_only_reads_local_state(self):
        food = Mock()
        library = lambda: SimpleNamespace(food_database=food)
        routes = NutritionGetRoutes(Mock(), library, Mock())
        handler = Mock()
        food.yazio_connection_status.return_value = {
            "status": "unchecked",
            "checked_at": None,
        }
        self.assertTrue(dispatch_route(routes, handler, "/api/nutrition/yazio/status"))
        food.check_yazio_connection.assert_not_called()
        handler.send_json.assert_called_once_with(
            200, {"status": "unchecked", "checked_at": None}
        )

    def test_check_dispatches_to_shared_food_database(self):
        food = Mock()
        food.check_yazio_connection.return_value = {
            "status": "success",
            "checked_at": "time",
        }
        routes = NutritionPostRoutes(
            Mock(), lambda: SimpleNamespace(food_database=food)
        )
        handler = Mock()
        self.assertTrue(
            dispatch_route(routes, handler, "/api/nutrition/yazio/check", method="POST")
        )
        food.check_yazio_connection.assert_called_once_with()
        handler.send_json.assert_called_once_with(
            200, {"status": "success", "checked_at": "time"}
        )


if __name__ == "__main__":
    unittest.main()
