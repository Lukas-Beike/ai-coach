"""Provider credential store: precedence, validation, status and hot-swap.

Uses an in-memory SQLite key/value table and a temporary config directory with
synthetic values. No real .env, /data, SQLCipher database or provider account
is touched.
"""

import dataclasses
import json
import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import cast

from backend import privacy
from backend import provider_credentials as credentials_module
from backend.backup import export
from backend.config import load_config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.http_api.credentials_put import CredentialsPutRoutes
from backend.observability import Redactor, config_secret_values
from backend.provider_credentials import (
    CREDENTIAL_KV_KEYS,
    GARMIN_TOKENS_KEY,
    GARMIN_TOKENSTORE_STATE_KEY,
    PROVIDER_CREDENTIALS_KEY,
    WAHOO_STATE_KEY,
    WAHOO_TOKENS_KEY,
    ProviderCredentialService,
    credential_status,
    effective_config,
    stored_credentials,
)

ENV = {
    "APP_PASSWORD": "synthetic-password-123",
    "OPENAI_API_KEY": "env-openai-key",
    "OPENAI_BASE_URL": "https://env.example.test/v1",
    "INTERVALS_API_KEY": "env-intervals-key",
    "INTERVALS_ATHLETE_ID": "i42",
    "GARMIN_EMAIL": "env@example.test",
}


class FakeManager:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        yield self._connection

    @contextmanager
    def unit_of_work(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._connection
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise


class ProviderCredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.env_config = load_config(root, root / "data", dict(ENV))
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        for table in ("provider_records", "provider_sync_cursors"):
            self.connection.execute(f"CREATE TABLE {table} (provider TEXT NOT NULL)")
        self.holder = {"config": self.env_config}
        self.service = ProviderCredentialService(
            env_config=self.env_config,
            database_manager=lambda: cast(
                DatabaseManager, FakeManager(self.connection)
            ),
            database_lock=nullcontext,
            key_values=KeyValueRepository(lambda: "2026-10-18T00:00:00Z"),
            apply_config=self._apply,
            current_config=lambda: self.holder["config"],
        )

    def tearDown(self) -> None:
        self.connection.close()
        self._temporary.cleanup()

    def _apply(self, config) -> None:
        self.holder["config"] = config

    def _stored_row(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM kv WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def test_athlete_change_is_rejected_while_intervals_data_exists(self):
        # Without Intervals data the athlete may change freely.
        self.service.update({"intervals_athlete_id": "i111"})
        self.connection.execute(
            "INSERT INTO provider_sync_cursors VALUES ('intervals')"
        )
        self.connection.commit()
        for change in (
            {"intervals_athlete_id": "i222"},
            {"intervals_athlete_id": None},
        ):
            with self.assertRaises(AppError) as rejected:
                self.service.update(change)
            self.assertEqual(rejected.exception.status, 409)
        self.assertEqual(self.holder["config"].intervals_athlete_id, "i111")
        # The same athlete and other fields still save.
        self.service.update({"intervals_athlete_id": " i111 ", "openai_api_key": "k2"})
        self.assertEqual(self.holder["config"].openai_api_key, "k2")

    def test_stored_value_overrides_env_and_clearing_restores_env(self):
        self.service.update({"openai_api_key": "db-openai-key"})
        self.assertEqual(self.holder["config"].openai_api_key, "db-openai-key")

        self.service.update({"openai_api_key": None})
        self.assertEqual(self.holder["config"].openai_api_key, "env-openai-key")
        self.assertIsNone(self._stored_row(PROVIDER_CREDENTIALS_KEY))

    def test_refresh_keeps_runtime_settings_outside_the_credentials(self):
        # A runtime value that differs from the environment, such as a patched
        # database key, survives refreshes; only credential fields change.
        self.holder["config"] = dataclasses.replace(
            self.env_config, app_password="runtime-password", openai_api_key="patched"
        )
        self.service.refresh()
        self.assertEqual(self.holder["config"].app_password, "runtime-password")
        self.assertEqual(self.holder["config"].openai_api_key, "patched")

        self.service.update({"openai_api_key": "db-openai-key"})
        self.assertEqual(self.holder["config"].openai_api_key, "db-openai-key")
        self.service.update({"openai_api_key": None})
        self.assertEqual(self.holder["config"].openai_api_key, "env-openai-key")
        self.assertEqual(self.holder["config"].app_password, "runtime-password")

    def test_empty_string_clears_like_null(self):
        self.service.update({"intervals_api_key": "db-intervals"})
        self.service.update({"intervals_api_key": "   "})
        self.assertEqual(self.holder["config"].intervals_api_key, "env-intervals-key")

    def test_hot_swap_is_visible_to_lambda_readers_without_restart(self):
        reader = lambda: self.holder["config"]
        self.assertEqual(reader().intervals_athlete_id, "i42")
        self.service.update({"intervals_athlete_id": "i99"})
        self.assertEqual(reader().intervals_athlete_id, "i99")

    def test_invalid_base_url_is_rejected_with_400_and_nothing_is_written(self):
        for value in ("http://example.test/v1", "ftp://example.test", "https://a/../b"):
            with self.subTest(value=value), self.assertRaises(AppError) as raised:
                self.service.update({"openai_base_url": value})
            self.assertEqual(raised.exception.status, 400)
        self.assertIsNone(self._stored_row(PROVIDER_CREDENTIALS_KEY))

    def test_loopback_http_base_url_is_accepted_and_normalized(self):
        self.service.update({"openai_base_url": "http://localhost:8080/v1/"})
        self.assertEqual(
            self.holder["config"].openai_base_url, "http://localhost:8080/v1"
        )

    def test_malformed_submissions_are_rejected_with_400(self):
        for values in (
            None,
            ["openai_api_key"],
            {"UNKNOWN_FIELD": "x"},
            {"openai_api_key": 12},
            {"openai_api_key": "bad\x00value"},
            {"openai_api_key": "x" * 5000},
        ):
            with self.subTest(values=values), self.assertRaises(AppError) as raised:
                self.service.update(values)
            self.assertEqual(raised.exception.status, 400)

    def test_stored_invalid_base_url_is_ignored_at_boot(self):
        effective = effective_config(
            self.env_config, {"openai_base_url": "http://example.test"}
        )
        self.assertEqual(effective.openai_base_url, "https://env.example.test/v1")

    def test_stored_credentials_ignore_unknown_and_non_string_entries(self):
        raw = json.dumps(
            {"openai_api_key": "k", "unknown": "x", "intervals_api_key": 3}
        )
        self.assertEqual(stored_credentials(raw), {"openai_api_key": "k"})
        self.assertEqual(stored_credentials("not json"), {})

    def test_status_never_contains_secret_values(self):
        self.service.update(
            {
                "openai_api_key": "secret-openai-value",
                "wahoo_client_secret": "secret-wahoo-value",
                "garmin_email": "stored@example.test",
            }
        )
        payload = json.dumps(self.service.status())
        for secret in ("secret-openai-value", "secret-wahoo-value", "stored@example"):
            self.assertNotIn(secret, payload)
        status = self.service.status()
        self.assertEqual(status["fields"]["openai_api_key"]["source"], "db")
        self.assertTrue(status["fields"]["openai_api_key"]["configured"])
        self.assertNotIn("value", status["fields"]["openai_api_key"])
        self.assertEqual(status["fields"]["intervals_api_key"]["source"], "env")
        self.assertEqual(status["fields"]["intervals_athlete_id"]["value"], "i42")

    def test_yazio_needs_all_four_values_and_never_appears_in_status(self):
        values = {
            "yazio_email": "athlete@yazio.example",
            "yazio_password": "secret-yazio-password",
            "yazio_client_id": "secret-yazio-client-id",
            "yazio_client_secret": "secret-yazio-client-secret",
        }
        self.assertFalse(self.service.status()["yazio_configured"])
        self.service.update({k: v for k, v in values.items() if k != "yazio_password"})
        self.assertFalse(self.holder["config"].yazio_configured)
        status = self.service.update({"yazio_password": values["yazio_password"]})
        self.assertTrue(status["yazio_configured"])
        self.assertTrue(self.holder["config"].yazio_configured)
        payload = json.dumps(status)
        for secret in values.values():
            self.assertNotIn(secret, payload)
        self.assertEqual(status["fields"]["yazio_email"]["source"], "db")
        self.assertNotIn("value", status["fields"]["yazio_email"])
        status = self.service.update({"yazio_client_secret": None})
        self.assertFalse(status["yazio_configured"])

    def test_yazio_generation_ignores_other_credentials_and_tracks_replacements(self):
        start = self.holder["config"].yazio_credential_generation
        unrelated = {"openai_api_key": "test"}
        first, second = "first", "second"
        self.service.update(unrelated)
        self.assertEqual(self.holder["config"].yazio_credential_generation, start)
        self.service.update({"yazio_password": first})
        self.assertEqual(self.holder["config"].yazio_credential_generation, start + 1)
        self.service.update({"yazio_password": second})
        self.service.update({"yazio_password": first})
        self.assertEqual(self.holder["config"].yazio_credential_generation, start + 3)

    def test_environment_password_is_stripped_like_the_stored_one(self):
        root = Path(self._temporary.name)
        config = load_config(root, root / "data", {**ENV, "YAZIO_PASSWORD": " pw "})
        self.assertEqual(config.yazio_password, "pw")

    def test_status_reports_none_when_neither_db_nor_env_is_set(self):
        config = dataclasses.replace(self.env_config, wahoo_client_secret="")
        status = credential_status(config, {})
        self.assertEqual(
            status["fields"]["wahoo_client_secret"],
            {"source": "none", "configured": False},
        )

    def test_garmin_connection_follows_token_presence_not_values(self):
        self.assertFalse(self.service.status()["garmin_connected"])
        self.connection.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (GARMIN_TOKENS_KEY, '{"token": "synthetic"}', "2026-10-18T00:00:00Z"),
        )
        status = self.service.status()
        self.assertTrue(status["garmin_connected"])
        self.assertEqual(
            status["garmin_connection"],
            {"connected": True, "source": "db", "mfa_pending": False},
        )
        self.assertNotIn("synthetic", json.dumps(status))

    def test_garmin_connection_supplier_drives_the_status(self):
        self.service._garmin_connection = lambda: {
            "connected": False,
            "source": "none",
            "mfa_pending": True,
        }
        status = self.service.status()
        self.assertFalse(status["garmin_connected"])
        self.assertTrue(status["garmin_connection"]["mfa_pending"])

    def test_wipe_then_refresh_returns_to_environment(self):
        self.service.update({"openai_api_key": "db-openai-key"})
        self.connection.execute("DELETE FROM kv")
        self.service.refresh()
        self.assertEqual(self.holder["config"].openai_api_key, "env-openai-key")

    def test_refresh_applies_the_configuration_under_the_database_lock(self):
        held: list[bool] = []
        applied_under_lock: list[bool] = []

        @contextmanager
        def lock() -> Iterator[None]:
            held.append(True)
            try:
                yield
            finally:
                held.pop()

        service = ProviderCredentialService(
            env_config=self.env_config,
            database_manager=lambda: FakeManager(self.connection),
            database_lock=lock,
            key_values=KeyValueRepository(lambda: "2026-10-18T00:00:00Z"),
            apply_config=lambda config: applied_under_lock.append(bool(held)),
        )
        self.connection.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
            (PROVIDER_CREDENTIALS_KEY, '{"openai_api_key":"db-key"}', "now"),
        )
        service.refresh()
        self.assertEqual(applied_under_lock, [True])

    def test_environment_secret_stays_redacted_while_a_stored_value_overrides_it(
        self,
    ):
        self.service.update({"openai_api_key": "db-openai-key"})
        redactor = Redactor(
            lambda: self.holder["config"],
            extra_secrets=lambda: config_secret_values(self.env_config),
        )
        redacted = redactor.redact_text("keys env-openai-key and db-openai-key")
        self.assertNotIn("env-openai-key", redacted)
        self.assertNotIn("db-openai-key", redacted)

    def test_credential_kv_keys_cover_every_stored_secret_key(self):
        self.assertEqual(
            CREDENTIAL_KV_KEYS,
            frozenset(
                {
                    PROVIDER_CREDENTIALS_KEY,
                    GARMIN_TOKENS_KEY,
                    GARMIN_TOKENSTORE_STATE_KEY,
                    WAHOO_TOKENS_KEY,
                    WAHOO_STATE_KEY,
                }
            ),
        )

    def test_export_and_privacy_share_the_credential_key_set(self):
        self.assertIs(export.CREDENTIAL_KV_KEYS, CREDENTIAL_KV_KEYS)
        self.assertIs(privacy.CREDENTIAL_KV_KEYS, CREDENTIAL_KV_KEYS)
        self.assertIs(credentials_module.CREDENTIAL_KV_KEYS, CREDENTIAL_KV_KEYS)

    def test_route_returns_status_only_and_delegates_to_service(self):
        seen = {}

        class FakeHandler:
            def read_json(self):
                return {"openai_api_key": "route-secret-value"}

            def send_json(self, status, payload):
                seen["status"] = status
                seen["payload"] = payload

        route = CredentialsPutRoutes(self.service)
        self.assertFalse(route.handle(FakeHandler(), "/api/settings/model"))
        self.assertTrue(route.handle(FakeHandler(), "/api/settings/credentials"))
        self.assertEqual(seen["status"], 200)
        self.assertNotIn("route-secret-value", json.dumps(seen["payload"]))
        self.assertEqual(self.holder["config"].openai_api_key, "route-secret-value")


if __name__ == "__main__":
    unittest.main()
