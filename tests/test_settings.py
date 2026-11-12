import unittest
from dataclasses import replace

from backend.config import Config
from backend.errors import AppError
from backend.settings import (
    CALENDAR_DISPLAY_DEFAULTS,
    CALENDAR_DISPLAY_MAX_WEEKS,
    MODEL_OPTIONS,
    THINKING_LEVEL_OPTIONS,
    SettingsService,
)


def make_config(**changes):
    config = Config(
        port=8090,
        openai_api_key="openai-test-key",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-6-luna",
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
            lambda key, value: (
                self.writes.append((key, value)),
                self.values.__setitem__(key, value),
            ),
        )

    def test_model_options_copy_and_unknown_configured_model(self):
        self.current_config[0] = replace(
            self.current_config[0], openai_model="custom-openai-model"
        )
        options = self.service.available_model_options()
        self.assertEqual(options[0]["id"], "custom-openai-model")
        options[0]["label"] = "changed"
        options.append({"id": "extra"})
        self.assertEqual(
            self.service.available_model_options()[0]["label"],
            "custom-openai-model (konfiguriert)",
        )
        self.assertEqual(MODEL_OPTIONS[0]["label"], "GPT-6 Luna")

    def test_model_is_persisted_and_save_returns_state(self):
        self.assertEqual(self.service.save_model("gpt-6-luna"), {"model": "gpt-6-luna"})
        self.assertEqual(self.writes[-1], ("selected_model_openai", "gpt-6-luna"))
        self.assertEqual(self.service.selected_model(), "gpt-6-luna")

    def test_invalid_model_is_rejected_without_writes(self):
        for model in ("not-supported", "gpt-5.6-sol"):
            with self.assertRaises(AppError) as error:
                self.service.save_model(model)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(
                str(error.exception), "Nicht unterst\u00fctzte Modellauswahl."
            )
        self.assertEqual(self.writes, [])

    def test_thinking_level_defaults_validates_and_returns_copies(self):
        self.assertEqual(self.service.selected_thinking_level(), "medium")
        options = self.service.available_thinking_level_options()
        options[0]["label"] = "changed"
        options.clear()
        self.assertEqual(
            self.service.available_thinking_level_options(),
            list(THINKING_LEVEL_OPTIONS),
        )
        self.assertEqual(
            self.service.save_thinking_level(" HIGH "), {"thinking_level": "high"}
        )
        self.assertEqual(self.writes[-1], ("selected_thinking_level", "high"))
        with self.assertRaises(AppError) as error:
            self.service.save_thinking_level("extreme")
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(
            str(error.exception), "Nicht unterst\u00fctztes Thinking Level."
        )

    def test_speed_defaults_and_model_capabilities(self):
        self.assertEqual(self.service.service_tier(), "fast")
        self.assertEqual(self.service.selected_thinking_level(), "medium")
        self.assertEqual(
            [o["id"] for o in self.service.service_tier_state()["options"]],
            ["default", "fast"],
        )
        with self.assertRaises(AppError):
            self.service.save_service_tier("ultrafast")
        self.service.save_model("gpt-6.1-sol")
        self.service.save_service_tier("ultrafast")
        self.assertEqual(self.service.service_tier(), "ultrafast")
        self.service.save_model("gpt-6-luna")
        self.assertEqual(self.service.service_tier(), "fast")
        self.service.save_service_tier("default")
        self.assertEqual(self.service.service_tier(), "default")
        self.assertIsNone(self.service.service_tier("custom-deployment"))

    def test_compatible_endpoint_keeps_only_configured_model_and_omits_tier(self):
        self.current_config[0] = replace(
            self.current_config[0],
            openai_base_url="https://provider.example.invalid/v1",
            openai_model="custom-deployment",
        )
        self.values["selected_model_openai"] = "gpt-6.1-sol"
        self.values["selected_service_tier"] = "ultrafast"
        self.assertEqual(self.service.selected_model(), "custom-deployment")
        self.assertEqual(
            [
                o["id"]
                for o in self.service.available_model_options()
                if o["provider"] == "openai"
            ],
            ["custom-deployment"],
        )
        self.assertIsNone(self.service.service_tier())
        self.assertIsNone(self.service.service_tier("gpt-6-luna"))
        self.assertEqual(self.service.service_tier_state()["selected"], "default")
        with self.assertRaises(AppError):
            self.service.save_model("gpt-6.1-sol")
        with self.assertRaises(AppError):
            self.service.save_service_tier("fast")

    def test_claude_families_follow_the_resolver_and_need_their_key(self):
        status = {
            "opus": {"model": "claude-opus-5-5", "rejected": "claude-opus-5-6"},
            "sonnet": {"model": "claude-sonnet-5-5", "rejected": None},
        }
        service = SettingsService(
            lambda: self.current_config[0],
            self.values.get,
            self.values.__setitem__,
            claude_models=lambda: status,
        )
        claude = [
            o for o in service.available_model_options() if o["provider"] == "claude"
        ]
        self.assertEqual(
            [(o["id"], o["label"], o["model"], o["rejected"]) for o in claude],
            [
                ("claude-opus", "Opus", "claude-opus-5-5", "claude-opus-5-6"),
                ("claude-sonnet", "Sonnet", "claude-sonnet-5-5", None),
                ("claude-haiku", "Haiku", None, None),
            ],
        )
        # Without an Anthropic key the families show but cannot be chosen.
        self.assertTrue(all(o["disabled"] for o in claude))
        with self.assertRaises(AppError) as raised:
            service.save_model("claude-opus")
        self.assertEqual(raised.exception.status, 400)
        self.assertNotIn("selected_model_openai", self.values)
        self.current_config[0] = replace(
            self.current_config[0], anthropic_api_key="anthropic-test-key"
        )
        self.assertEqual(service.save_model("claude-opus"), {"model": "claude-opus"})
        self.assertEqual(service.selected_model(), "claude-opus")
        self.assertEqual(service.selected_provider(), "anthropic")
        # Claude has no speed modes; OpenAI's stay as they were.
        self.assertIsNone(service.service_tier())
        self.current_config[0] = replace(self.current_config[0], openai_api_key="")
        self.assertTrue(
            all(
                o["disabled"]
                for o in service.available_model_options()
                if o["provider"] == "openai"
            )
        )
        service.save_model("gpt-6-sol")
        self.assertEqual(service.selected_provider(), "openai")

    def test_calendar_defaults_clamping_and_write_keys(self):
        self.assertEqual(
            self.service.calendar_display_settings(), CALENDAR_DISPLAY_DEFAULTS
        )
        self.values.update(
            {
                "calendar_display_past_weeks": "-4",
                "calendar_display_future_weeks": "99",
                "calendar_display_unknown": "7",
            }
        )
        self.assertEqual(
            self.service.calendar_display_settings(),
            {"past_weeks": 0, "future_weeks": CALENDAR_DISPLAY_MAX_WEEKS},
        )
        result = self.service.save_calendar_display_settings({"past_weeks": 3})
        self.assertEqual(
            result,
            {
                "status": "ok",
                "past_weeks": 3,
                "future_weeks": CALENDAR_DISPLAY_MAX_WEEKS,
            },
        )
        self.assertEqual(self.writes[-1], ("calendar_display_past_weeks", "3"))

    def test_calendar_invalid_values_have_exact_errors_and_no_partial_write(self):
        cases = (
            (None, "Die Kalenderansicht muss als Objekt gesendet werden."),
            ({}, "Keine Kalenderansicht-Einstellungen eingegeben."),
            ({"past_weeks": "x"}, "Wochen zur\u00fcck muss eine ganze Zahl sein."),
            (
                {"future_weeks": CALENDAR_DISPLAY_MAX_WEEKS + 1},
                "Wochen voraus muss zwischen 0 und 52 liegen.",
            ),
        )
        for payload, message in cases:
            with self.subTest(payload=payload), self.assertRaises(AppError) as error:
                self.service.save_calendar_display_settings(payload)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(str(error.exception), message)
            self.assertEqual(self.writes, [])


if __name__ == "__main__":
    unittest.main()
