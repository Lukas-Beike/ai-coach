"""Garmin login use case: login, MFA, disconnect, token storage and redaction.

Uses an in-memory SQLite key/value table, a temporary data directory and a fake
Garmin SDK client. No real Garmin account, .env, /data or SQLCipher database is
touched.
"""

import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from backend.config import load_config
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.http_api.garmin_post import (
    DISCONNECT_PATH,
    LOGIN_PATH,
    GarminPostRoutes,
)
from backend.observability import Redactor
from backend.provider_credentials import (
    GARMIN_TOKENS_KEY,
    GARMIN_TOKENSTORE_STATE_KEY,
    garmin_tokens_connected,
)
from backend.sync.garmin_login import (
    MFA_TTL_SECONDS,
    GarminLoginService,
    GarminSecretRegistry,
    GarminTokenStore,
)

PASSWORD = "synthetic-pass-value"
EMAIL = "athlete@example.invalid"
BLOB = '{"di_token": "tok-aaaaaaaaaaaa", "di_refresh_token": "ref-bbbbbbbbbbbb"}'
REFRESHED_BLOB = (
    '{"di_token": "tok-cccccccccccc", "di_refresh_token": "ref-dddddddddddd"}'
)


class GarminConnectAuthenticationError(Exception):
    """Name-matched stand-in for the SDK authentication error."""


class FakeManager:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        yield self._connection

    @contextmanager
    def read_snapshot(self) -> Iterator[sqlite3.Connection]:
        yield self._connection

    @contextmanager
    def unit_of_work(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._connection
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise


class FakeSdkTokens:
    def __init__(self, blob: str) -> None:
        self.blob = blob

    def dumps(self) -> str:
        return self.blob


class FakeClient:
    """Mimics the parts of ``garminconnect.Garmin`` the use case calls."""

    def __init__(
        self,
        *,
        needs_mfa: bool = False,
        blob: str = BLOB,
        login_error: BaseException | None = None,
        mfa_codes: tuple[str, ...] = (),
    ) -> None:
        self.needs_mfa = needs_mfa
        self.login_error = login_error
        self.mfa_codes = mfa_codes
        self.client = FakeSdkTokens(blob)
        self.resumed_with: list[str] = []

    def login(self, *_: Any) -> tuple[bool, None]:
        if self.login_error is not None:
            raise self.login_error
        return self.needs_mfa, None

    def resume_login(self, _state: Any, code: str) -> None:
        self.resumed_with.append(code)
        if code not in self.mfa_codes:
            raise RuntimeError("SDK says: wrong code 'xyz' for synthetic account")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class GarminLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.tokenstore = self.root / "garmin_tokens"
        self.config = load_config(
            self.root, self.root / "data", {"APP_PASSWORD": "x" * 12}
        )
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        self.key_values = KeyValueRepository(lambda: "2026-10-18T00:00:00Z")
        self.registry = GarminSecretRegistry()
        self.clock = FakeClock()
        self.clients: list[FakeClient] = []
        self.next_client: FakeClient = FakeClient()
        self.factory_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.tokens = GarminTokenStore(
            database_manager=lambda: FakeManager(self.connection),
            database_lock=nullcontext,
            key_values=self.key_values,
            tokenstore_path=lambda: str(self.tokenstore),
            registry=self.registry,
        )
        self.service = GarminLoginService(
            config=lambda: self.config,
            client_factory=self._factory,
            tokens=self.tokens,
            registry=self.registry,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.connection.close()
        self._temporary.cleanup()

    def _factory(self, *args: Any, **kwargs: Any) -> FakeClient:
        self.factory_calls.append((args, kwargs))
        client = self.next_client
        self.clients.append(client)
        return client

    def _stored(self, key: str) -> str | None:
        return self.key_values.get(self.connection, key)

    def _login_body(self) -> dict[str, str]:
        return {"email": EMAIL, "password": PASSWORD}

    def test_login_success_stores_tokens_without_password(self):
        self.next_client = FakeClient()
        result = self.service.login(self._login_body())
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["source"], "db")
        self.assertTrue(result["connected"])
        self.assertFalse(result["mfa_pending"])
        self.assertEqual(self._stored(GARMIN_TOKENS_KEY), BLOB)
        self.assertTrue(self.factory_calls[0][1]["return_on_mfa"])
        # The password is used for the call only; it is not stored anywhere.
        stored_values = " ".join(
            str(row["value"]) for row in self.connection.execute("SELECT value FROM kv")
        )
        self.assertNotIn(PASSWORD, stored_values)
        self.assertNotIn(PASSWORD, self.registry.values())

    def test_mfa_wrong_code_keeps_slot_then_correct_code_connects(self):
        self.next_client = FakeClient(needs_mfa=True, mfa_codes=("123456",))
        result = self.service.login(self._login_body())
        self.assertEqual(result["status"], "mfa_required")
        self.assertTrue(result["mfa_pending"])
        self.assertIsNone(self._stored(GARMIN_TOKENS_KEY))

        with self.assertRaises(AppError) as wrong:
            self.service.submit_mfa({"code": "000000"})
        self.assertEqual(wrong.exception.status, 401)
        self.assertNotIn("SDK says", wrong.exception.message)
        self.assertTrue(self.service.status()["mfa_pending"])

        result = self.service.submit_mfa({"code": "123456"})
        self.assertEqual(result["status"], "connected")
        self.assertFalse(result["mfa_pending"])
        self.assertEqual(self._stored(GARMIN_TOKENS_KEY), BLOB)

    def test_mfa_slot_expires_after_ttl(self):
        self.next_client = FakeClient(needs_mfa=True, mfa_codes=("123456",))
        self.service.login(self._login_body())
        self.clock.now += MFA_TTL_SECONDS + 1
        with self.assertRaises(AppError) as expired:
            self.service.submit_mfa({"code": "123456"})
        self.assertEqual(expired.exception.status, 409)
        self.assertFalse(self.service.status()["mfa_pending"])
        self.assertIsNone(self._stored(GARMIN_TOKENS_KEY))

    def test_submit_without_pending_login_is_rejected(self):
        with self.assertRaises(AppError) as missing:
            self.service.submit_mfa({"code": "123456"})
        self.assertEqual(missing.exception.status, 409)

    def test_bad_mfa_format_is_rejected_before_sdk_call(self):
        for body in ({"code": "12a"}, {"code": "12"}, {"code": ""}, {}, "x"):
            with self.assertRaises(AppError) as bad:
                self.service.submit_mfa(body)
            self.assertEqual(bad.exception.status, 400)

    def test_login_error_mapping_and_no_sdk_text(self):
        self.next_client = FakeClient(
            login_error=GarminConnectAuthenticationError(f"bad {PASSWORD}")
        )
        with self.assertRaises(AppError) as auth:
            self.service.login(self._login_body())
        self.assertEqual(auth.exception.status, 401)
        self.assertNotIn(PASSWORD, auth.exception.message)

        self.next_client = FakeClient(login_error=ConnectionError("network down"))
        with self.assertRaises(AppError) as network:
            self.service.login(self._login_body())
        self.assertEqual(network.exception.status, 502)

    def test_disconnect_clears_tokens_and_blocks_legacy_file(self):
        self.tokenstore.write_text(BLOB, encoding="utf-8")
        self.next_client = FakeClient()
        self.service.login(self._login_body())
        result = self.service.disconnect()
        self.assertEqual(result["status"], "disconnected")
        self.assertFalse(result["connected"])
        self.assertEqual(result["source"], "none")
        self.assertIsNone(self._stored(GARMIN_TOKENS_KEY))
        self.assertEqual(self._stored(GARMIN_TOKENSTORE_STATE_KEY), "disconnected")
        # The preserved file is not imported again after an explicit disconnect.
        self.assertTrue(self.tokenstore.exists())
        self.assertEqual(self.tokens.source(), "none")
        self.assertEqual(
            self.tokens.login_argument(),
            str(self.tokenstore) + ".disconnected",
        )

    def test_legacy_file_is_imported_once_and_never_deleted(self):
        self.tokenstore.write_text(BLOB, encoding="utf-8")
        self.assertEqual(self.service.status()["source"], "file")
        self.assertTrue(self.service.status()["connected"])
        self.assertEqual(self.tokens.login_argument(), str(self.tokenstore))

        client = FakeClient(blob=BLOB)
        self.tokens.write_back(client)
        self.assertEqual(self._stored(GARMIN_TOKENS_KEY), BLOB)
        self.assertTrue(self.tokenstore.exists())
        self.assertEqual(self.service.status()["source"], "db")

    def test_refreshed_tokens_are_written_back(self):
        self.next_client = FakeClient(blob=BLOB)
        self.service.login(self._login_body())
        self.tokens.write_back(FakeClient(blob=REFRESHED_BLOB))
        self.assertEqual(self._stored(GARMIN_TOKENS_KEY), REFRESHED_BLOB)
        self.assertNotIn(BLOB, self.registry.values())
        self.assertIn("tok-cccccccccccc", self.registry.values())

    def test_write_back_failure_keeps_stored_blob_and_hides_sdk_text(self):
        self.next_client = FakeClient(blob=BLOB)
        self.service.login(self._login_body())

        class BrokenClient:
            @property
            def client(self):
                raise RuntimeError(f"leaked {BLOB}")

        self.tokens.write_back(BrokenClient())
        self.assertEqual(self._stored(GARMIN_TOKENS_KEY), BLOB)

    def test_token_values_are_registered_for_redaction(self):
        self.next_client = FakeClient(blob=BLOB)
        self.service.login(self._login_body())
        redactor = Redactor(lambda: self.config, extra_secrets=self.registry.values)
        redacted = redactor.redact_text("token=tok-aaaaaaaaaaaa ok")
        self.assertNotIn("tok-aaaaaaaaaaaa", redacted)

    def test_status_shape_and_configured_signal(self):
        status = self.service.status()
        self.assertEqual(set(status), {"connected", "source", "mfa_pending"})
        self.assertFalse(
            garmin_tokens_connected(lambda key: self._stored(key), str(self.tokenstore))
        )
        self.next_client = FakeClient()
        self.service.login(self._login_body())
        self.assertTrue(
            garmin_tokens_connected(lambda key: self._stored(key), str(self.tokenstore))
        )

    def test_post_routes_dispatch_and_do_not_echo_body(self):
        routes = GarminPostRoutes(lambda: self.service)
        sent: list[tuple[int, dict[str, Any]]] = []

        class Handler:
            def read_json(self) -> dict[str, Any]:
                return {"email": EMAIL, "password": PASSWORD}

            def send_json(self, status: int, payload: dict[str, Any]) -> None:
                sent.append((status, payload))

        self.next_client = FakeClient()
        self.assertTrue(routes.handle(Handler(), LOGIN_PATH))
        self.assertEqual(sent[-1][0], 200)
        self.assertNotIn(PASSWORD, repr(sent[-1][1]))
        self.assertTrue(routes.handle(Handler(), DISCONNECT_PATH))
        self.assertEqual(sent[-1][1]["status"], "disconnected")
        self.assertFalse(routes.handle(Handler(), "/api/garmin/other"))


if __name__ == "__main__":
    unittest.main()
