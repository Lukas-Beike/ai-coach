from __future__ import annotations

import unittest
from unittest.mock import Mock

from support import dispatch_route

from backend.errors import AppError
from backend.http_api.settings_put import SettingsPutRoutes


class SettingsPutRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Mock()
        self.handler = Mock()
        self.routes = SettingsPutRoutes(self.settings)

    def test_model_route_passes_model_field(self) -> None:
        self.handler.read_json.return_value = {"model": "gpt-6-luna"}
        self.settings.save_model.return_value = {"model": "gpt-6-luna"}

        self.assertTrue(
            dispatch_route(
                self.routes, self.handler, "/api/settings/model", method="PUT"
            )
        )

        # Without a task the conversation choice is saved.
        self.settings.save_model.assert_called_once_with("gpt-6-luna", "conversation")
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, {"model": "gpt-6-luna"})

    def test_thinking_level_route_passes_thinking_level_field(self) -> None:
        self.handler.read_json.return_value = {"thinking_level": "high"}
        self.settings.save_thinking_level.return_value = {"thinking_level": "high"}

        self.assertTrue(
            dispatch_route(
                self.routes, self.handler, "/api/settings/thinking-level", method="PUT"
            )
        )

        self.settings.save_thinking_level.assert_called_once_with(
            "high", "conversation"
        )
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, {"thinking_level": "high"})

    def test_model_and_thinking_routes_pass_the_task(self) -> None:
        for path, field, save in (
            ("/api/settings/model", "model", self.settings.save_model),
            (
                "/api/settings/thinking-level",
                "thinking_level",
                self.settings.save_thinking_level,
            ),
        ):
            with self.subTest(path=path):
                self.handler.read_json.return_value = {field: "x", "task": "planning"}
                dispatch_route(self.routes, self.handler, path, method="PUT")
                save.assert_called_once_with("x", "planning")

    def test_calendar_display_route_passes_whole_payload(self) -> None:
        payload = {"past_weeks": 3, "future_weeks": 7}
        self.handler.read_json.return_value = payload
        result = {"status": "ok", **payload}
        self.settings.save_calendar_display_settings.return_value = result

        self.assertTrue(
            dispatch_route(
                self.routes,
                self.handler,
                "/api/settings/calendar-display",
                method="PUT",
            )
        )

        self.settings.save_calendar_display_settings.assert_called_once_with(payload)
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        self.assertFalse(
            dispatch_route(
                self.routes, self.handler, "/api/settings/unknown", method="PUT"
            )
        )

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        for save in (
            self.settings.save_model,
            self.settings.save_thinking_level,
            self.settings.save_calendar_display_settings,
        ):
            save.assert_not_called()

    def test_settings_errors_propagate_without_response(self) -> None:
        self.handler.read_json.return_value = {"model": "invalid"}
        self.settings.save_model.side_effect = AppError(400, "invalid model")

        with self.assertRaisesRegex(AppError, "invalid model"):
            dispatch_route(
                self.routes, self.handler, "/api/settings/model", method="PUT"
            )

        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
