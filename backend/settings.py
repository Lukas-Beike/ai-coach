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
    {
        "id": "gpt-6-luna",
        "label": "GPT-6 Luna",
        "description": "Effizient für kostenbewusste Nutzung",
    },
)
THINKING_LEVEL_OPTIONS = (
    {
        "id": "low",
        "label": "Niedrig",
        "description": "Schnellere Antworten mit weniger zusätzlicher Überlegung",
    },
    {
        "id": "medium",
        "label": "Mittel",
        "description": "Ausgewogene Qualität, Geschwindigkeit und Kosten",
    },
    {
        "id": "high",
        "label": "Hoch",
        "description": "Gründlichere Überlegung für komplexe Trainingsfragen",
    },
)
CALENDAR_DISPLAY_DEFAULTS = {"past_weeks": 1, "future_weeks": 4}
CALENDAR_DISPLAY_MAX_WEEKS = 52


def _copy_options(
    options: tuple[dict[str, str], ...] | list[dict[str, str]],
) -> list[dict[str, str]]:
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
    def _available_model_options(config: Config) -> list[dict[str, str]]:
        options = _copy_options(MODEL_OPTIONS)
        configured_model = config.openai_model
        if configured_model not in {option["id"] for option in options}:
            options.insert(
                0,
                {
                    "id": configured_model,
                    "label": f"{configured_model} (konfiguriert)",
                    "description": "In .env konfiguriert",
                },
            )
        return options

    def _selected_model(self, config: Config) -> str:
        configured = {option["id"] for option in self._available_model_options(config)}
        stored = self._get_value("selected_model_openai")
        default = config.openai_model
        return stored if stored in configured else default

    def _calendar_display_settings(self) -> dict[str, int]:
        settings: dict[str, int] = {}
        for key, default in CALENDAR_DISPLAY_DEFAULTS.items():
            try:
                value = int(self._get_value(f"calendar_display_{key}") or default)
            except TypeError, ValueError:
                value = default
            settings[key] = max(0, min(value, CALENDAR_DISPLAY_MAX_WEEKS))
        return settings

    def available_model_options(self) -> list[dict[str, str]]:
        config = self._config_supplier()
        return self._available_model_options(config)

    def selected_model(self) -> str:
        return self._selected_model(self._config_supplier())

    def save_model(self, model: Any) -> dict[str, str]:
        config = self._config_supplier()
        model_id = str(model or "").strip()
        if model_id not in {
            option["id"] for option in self._available_model_options(config)
        }:
            raise AppError(400, "Nicht unterstützte Modellauswahl.")
        self._set_value("selected_model_openai", model_id)
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
                raise AppError(
                    400, f"Wochen {label} muss eine ganze Zahl sein."
                ) from exc
            if not 0 <= value <= CALENDAR_DISPLAY_MAX_WEEKS:
                raise AppError(
                    400,
                    f"Wochen {label} muss zwischen 0 und {CALENDAR_DISPLAY_MAX_WEEKS} liegen.",
                )
            updates[key] = value
        if not updates:
            raise AppError(400, "Keine Kalenderansicht-Einstellungen eingegeben.")
        for key, value in updates.items():
            self._set_value(f"calendar_display_{key}", str(value))
        return {"status": "ok", **self._calendar_display_settings()}
