"""Application settings selection and validation.

The service is deliberately persistence-agnostic: configuration and key/value
storage are supplied by the application composition root.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.errors import AppError

MODEL_OPTIONS = (
    {"id": "gpt-6-luna", "label": "GPT-6 Luna", "description": "Effizient für kostenbewusste Nutzung"},
)
GEMINI_MODEL_OPTIONS = (
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash", "description": "Schnelle, leistungsstarke Gemini-Antworten"},
    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "description": "Gründlichere Gemini-Analyse für komplexe Trainingsfragen"},
)
THINKING_LEVEL_OPTIONS = (
    {"id": "low", "label": "Niedrig", "description": "Schnellere Antworten mit weniger zusätzlicher Überlegung"},
    {"id": "medium", "label": "Mittel", "description": "Ausgewogene Qualität, Geschwindigkeit und Kosten"},
    {"id": "high", "label": "Hoch", "description": "Gründlichere Überlegung für komplexe Trainingsfragen"},
)
CALENDAR_DISPLAY_DEFAULTS = {"past_weeks": 1, "future_weeks": 4}
CALENDAR_DISPLAY_MAX_WEEKS = 52


def _copy_options(options: tuple[dict[str, str], ...] | list[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(option) for option in options]


class SettingsService:
    """Own settings policy while leaving configuration and persistence outside."""

    def __init__(
        self,
        config_supplier: Callable[[], Config],
        get_value: Callable[[str], str | None],
        set_value: Callable[[str, str], None],
    ) -> None:
        self._config_supplier = config_supplier
        self._get_value = get_value
        self._set_value = set_value

    @staticmethod
    def _available_ai_providers(config: Config) -> list[dict[str, str]]:
        providers: list[dict[str, str]] = []
        if config.openai_api_key:
            providers.append({"id": "openai", "label": "OpenAI", "description": "GPT-6 Luna über die OpenAI Responses API"})
        if config.gemini_api_key:
            providers.append({"id": "gemini", "label": "Gemini", "description": "Google Gemini API"})
        return providers

    def _selected_ai_provider(self, config: Config) -> str:
        configured = {item["id"] for item in self._available_ai_providers(config)}
        stored = str(self._get_value("selected_ai_provider") or "").casefold()
        if stored in configured:
            return stored
        if config.ai_provider in configured:
            return config.ai_provider
        if "openai" in configured:
            return "openai"
        if "gemini" in configured:
            return "gemini"
        return ""

    @staticmethod
    def _available_model_options(config: Config, provider: str) -> list[dict[str, str]]:
        options = _copy_options(GEMINI_MODEL_OPTIONS if provider == "gemini" else MODEL_OPTIONS)
        configured_model = config.gemini_model if provider == "gemini" else config.openai_model
        if configured_model not in {option["id"] for option in options}:
            options.insert(0, {
                "id": configured_model,
                "label": f"{configured_model} (konfiguriert)",
                "description": "In .env konfiguriert",
            })
        return options

    def _selected_model(self, config: Config, provider: str | None = None) -> str:
        active_provider = provider or self._selected_ai_provider(config)
        configured = {option["id"] for option in self._available_model_options(config, active_provider)}
        stored = self._get_value(f"selected_model_{active_provider}") if active_provider else None
        default = config.gemini_model if active_provider == "gemini" else config.openai_model
        return stored if stored in configured else default

    def _calendar_display_settings(self) -> dict[str, int]:
        settings: dict[str, int] = {}
        for key, default in CALENDAR_DISPLAY_DEFAULTS.items():
            try:
                value = int(self._get_value(f"calendar_display_{key}") or default)
            except (TypeError, ValueError):
                value = default
            settings[key] = max(0, min(value, CALENDAR_DISPLAY_MAX_WEEKS))
        return settings

    def available_ai_providers(self) -> list[dict[str, str]]:
        return self._available_ai_providers(self._config_supplier())

    def selected_ai_provider(self) -> str:
        return self._selected_ai_provider(self._config_supplier())

    def save_ai_provider(self, provider: Any) -> dict[str, Any]:
        config = self._config_supplier()
        provider_id = str(provider or "").strip().casefold()
        if provider_id not in {item["id"] for item in self._available_ai_providers(config)}:
            raise AppError(400, "Der ausgewählte KI-Anbieter ist nicht konfiguriert.")
        self._set_value("selected_ai_provider", provider_id)
        return {
            "provider": provider_id,
            "model": self._selected_model(config, provider_id),
            "model_options": self._available_model_options(config, provider_id),
        }

    def available_model_options(self, provider: str | None = None) -> list[dict[str, str]]:
        config = self._config_supplier()
        active_provider = provider or self._selected_ai_provider(config)
        return self._available_model_options(config, active_provider)

    def selected_model(self, provider: str | None = None) -> str:
        return self._selected_model(self._config_supplier(), provider)

    def save_model(self, model: Any) -> dict[str, str]:
        config = self._config_supplier()
        provider = self._selected_ai_provider(config)
        model_id = str(model or "").strip()
        if model_id not in {option["id"] for option in self._available_model_options(config, provider)}:
            raise AppError(400, "Nicht unterstützte Modellauswahl.")
        self._set_value(f"selected_model_{provider}", model_id)
        return {"model": model_id}

    def available_thinking_level_options(self) -> list[dict[str, str]]:
        self._config_supplier()
        return _copy_options(THINKING_LEVEL_OPTIONS)

    def selected_thinking_level(self) -> str:
        self._config_supplier()
        configured = {option["id"] for option in THINKING_LEVEL_OPTIONS}
        stored = self._get_value("selected_thinking_level")
        return stored if stored in configured else "medium"

    def save_thinking_level(self, level: Any) -> dict[str, str]:
        self._config_supplier()
        level_id = str(level or "").strip().lower()
        if level_id not in {option["id"] for option in THINKING_LEVEL_OPTIONS}:
            raise AppError(400, "Nicht unterstütztes Thinking Level.")
        self._set_value("selected_thinking_level", level_id)
        return {"thinking_level": level_id}

    def calendar_display_settings(self) -> dict[str, int]:
        self._config_supplier()
        return self._calendar_display_settings()

    def save_calendar_display_settings(self, values: Any) -> dict[str, Any]:
        self._config_supplier()
        if not isinstance(values, dict):
            raise AppError(400, "Die Kalenderansicht muss als Objekt gesendet werden.")
        updates: dict[str, int] = {}
        for key, label in (("past_weeks", "zurück"), ("future_weeks", "voraus")):
            if key not in values:
                continue
            try:
                value = int(values[key])
            except (TypeError, ValueError) as exc:
                raise AppError(400, f"Wochen {label} muss eine ganze Zahl sein.") from exc
            if not 0 <= value <= CALENDAR_DISPLAY_MAX_WEEKS:
                raise AppError(400, f"Wochen {label} muss zwischen 0 und {CALENDAR_DISPLAY_MAX_WEEKS} liegen.")
            updates[key] = value
        if not updates:
            raise AppError(400, "Keine Kalenderansicht-Einstellungen eingegeben.")
        for key, value in updates.items():
            self._set_value(f"calendar_display_{key}", str(value))
        return {"status": "ok", **self._calendar_display_settings()}
