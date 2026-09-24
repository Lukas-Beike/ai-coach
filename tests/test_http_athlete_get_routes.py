from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.http_api.athlete_get import AthleteGetRoutes


class AthleteGetRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.auth = Mock()
        self.performance = Mock()
        self.profile = Mock()
        self.competitions = Mock()
        self.feedback = Mock()
        self.preview = Mock()
        self.settings = Mock()
        self.factories = {
            "auth": Mock(return_value=self.auth),
            "performance": Mock(return_value=self.performance),
            "profile": Mock(return_value=self.profile),
            "competitions": Mock(return_value=self.competitions),
            "feedback": Mock(return_value=self.feedback),
            "preview": Mock(return_value=self.preview),
        }
        self.routes = AthleteGetRoutes(
            self.factories["auth"],
            self.factories["performance"],
            self.factories["profile"],
            self.factories["competitions"],
            self.factories["feedback"],
            self.factories["preview"],
            self.settings,
        )

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
                self.assertTrue(self.routes.handle(self.handler, path))
                self.handler.send_json.assert_called_once_with(200, expected_payload)
        self.competitions.list.assert_called_once_with(limit=100)

    def test_context_preview_uses_current_provider_selection(self) -> None:
        providers = iter(("openai", "gemini"))
        self.settings.selected_ai_provider.side_effect = lambda: next(providers)
        self.preview.preview.side_effect = lambda provider: {"provider": provider}

        for expected_provider in ("openai", "gemini"):
            self.handler.reset_mock()
            self.assertTrue(self.routes.handle(self.handler, "/api/context-preview"))
            self.preview.preview.assert_called_with(expected_provider)
            self.handler.send_json.assert_called_once_with(
                200, {"provider": expected_provider}
            )

        self.assertEqual(self.factories["preview"].call_count, 2)

    def test_keep_alive_requests_resolve_auth_service_again(self) -> None:
        first_auth = Mock()
        second_auth = Mock()
        self.factories["auth"].side_effect = (first_auth, second_auth)

        self.assertTrue(self.routes.handle(self.handler, "/api/performance"))
        self.assertTrue(self.routes.handle(self.handler, "/api/feedback"))

        self.assertEqual(self.factories["auth"].call_count, 2)
        first_auth.require_auth.assert_called_once_with(self.handler)
        second_auth.require_auth.assert_called_once_with(self.handler)

    def test_unknown_route_returns_false_without_resolving_any_factory(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/not-an-athlete-read"))
        for factory in self.factories.values():
            factory.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_auth_failure_prevents_data_and_settings_resolution_or_response(self) -> None:
        self.auth.require_auth.side_effect = PermissionError("unauthorized")

        with self.assertRaisesRegex(PermissionError, "unauthorized"):
            self.routes.handle(self.handler, "/api/context-preview")

        self.factories["auth"].assert_called_once_with()
        for name in ("performance", "profile", "competitions", "feedback", "preview"):
            self.factories[name].assert_not_called()
        self.settings.selected_ai_provider.assert_not_called()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
