"""Authenticated local settings PUT routes."""

from __future__ import annotations

from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.settings import SettingsService


class SettingsPutRoutes:
    """Dispatch local settings writes through the settings state owner."""

    def __init__(self, settings: SettingsService) -> None:
        self._settings = settings

    def routes(self) -> list[Route]:
        return [
            Route("PUT", "/api/settings/model", Access.SESSION_CSRF, self._model),
            Route(
                "PUT",
                "/api/settings/service-tier",
                Access.SESSION_CSRF,
                self._service_tier,
            ),
            Route(
                "PUT",
                "/api/settings/thinking-level",
                Access.SESSION_CSRF,
                self._thinking_level,
            ),
            Route(
                "PUT",
                "/api/settings/calendar-display",
                Access.SESSION_CSRF,
                self._calendar,
            ),
        ]

    def _model(self, handler: Any, _request: RouteRequest) -> None:
        """Select the Coach model.

        Request: JSON body `{"model": string}`. `model` is `claude-opus`,
        `claude-sonnet`, `claude-haiku`, the model configured in the environment,
        or, with the default OpenAI base URL, `gpt-6-luna`, `gpt-6-sol`,
        `gpt-6.1-sol` or `gpt-6-astra`.

        Response: 200 `{"model": string}`.

        Errors: 400 "Nicht unterstützte Modellauswahl."; 400 "Für dieses Modell
        fehlt der API-Schlüssel unter Mehr › Anbindungen." when the model's provider
        has no key.
        """
        handler.send_json(
            200, self._settings.save_model(handler.read_json().get("model"))
        )

    def _service_tier(self, handler: Any, _request: RouteRequest) -> None:
        """Select the OpenAI service tier.

        Request: JSON body `{"service_tier": string}`, case-insensitive: `default`,
        `fast` or `ultrafast`, as far as the selected model supports it. `fast` needs
        `gpt-6-luna`, `gpt-6-sol`, `gpt-6.1-sol` or `gpt-6-astra`, `ultrafast`
        `gpt-6.1-sol` or `gpt-6-astra`; with a custom OpenAI base URL or any other
        model only `default`.

        Response: 200 `{"service_tier": string}`.

        Errors: 400 "Nicht unterstützter Geschwindigkeitsmodus für dieses Modell.".
        """
        handler.send_json(
            200,
            self._settings.save_service_tier(handler.read_json().get("service_tier")),
        )

    def _thinking_level(self, handler: Any, _request: RouteRequest) -> None:
        """Select the thinking level.

        Request: JSON body `{"thinking_level": string}`, case-insensitive: `low`,
        `medium` or `high`.

        Response: 200 `{"thinking_level": string}`.

        Errors: 400 "Nicht unterstütztes Thinking Level.".
        """
        handler.send_json(
            200,
            self._settings.save_thinking_level(
                handler.read_json().get("thinking_level")
            ),
        )

    def _calendar(self, handler: Any, _request: RouteRequest) -> None:
        """Update the calendar display settings.

        Request: JSON body `{"past_weeks": integer, "future_weeks": integer}`, each
        0 to 52, at least one required; a field not sent keeps its value.

        Response: 200 `{"status": "ok", "past_weeks": integer, "future_weeks":
        integer}` with the stored values (defaults 1 and 4).

        Errors: 400 "Wochen zurück muss eine ganze Zahl sein." and "Wochen voraus
        muss eine ganze Zahl sein."; 400 "Wochen zurück muss zwischen 0 und 52
        liegen." and "Wochen voraus muss zwischen 0 und 52 liegen."; 400 "Keine
        Kalenderansicht-Einstellungen eingegeben." when neither field is sent.
        """
        handler.send_json(
            200, self._settings.save_calendar_display_settings(handler.read_json())
        )
