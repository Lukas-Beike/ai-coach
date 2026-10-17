"""Configuration is explicit, repeatable, and independent of application imports."""

import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest import mock

import backend
from backend.config import (
    Config,
    app_password_storage_warning,
    load_config,
    local_env_defines,
    save_persistent_settings,
    security_configuration_error,
    trusted_proxy_warning,
    validated_openai_base_url,
)
from backend.errors import AppError


class ConfigTests(unittest.TestCase):
    def test_two_loads_use_their_supplied_environment_and_paths(self):
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            first_config = load_config(
                Path(first),
                Path(first),
                {
                    "APP_PASSWORD": "first-password",
                    "DATA_DIR": first,
                    "PORT": "8091",
                },
            )
            second_config = load_config(
                Path(second),
                Path(second),
                {
                    "APP_PASSWORD": "second-password",
                    "DATA_DIR": second,
                    "PORT": "8092",
                },
            )

        self.assertEqual(first_config.app_password, "first-password")
        self.assertEqual(first_config.port, 8091)
        self.assertEqual(second_config.app_password, "second-password")
        self.assertEqual(second_config.port, 8092)
        self.assertEqual(
            first_config.garmin_tokenstore, str(Path(first) / "garmin_tokens")
        )
        self.assertEqual(
            second_config.garmin_tokenstore, str(Path(second) / "garmin_tokens")
        )

    def test_process_values_win_over_persisted_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(
                "PORT=9999\nAPP_PASSWORD=persisted\n", encoding="utf-8"
            )
            config = load_config(
                root, root, {"PORT": "8090", "APP_PASSWORD": "process"}
            )

        self.assertEqual(config.port, 8090)
        self.assertEqual(config.app_password, "process")

    def test_blank_openai_base_url_uses_documented_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = load_config(root, root, {"OPENAI_BASE_URL": "  "})

        self.assertEqual(config.openai_base_url, "https://api.openai.com/v1")

    def test_sync_history_floor_defaults_parses_and_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            default = load_config(root, root, {})
            valid = load_config(
                root, root, {"SYNC_HISTORY_EARLIEST_DATE": " 2015-06-01 "}
            )
            blank = load_config(root, root, {"SYNC_HISTORY_EARLIEST_DATE": "  "})
            with self.assertLogs("backend.config", level="WARNING") as logs:
                invalid = load_config(
                    root, root, {"SYNC_HISTORY_EARLIEST_DATE": "not-a-date"}
                )

        self.assertEqual(default.sync_history_earliest_date, date(2000, 1, 1))
        self.assertEqual(valid.sync_history_earliest_date, date(2015, 6, 1))
        self.assertEqual(blank.sync_history_earliest_date, date(2000, 1, 1))
        self.assertEqual(invalid.sync_history_earliest_date, date(2000, 1, 1))
        self.assertEqual(len(logs.records), 1)
        self.assertNotIn("not-a-date", logs.output[0])

    def test_trusted_proxies_parse_addresses_and_networks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            default = load_config(root, root, {})
            parsed = load_config(
                root,
                root,
                {
                    "TRUSTED_PROXY_IPS": (
                        " 192.168.1.6, fd00::/64 10.0.0.0/8 ::ffff:192.168.1.7"
                    )
                },
            )
            invalid = load_config(
                root,
                root,
                {"TRUSTED_PROXY_IPS": "192.168.1.6,not-an-ip 192.168.1.6/24"},
            )

        self.assertEqual(default.trusted_proxies, ())
        self.assertIsNone(trusted_proxy_warning(default))
        self.assertEqual(
            [str(network) for network in parsed.trusted_proxies],
            ["192.168.1.6/32", "fd00::/64", "10.0.0.0/8", "192.168.1.7/32"],
        )
        self.assertIsNone(trusted_proxy_warning(parsed))
        # A host address with a mask must not silently widen trust to the subnet.
        self.assertEqual(
            [str(network) for network in invalid.trusted_proxies], ["192.168.1.6/32"]
        )
        self.assertEqual(invalid.invalid_trusted_proxies, 2)
        warning = trusted_proxy_warning(invalid)
        self.assertIn("TRUSTED_PROXY_IPS", warning)
        self.assertNotIn("not-an-ip", warning)

    def test_local_env_defines_reports_only_assigned_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_path = Path(temporary) / ".env"
            self.assertFalse(local_env_defines(env_path, "APP_PASSWORD"))
            env_path.write_text(
                "# APP_PASSWORD=commented\nAPP_PASSWORD=\nOTHER=1\n", encoding="utf-8"
            )
            self.assertFalse(local_env_defines(env_path, "APP_PASSWORD"))
            env_path.write_text(
                "export APP_PASSWORD='synthetic-value'\n", encoding="utf-8"
            )
            self.assertTrue(local_env_defines(env_path, "APP_PASSWORD"))

    def test_app_password_storage_warning_never_contains_the_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self.assertIsNone(app_password_storage_warning(data_dir))
            (data_dir / ".env").write_text(
                "APP_PASSWORD=synthetic-secret-value\n", encoding="utf-8"
            )
            warning = app_password_storage_warning(data_dir)
        self.assertIsNotNone(warning)
        self.assertIn("DATA_DIR/.env", warning)
        self.assertNotIn("synthetic-secret-value", warning)

    def test_security_error_order_and_success(self):
        config = Config(
            8090,
            "",
            "https://api.openai.com/v1",
            "model",
            "",
            "0",
            "",
            "",
            "tokens",
            "",
            "",
            "",
            False,
            -1,
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
        self.assertIsNone(
            security_configuration_error(config, sqlcipher_available=True)
        )

    def test_openai_base_url_requires_https_or_loopback_http(self):
        self.assertEqual(
            validated_openai_base_url("https://api.example.test/v1/"),
            "https://api.example.test/v1",
        )
        self.assertEqual(
            validated_openai_base_url("http://127.0.0.1:8080/v1"),
            "http://127.0.0.1:8080/v1",
        )
        self.assertEqual(
            validated_openai_base_url("http://[::1]:8080/v1"), "http://[::1]:8080/v1"
        )
        for value in (
            "http://192.168.1.5/v1",
            "http://example.test/v1",
            "ftp://api.example.test/v1",
        ):
            with self.subTest(value=value), self.assertRaises(AppError):
                validated_openai_base_url(value)

    def test_save_rejects_invalid_or_empty_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for values, message in (
                (None, "Die Einstellungen müssen als Objekt gesendet werden."),
                (
                    {"UNKNOWN": "ignored"},
                    "Keine neuen Zugangsdaten oder Einstellungen eingegeben.",
                ),
                (
                    {"OPENAI_API_KEY": " \r\n"},
                    "Keine neuen Zugangsdaten oder Einstellungen eingegeben.",
                ),
            ):
                with self.subTest(values=values), self.assertRaises(AppError) as raised:
                    save_persistent_settings(data_dir, values, {})
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.message, message)
            self.assertFalse((data_dir / ".env").exists())

    def test_save_filters_values_preserves_env_file_and_updates_process_environment(
        self,
    ):
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
            self.assertEqual(
                result,
                {
                    "status": "ok",
                    "updated": ["GARMIN_EMAIL", "OPENAI_API_KEY"],
                    "restart_required": True,
                },
            )
            self.assertEqual(
                environ,
                {
                    "OPENAI_API_KEY": "newsecret",
                    "GARMIN_EMAIL": "athlete@example.test",
                },
            )
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
                save_persistent_settings(
                    data_dir, {"GARMIN_EMAIL": "athlete@example.test"}, {}
                )
            self.assertEqual(raised.exception.status, 500)
            self.assertIn(".env konnte nicht gelesen werden", raised.exception.message)

            (data_dir / ".env").rmdir()
            environ = {}
            with (
                mock.patch.object(
                    Path, "write_text", side_effect=OSError("synthetic write failure")
                ),
                self.assertRaises(AppError) as raised,
            ):
                save_persistent_settings(
                    data_dir, {"GARMIN_EMAIL": "athlete@example.test"}, environ
                )
            self.assertEqual(raised.exception.status, 500)
            self.assertIn(
                ".env konnte nicht gespeichert werden", raised.exception.message
            )
            self.assertEqual(environ, {"GARMIN_EMAIL": "athlete@example.test"})

    def test_import_has_no_filesystem_side_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            before = set(temporary_path.iterdir())
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(
                Path(backend.__file__).resolve().parent.parent
            )
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
