"""Configuration is explicit, repeatable, and independent of application imports."""

import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import backend
from backend.config import (
    Config,
    load_config,
    save_persistent_settings,
    security_configuration_error,
)
from backend.errors import AppError


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

    def test_security_error_order_and_success(self):
        config = Config(
            8090, "", "https://api.openai.com/v1", "model", "", "gemini", "openai",
            "", "0", "", "", "tokens", "", "", "", False, -1,
        )
        self.assertEqual(
            security_configuration_error(config, sqlcipher_available=False),
            "APP_PASSWORD ist nicht konfiguriert. Lege ein langes, zufälliges Passwort als Container-Umgebungsvariable fest.",
        )
        config = replace(config, app_password="short")
        self.assertEqual(
            security_configuration_error(config, sqlcipher_available=False),
            "APP_PASSWORD muss mindestens 12 Zeichen lang sein.",
        )
        config = replace(config, app_password="long-enough-password")
        self.assertEqual(
            security_configuration_error(config, sqlcipher_available=False),
            "SQLCipher ist nicht verfügbar; die verschlüsselte Datenbank kann nicht geöffnet werden.",
        )
        self.assertIsNone(security_configuration_error(config, sqlcipher_available=True))

    def test_save_rejects_invalid_or_empty_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for values, message in (
                (None, "Die Einstellungen müssen als Objekt gesendet werden."),
                ({"UNKNOWN": "ignored"}, "Keine neuen Zugangsdaten oder Einstellungen eingegeben."),
                ({"OPENAI_API_KEY": " \r\n"}, "Keine neuen Zugangsdaten oder Einstellungen eingegeben."),
            ):
                with self.subTest(values=values), self.assertRaises(AppError) as raised:
                    save_persistent_settings(data_dir, values, {})
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.message, message)
            self.assertFalse((data_dir / ".env").exists())

    def test_save_filters_values_preserves_env_file_and_updates_process_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            env_path = data_dir / ".env"
            env_path.write_text(
                "# keep this comment\nexport OPENAI_API_KEY=old\nUNTOUCHED = keep\n",
                encoding="utf-8",
            )
            environ = {"OPENAI_API_KEY": "process-old"}
            result = save_persistent_settings(
                data_dir,
                {
                    "OPENAI_API_KEY": " new\r\nsecret ",
                    "GARMIN_EMAIL": " athlete@example.test ",
                    "GARMIN_PASSWORD": "",
                    "UNKNOWN": "must-not-persist",
                },
                environ,
            )
            self.assertEqual(result, {
                "status": "ok",
                "updated": ["GARMIN_EMAIL", "OPENAI_API_KEY"],
                "restart_required": True,
            })
            self.assertEqual(environ, {
                "OPENAI_API_KEY": "newsecret",
                "GARMIN_EMAIL": "athlete@example.test",
            })
            self.assertEqual(
                env_path.read_text(encoding="utf-8"),
                "# keep this comment\nexport OPENAI_API_KEY=newsecret\nUNTOUCHED = keep\nGARMIN_EMAIL=athlete@example.test\n",
            )
            self.assertNotIn("newsecret", repr(result))

    def test_save_maps_read_and_write_errors_to_app_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / ".env").mkdir()
            with self.assertRaises(AppError) as raised:
                save_persistent_settings(data_dir, {"GARMIN_EMAIL": "athlete@example.test"}, {})
            self.assertEqual(raised.exception.status, 500)
            self.assertIn(".env konnte nicht gelesen werden", raised.exception.message)

            (data_dir / ".env").rmdir()
            environ = {}
            with mock.patch.object(Path, "write_text", side_effect=OSError("synthetic write failure")), self.assertRaises(AppError) as raised:
                save_persistent_settings(data_dir, {"GARMIN_EMAIL": "athlete@example.test"}, environ)
            self.assertEqual(raised.exception.status, 500)
            self.assertIn(".env konnte nicht gespeichert werden", raised.exception.message)
            self.assertEqual(environ, {"GARMIN_EMAIL": "athlete@example.test"})

    def test_import_has_no_filesystem_side_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            before = set(temporary_path.iterdir())
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(backend.__file__).resolve().parent.parent)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", "import backend.config"],
                cwd=temporary,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, set(temporary_path.iterdir()))

