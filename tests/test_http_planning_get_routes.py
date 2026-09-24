import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.http_api.planning_get import PlanningGetRoutes


class PlanningGetRoutesTests(unittest.TestCase):
    def setUp(self):
        self.handler = SimpleNamespace(path="", send_json=Mock())
        self.auth = Mock()
        self.plan = Mock()
        self.weather = Mock()
        self.library = Mock()
        self.routes = PlanningGetRoutes(
            Mock(return_value=self.auth),
            Mock(return_value=self.plan),
            Mock(return_value=self.weather),
            Mock(return_value=self.library),
        )

    def test_plan_uses_first_local_value_and_returns_json(self):
        self.handler.path = "/api/plan?local=1&local=0"
        self.plan.read.return_value = {"plans": []}

        self.assertTrue(self.routes.handle(self.handler, "/api/plan"))

        self.auth.require_auth.assert_called_once_with(self.handler)
        self.plan.read.assert_called_once_with(local_only=True)
        self.handler.send_json.assert_called_once_with(200, {"plans": []})
        self.weather.state.assert_not_called()
        self.library.page.assert_not_called()

    def test_weather_uses_first_local_value(self):
        self.handler.path = "/api/weather?local=0&local=1"
        self.weather.state.return_value = {"configured": True}

        self.assertTrue(self.routes.handle(self.handler, "/api/weather"))

        self.auth.require_auth.assert_called_once_with(self.handler)
        self.weather.state.assert_called_once_with(local_only=False)
        self.handler.send_json.assert_called_once_with(200, {"configured": True})

    def test_library_passes_first_cursor_and_limit_values(self):
        self.handler.path = "/api/library?cursor=first&cursor=second&limit=7&limit=9"
        self.library.page.return_value = {"workouts": []}

        self.assertTrue(self.routes.handle(self.handler, "/api/library"))

        self.auth.require_auth.assert_called_once_with(self.handler)
        self.library.page.assert_called_once_with("first", "7")
        self.handler.send_json.assert_called_once_with(200, {"workouts": []})

    def test_query_defaults_match_previous_handler_contract(self):
        self.handler.path = "/api/plan"
        self.plan.read.return_value = {"plans": []}
        self.routes.handle(self.handler, "/api/plan")
        self.plan.read.assert_called_once_with(local_only=False)

        self.handler.path = "/api/weather"
        self.routes.handle(self.handler, "/api/weather")
        self.weather.state.assert_called_once_with(local_only=False)

        self.handler.path = "/api/library"
        self.routes.handle(self.handler, "/api/library")
        self.library.page.assert_called_once_with(None, None)

    def test_auth_failure_stops_before_data_service_and_response(self):
        error = RuntimeError("unauthorized")
        self.auth.require_auth.side_effect = error
        self.handler.path = "/api/plan"

        with self.assertRaisesRegex(RuntimeError, "unauthorized"):
            self.routes.handle(self.handler, "/api/plan")

        self.auth.require_auth.assert_called_once_with(self.handler)
        self.plan.read.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_unknown_route_resolves_no_factory(self):
        factories = [
            Mock(return_value=self.auth),
            Mock(return_value=self.plan),
            Mock(return_value=self.weather),
            Mock(return_value=self.library),
        ]
        routes = PlanningGetRoutes(*factories)

        self.assertFalse(routes.handle(self.handler, "/api/unknown"))

        for factory in factories:
            factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_auth_factory_is_resolved_again_for_each_request(self):
        first_auth = Mock()
        second_auth = Mock()
        auth_factory = Mock(side_effect=[first_auth, second_auth])
        routes = PlanningGetRoutes(
            auth_factory,
            Mock(return_value=self.plan),
            Mock(return_value=self.weather),
            Mock(return_value=self.library),
        )
        self.handler.path = "/api/weather"

        self.assertTrue(routes.handle(self.handler, "/api/weather"))
        self.assertTrue(routes.handle(self.handler, "/api/weather"))

        self.assertEqual(auth_factory.call_count, 2)
        first_auth.require_auth.assert_called_once_with(self.handler)
        second_auth.require_auth.assert_called_once_with(self.handler)


if __name__ == "__main__":
    unittest.main()
