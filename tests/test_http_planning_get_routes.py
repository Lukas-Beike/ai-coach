import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from support import dispatch_route

from backend.http_api.planning_get import PlanningGetRoutes


class PlanningGetRoutesTests(unittest.TestCase):
    def setUp(self):
        self.handler = SimpleNamespace(path="", send_json=Mock())
        self.plan = Mock()
        self.weather = Mock()
        self.library = Mock()
        self.routes = PlanningGetRoutes(
            Mock(return_value=self.plan),
            Mock(return_value=self.weather),
            Mock(return_value=self.library),
        )

    def test_plan_uses_first_local_value_and_returns_json(self):
        self.handler.path = "/api/plan?local=1&local=0"
        self.plan.read_public.return_value = {"plans": []}

        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/plan"))

        self.plan.read_public.assert_called_once_with(local_only=True)
        self.handler.send_json.assert_called_once_with(200, {"plans": []})
        self.weather.state.assert_not_called()
        self.library.page.assert_not_called()

    def test_weather_uses_first_local_value(self):
        self.handler.path = "/api/weather?local=0&local=1"
        self.weather.state.return_value = {"configured": True}

        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/weather"))

        self.weather.state.assert_called_once_with(local_only=False)
        self.handler.send_json.assert_called_once_with(200, {"configured": True})

    def test_library_passes_first_cursor_and_limit_values(self):
        self.handler.path = "/api/library?cursor=first&cursor=second&limit=7&limit=9"
        self.library.page.return_value = {"workouts": []}

        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/library"))

        self.library.page.assert_called_once_with("first", "7")
        self.handler.send_json.assert_called_once_with(200, {"workouts": []})

    def test_query_defaults_match_previous_handler_contract(self):
        self.handler.path = "/api/plan"
        self.plan.read_public.return_value = {"plans": []}
        dispatch_route(self.routes, self.handler, "/api/plan")
        self.plan.read_public.assert_called_once_with(local_only=False)

        self.handler.path = "/api/weather"
        dispatch_route(self.routes, self.handler, "/api/weather")
        self.weather.state.assert_called_once_with(local_only=False)

        self.handler.path = "/api/library"
        dispatch_route(self.routes, self.handler, "/api/library")
        self.library.page.assert_called_once_with(None, None)

    def test_unknown_route_resolves_no_factory(self):
        factories = [
            Mock(return_value=self.plan),
            Mock(return_value=self.weather),
            Mock(return_value=self.library),
        ]
        routes = PlanningGetRoutes(*factories)

        self.assertFalse(dispatch_route(routes, self.handler, "/api/unknown"))

        for factory in factories:
            factory.assert_not_called()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
