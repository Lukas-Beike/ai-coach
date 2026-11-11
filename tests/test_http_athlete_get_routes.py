from __future__ import annotations

import unittest
from unittest.mock import Mock

from support import dispatch_route

from backend.http_api.athlete_get import AthleteGetRoutes


class AthleteGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.performance = Mock()
        self.profile = Mock()
        self.competitions = Mock()
        self.feedback = Mock()
        self.preview = Mock()
        self.settings = Mock()
        self.factories = {
            "performance": Mock(return_value=self.performance),
            "profile": Mock(return_value=self.profile),
            "competitions": Mock(return_value=self.competitions),
            "feedback": Mock(return_value=self.feedback),
            "preview": Mock(return_value=self.preview),
        }
        self.routes = AthleteGetRoutes(
            self.factories["performance"],
            self.factories["profile"],
            self.factories["competitions"],
            self.factories["feedback"],
            self.factories["preview"],
            self.settings,
        )

    def test_zones_need_the_zone_service(self) -> None:
        self.assertFalse(dispatch_route(self.routes, self.handler, "/api/zones"))
        zones = Mock()
        zones.read.return_value = {"configurations": []}
        routes = AthleteGetRoutes(
            self.factories["performance"],
            self.factories["profile"],
            self.factories["competitions"],
            self.factories["feedback"],
            self.factories["preview"],
            self.settings,
            Mock(return_value=zones),
        )
        self.assertTrue(dispatch_route(routes, self.handler, "/api/zones"))
        self.handler.send_json.assert_called_once_with(200, {"configurations": []})

    def test_each_route_preserves_its_response_payload(self) -> None:
        self.performance.performance_state.return_value = {"metrics": {"ftp": 250}}
        self.profile.get.return_value = {"name": "Test Athlete"}
        self.competitions.list.return_value = [{"name": "Test Race"}]
        self.feedback.feedback_state.return_value = {"feedback": []}
        cases = (
            ("/api/performance", {"metrics": {"ftp": 250}}),
            (
                "/api/profile",
                {
                    "profile": {"name": "Test Athlete"},
                    "competitions": [{"name": "Test Race"}],
                },
            ),
            ("/api/feedback", {"feedback": []}),
        )
        for path, expected_payload in cases:
            with self.subTest(path=path):
                self.handler.reset_mock()
                self.assertTrue(dispatch_route(self.routes, self.handler, path))
                self.handler.send_json.assert_called_once_with(200, expected_payload)
        self.competitions.list.assert_called_once_with(limit=100)

    def test_context_preview_uses_openai_contract(self) -> None:
        self.preview.preview.return_value = {"context": "synthetic"}

        self.assertTrue(dispatch_route(self.routes, self.handler, "/api/context-preview"))

        self.preview.preview.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, {"context": "synthetic"})
        self.assertEqual(self.factories["preview"].call_count, 1)

    def test_unknown_route_returns_false_without_resolving_any_factory(self) -> None:
        self.assertFalse(dispatch_route(self.routes, self.handler, "/api/not-an-athlete-read"))
        for factory in self.factories.values():
            factory.assert_not_called()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
