"""Configuration is explicit, repeatable, and independent of application imports."""

import tempfile
import unittest
from pathlib import Path

from backend.config import Config, load_config
from backend.providers.intervals_client import IntervalsClient


class ConfigTests(unittest.TestCase):
    def test_two_loads_use_their_supplied_environment_and_paths(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_config = load_config(Path(first), Path(first), {
                "APP_PASSWORD": "first-password",
                "DATA_DIR": first,
                "PORT": "8091",
            })
            second_config = load_config(Path(second), Path(second), {
                "APP_PASSWORD": "second-password",
                "DATA_DIR": second,
                "PORT": "8092",
            })

        self.assertEqual(first_config.app_password, "first-password")
        self.assertEqual(first_config.port, 8091)
        self.assertEqual(second_config.app_password, "second-password")
        self.assertEqual(second_config.port, 8092)
        self.assertEqual(first_config.garmin_tokenstore, str(Path(first) / "garmin_tokens"))
        self.assertEqual(second_config.garmin_tokenstore, str(Path(second) / "garmin_tokens"))

    def test_process_values_win_over_persisted_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("PORT=9999\nAPP_PASSWORD=persisted\n", encoding="utf-8")
            config = load_config(root, root, {"PORT": "8090", "APP_PASSWORD": "process"})

        self.assertEqual(config.port, 8090)
        self.assertEqual(config.app_password, "process")

    def test_provider_client_requires_explicit_config_and_request(self):
        config = Config(
            port=8090, openai_api_key="", openai_base_url="https://api.openai.com/v1", openai_model="model",
            gemini_api_key="", gemini_model="gemini", ai_provider="", intervals_api_key="key",
            intervals_athlete_id="athlete", garmin_email="", garmin_password="", garmin_tokenstore="tokens",
            garmin_fixture_path="", calendar_ical_url="", app_password="password", secure_cookies=False,
            data_retention_days=-1,
        )
        client = IntervalsClient(config, request=lambda *args, **kwargs: [])
        self.assertIs(client.config, config)
        with self.assertRaises(TypeError):
            IntervalsClient()  # type: ignore[call-arg]

