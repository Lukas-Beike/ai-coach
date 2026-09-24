from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.settings_put import SettingsPutRoutes


class SettingsPutRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Mock()
        self.handler = Mock()
        self.routes = SettingsPutRoutes(self.settings)

    def test_model_route_passes_model_field(self) -> None:
        self.handler.read_json.return_value = {"model": "gpt-5.6-sol"}
        self.settings.save_model.return_value = {"model": "gpt-5.6-sol"}

        self.assertTrue(self.routes.handle(self.handler, "/api/settings/model"))

        self.settings.save_model.assert_called_once_with("gpt-5.6-sol")
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, {"model": "gpt-5.6-sol"})

    def test_ai_provider_route_passes_provider_field(self) -> None:
        self.handler.read_json.return_value = {"provider": "gemini"}
        result = {"provider": "gemini", "model": "gemini-3.8-flash"}
        self.settings.save_ai_provider.return_value = result

        self.assertTrue(self.routes.handle(self.handler, "/api/settings/ai-provider"))

        self.settings.save_ai_provider.assert_called_once_with("gemini")
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_thinking_level_route_passes_thinking_level_field(self) -> None:
        self.handler.read_json.return_value = {"thinking_level": "high"}
        self.settings.save_thinking_level.return_value = {"thinking_level": "high"}

        self.assertTrue(self.routes.handle(self.handler, "/api/settings/thinking-level"))

        self.settings.save_thinking_level.assert_called_once_with("high")
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, {"thinking_level": "high"})

    def test_calendar_display_route_passes_whole_payload(self) -> None:
        payload = {"past_weeks": 3, "future_weeks": 7}
        self.handler.read_json.return_value = payload
        result = {"status": "ok", **payload}
        self.settings.save_calendar_display_settings.return_value = result

        self.assertTrue(self.routes.handle(self.handler, "/api/settings/calendar-display"))

        self.settings.save_calendar_display_settings.assert_called_once_with(payload)
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/settings/unknown"))

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        for save in (
            self.settings.save_model,
            self.settings.save_ai_provider,
            self.settings.save_thinking_level,
            self.settings.save_calendar_display_settings,
        ):
            save.assert_not_called()

    def test_settings_errors_propagate_without_response(self) -> None:
        self.handler.read_json.return_value = {"model": "invalid"}
        self.settings.save_model.side_effect = AppError(400, "invalid model")

        with self.assertRaisesRegex(AppError, "invalid model"):
            self.routes.handle(self.handler, "/api/settings/model")

        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
