import unittest
from dataclasses import replace

from backend.config import Config
from backend.errors import AppError
from backend.settings import (
    CALENDAR_DISPLAY_DEFAULTS,
    CALENDAR_DISPLAY_MAX_WEEKS,
    GEMINI_MODEL_OPTIONS,
    MODEL_OPTIONS,
    THINKING_LEVEL_OPTIONS,
    SettingsService,
)


def make_config(**changes):
    config = Config(
        port=8090,
        openai_api_key="openai-test-key",
        openai_base_url="https://openai.example.invalid/v1",
        openai_model="gpt-6-luna",
        gemini_api_key="",
        gemini_model="gemini-3.8-flash",
        ai_provider="openai",
        intervals_api_key="intervals-test-key",
        intervals_athlete_id="synthetic-athlete",
        garmin_email="",
        garmin_password="",
        garmin_tokenstore="synthetic-tokenstore",
        garmin_fixture_path="",
        calendar_ical_url="",
        app_password="synthetic-app-password",
        secure_cookies=False,
        data_retention_days=-1,
    )
    return replace(config, **changes)


class SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.current_config = [make_config()]
        self.values = {}
        self.writes = []
        self.service = SettingsService(
            lambda: self.current_config[0],
            self.values.get,
            lambda key, value: (self.writes.append((key, value)), self.values.__setitem__(key, value)),
        )

    def test_available_providers_are_ordered_and_follow_live_config(self):
        self.assertEqual([item["id"] for item in self.service.available_ai_providers()], ["openai"])
        self.current_config[0] = replace(self.current_config[0], gemini_api_key="gemini-test-key", ai_provider="gemini")
        self.assertEqual([item["id"] for item in self.service.available_ai_providers()], ["openai", "gemini"])
        self.assertEqual(self.service.selected_ai_provider(), "gemini")

    def test_provider_selection_prefers_stored_then_config_then_fallback(self):
        self.current_config[0] = replace(self.current_config[0], gemini_api_key="gemini-test-key", ai_provider="gemini")
        self.assertEqual(self.service.selected_ai_provider(), "gemini")
        self.values["selected_ai_provider"] = "OPENAI"
        self.assertEqual(self.service.selected_ai_provider(), "openai")
        self.values["selected_ai_provider"] = "unknown"
        self.current_config[0] = replace(self.current_config[0], ai_provider="unknown")
        self.assertEqual(self.service.selected_ai_provider(), "openai")
        self.current_config[0] = replace(self.current_config[0], openai_api_key="", gemini_api_key="gemini-test-key")
        self.assertEqual(self.service.selected_ai_provider(), "gemini")
        self.current_config[0] = replace(self.current_config[0], gemini_api_key="")
        self.assertEqual(self.service.selected_ai_provider(), "")

    def test_model_options_copy_and_unknown_configured_model(self):
        self.current_config[0] = replace(self.current_config[0], openai_model="custom-openai-model")
        options = self.service.available_model_options("openai")
        self.assertEqual(options[0]["id"], "custom-openai-model")
        options[0]["label"] = "changed"
        options.append({"id": "extra"})
        self.assertEqual(self.service.available_model_options("openai")[0]["label"], "custom-openai-model (konfiguriert)")
        self.assertEqual(MODEL_OPTIONS[0]["label"], "GPT-6 Luna")

        self.current_config[0] = replace(self.current_config[0], gemini_api_key="gemini-test-key", gemini_model="custom-gemini-model")
        self.assertEqual(self.service.available_model_options("gemini")[0]["id"], "custom-gemini-model")
        self.assertEqual(GEMINI_MODEL_OPTIONS[0]["id"], "gemini-3.8-flash")

    def test_models_are_persisted_per_provider_and_save_returns_state(self):
        self.current_config[0] = replace(self.current_config[0], gemini_api_key="gemini-test-key")
        self.assertEqual(self.service.save_model("gpt-6-luna"), {"model": "gpt-6-luna"})
        self.assertEqual(self.writes[-1], ("selected_model_openai", "gpt-6-luna"))
        provider_state = self.service.save_ai_provider("gemini")
        self.assertEqual(provider_state["provider"], "gemini")
        self.assertEqual(provider_state["model"], "gemini-3.8-flash")
        self.assertEqual(self.writes[-1], ("selected_ai_provider", "gemini"))
        self.service.save_model("gemini-2.5-pro")
        self.assertEqual(self.writes[-1], ("selected_model_gemini", "gemini-2.5-pro"))
        self.service.save_ai_provider("openai")
        self.assertEqual(self.service.selected_model(), "gpt-6-luna")

    def test_invalid_provider_and_model_are_rejected_without_writes(self):
        with self.assertRaisesRegex(AppError, "Der ausgewählte KI-Anbieter ist nicht konfiguriert") as error:
            self.service.save_ai_provider("gemini")
        self.assertEqual(error.exception.status, 400)
        with self.assertRaisesRegex(AppError, "Nicht unterstützte Modellauswahl") as error:
            self.service.save_model("not-supported")
        self.assertEqual(error.exception.status, 400)
        with self.assertRaisesRegex(AppError, "Nicht unterstützte Modellauswahl") as error:
            self.service.save_model("gpt-5.6-sol")
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.writes, [])

    def test_thinking_level_defaults_validates_and_returns_copies(self):
        self.assertEqual(self.service.selected_thinking_level(), "medium")
        options = self.service.available_thinking_level_options()
        options[0]["label"] = "changed"
        options.clear()
        self.assertEqual(self.service.available_thinking_level_options(), list(THINKING_LEVEL_OPTIONS))
        self.assertEqual(self.service.save_thinking_level(" HIGH "), {"thinking_level": "high"})
        self.assertEqual(self.writes[-1], ("selected_thinking_level", "high"))
        with self.assertRaisesRegex(AppError, "Nicht unterstütztes Thinking Level") as error:
            self.service.save_thinking_level("extreme")
        self.assertEqual(error.exception.status, 400)

    def test_calendar_defaults_clamping_and_write_keys(self):
        self.assertEqual(self.service.calendar_display_settings(), CALENDAR_DISPLAY_DEFAULTS)
        self.values.update({"calendar_display_past_weeks": "-4", "calendar_display_future_weeks": "99", "calendar_display_unknown": "7"})
        self.assertEqual(self.service.calendar_display_settings(), {"past_weeks": 0, "future_weeks": CALENDAR_DISPLAY_MAX_WEEKS})
        result = self.service.save_calendar_display_settings({"past_weeks": 3})
        self.assertEqual(result, {"status": "ok", "past_weeks": 3, "future_weeks": CALENDAR_DISPLAY_MAX_WEEKS})
        self.assertEqual(self.writes[-1], ("calendar_display_past_weeks", "3"))

    def test_calendar_invalid_values_have_exact_errors_and_no_partial_write(self):
        for payload, message in (
            (None, "Die Kalenderansicht muss als Objekt gesendet werden."),
            ({}, "Keine Kalenderansicht-Einstellungen eingegeben."),
            ({"past_weeks": "x"}, "Wochen zurück muss eine ganze Zahl sein."),
            ({"future_weeks": CALENDAR_DISPLAY_MAX_WEEKS + 1}, "Wochen voraus muss zwischen 0 und 52 liegen."),
        ):
            with self.subTest(payload=payload), self.assertRaisesRegex(AppError, message) as error:
                self.service.save_calendar_display_settings(payload)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(self.writes, [])


if __name__ == "__main__":
    unittest.main()
