"""Wahoo OAuth connection: configuration, transport, state, tokens, redaction."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.parse import parse_qs, urlsplit

from backend.canonical.vocabulary import ProviderId
from backend.config import SETTINGS_SECRET_KEYS, SETTINGS_VALUE_KEYS, load_config
from backend.errors import AppError
from backend.http_api.wahoo import WahooGetRoutes, WahooPostRoutes
from backend.observability import REDACTED_URL_QUERY_KEYS, redact_request_query
from backend.providers.wahoo_oauth import WAHOO_SCOPES, WahooOAuthClient
from backend.sync.wahoo_connection import (
    NOT_CONFIGURED_MESSAGE,
    STATE_TTL,
    WAHOO_SECRET_KEYS,
    WAHOO_STATE_KEY,
    WAHOO_TOKENS_KEY,
    WahooConnectionService,
    connection_status,
)

REDIRECT = "https://coach.example.invalid/api/wahoo/callback"
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


class FakeKeyValues:
    """In-memory stand-in for KeyValueRepository (no SQLCipher required)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, _db, key):
        return self.data.get(key)

    def set(self, _db, key, value):
        self.data[key] = value

    def delete(self, _db, key):
        self.data.pop(key, None)


class FakeManager:
    @contextmanager
    def unit_of_work(self):
        yield object()

    reader = unit_of_work


def make_config(**overrides):
    with tempfile.TemporaryDirectory() as directory:
        env = {
            "APP_PASSWORD": "test-password-123",
            "WAHOO_CLIENT_ID": "client-id-1",
            "WAHOO_CLIENT_SECRET": "client-secret-1",
            "WAHOO_REDIRECT_URI": REDIRECT,
            **overrides,
        }
        return load_config(Path(directory), Path(directory), env)


def grant_payload(access="access-1", refresh="refresh-1", expires_in=3600, **extra):
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
        "token_type": "Bearer",
        **extra,
    }


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> str:
        return self.now.isoformat()


class WahooConfigTests(unittest.TestCase):
    def test_configured_only_with_all_three_values(self):
        self.assertTrue(make_config().wahoo_configured)
        for key in ("WAHOO_CLIENT_ID", "WAHOO_CLIENT_SECRET", "WAHOO_REDIRECT_URI"):
            with self.subTest(missing=key):
                self.assertFalse(make_config(**{key: "  "}).wahoo_configured)

    def test_secret_and_value_settings_are_classified(self):
        self.assertIn("WAHOO_CLIENT_SECRET", SETTINGS_SECRET_KEYS)
        self.assertIn("WAHOO_CLIENT_ID", SETTINGS_VALUE_KEYS)
        self.assertIn("WAHOO_REDIRECT_URI", SETTINGS_VALUE_KEYS)
        self.assertNotIn("WAHOO_CLIENT_SECRET", SETTINGS_VALUE_KEYS)

    def test_provider_id_is_registered_as_a_read_only_provider(self):
        from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY

        self.assertIn(ProviderId.WAHOO.value, DEFAULT_PROVIDER_REGISTRY.ids())


class WahooOAuthClientTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.request = Mock(return_value=grant_payload())
        self.client = WahooOAuthClient(lambda: self.config, self.request)

    def test_authorize_url_carries_expected_parameters(self):
        url = self.client.authorize_url("state-xyz")
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.assertEqual(
            f"{parts.scheme}://{parts.netloc}{parts.path}",
            "https://api.wahooligan.com/oauth/authorize",
        )
        self.assertEqual(query["client_id"], ["client-id-1"])
        self.assertEqual(query["redirect_uri"], [REDIRECT])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["state"], ["state-xyz"])
        self.assertEqual(query["scope"], [" ".join(WAHOO_SCOPES)])
        self.assertNotIn("client-secret-1", url)

    def test_code_exchange_posts_form_body_without_query_secrets(self):
        grant = self.client.exchange_code("code-abc")
        args, kwargs = self.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(urlsplit(args[1]).query, "")
        form = parse_qs(kwargs["raw_body"].decode("ascii"))
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertEqual(form["code"], ["code-abc"])
        self.assertEqual(form["client_secret"], ["client-secret-1"])
        self.assertEqual(form["redirect_uri"], [REDIRECT])
        self.assertEqual(grant.access_token, "access-1")
        self.assertEqual(grant.scope, " ".join(WAHOO_SCOPES))
        self.assertNotIn("access-1", repr(grant))

    def test_invalid_token_response_is_rejected(self):
        for payload in (
            None,
            {},
            grant_payload(access=""),
            grant_payload(expires_in=0),
        ):
            with self.subTest(payload=payload):
                self.request.return_value = payload
                with self.assertRaises(AppError):
                    self.client.exchange_code("code")

    def test_deauthorize_uses_bearer_delete(self):
        self.client.deauthorize("access-1")
        args, kwargs = self.request.call_args
        self.assertEqual(args[0], "DELETE")
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer access-1"})


class WahooConnectionServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.clock = Clock()
        self.values = FakeKeyValues()
        self.request = Mock(return_value=grant_payload())
        self.states = iter(f"state-{index}" for index in range(10))
        self.service = self.make_service(lambda: self.config)

    def make_service(self, config):
        return WahooConnectionService(
            config=config,
            oauth=lambda: WahooOAuthClient(config, self.request),
            database_manager=lambda: FakeManager(),
            database_lock=lambda: MagicMock(),
            key_values=self.values,
            utc_now=self.clock,
            token_factory=lambda: next(self.states),
        )

    def connect(self):
        self.service.start_authorization()
        return self.service.complete_authorization("code-1", "state-0")

    def test_not_configured_is_a_clear_german_error(self):
        self.config = make_config(WAHOO_CLIENT_SECRET="")
        with self.assertRaises(AppError) as caught:
            self.service.start_authorization()
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.message, NOT_CONFIGURED_MESSAGE)
        self.assertIn("nicht konfiguriert", caught.exception.message)
        self.assertEqual(self.values.data, {})

    def test_redirect_must_be_https(self):
        self.config = make_config(WAHOO_REDIRECT_URI="http://coach.example.invalid/cb")
        with self.assertRaises(AppError) as caught:
            self.service.start_authorization()
        self.assertEqual(caught.exception.reason, "invalid_redirect_uri")

    def test_start_stores_only_state_digest_with_ttl(self):
        result = self.service.start_authorization()
        self.assertIn("state=state-0", result["authorize_url"])
        stored = json.loads(self.values.data[WAHOO_STATE_KEY])
        self.assertNotIn("state-0", self.values.data[WAHOO_STATE_KEY])
        self.assertEqual(datetime.fromisoformat(stored["expires_at"]), NOW + STATE_TTL)

    def test_successful_callback_stores_tokens_and_reports_status_without_them(self):
        self.assertEqual(self.connect(), "connected")
        stored = json.loads(self.values.data[WAHOO_TOKENS_KEY])
        self.assertEqual(
            set(stored),
            {"access_token", "refresh_token", "expires_at", "scope", "connected_at"},
        )
        self.assertEqual(stored["access_token"], "access-1")
        self.assertNotIn(WAHOO_STATE_KEY, self.values.data)
        status = self.service.status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["connected_at"], NOW.isoformat())
        self.assertNotIn("access-1", json.dumps(status))
        self.assertNotIn("refresh-1", json.dumps(status))

    def test_state_is_single_use(self):
        self.assertEqual(self.connect(), "connected")
        self.request.reset_mock()
        self.assertEqual(
            self.service.complete_authorization("code-2", "state-0"), "error"
        )
        self.request.assert_not_called()

    def test_wrong_state_is_rejected_without_exchange_or_cancelling_login(self):
        self.service.start_authorization()
        for state in ("other", "", None):
            self.assertEqual(
                self.service.complete_authorization("code", state), "error"
            )
        self.request.assert_not_called()
        self.assertIn(WAHOO_STATE_KEY, self.values.data)
        self.assertEqual(
            self.service.complete_authorization("code", "state-0"), "connected"
        )

    def test_expired_state_is_rejected_and_removed(self):
        self.service.start_authorization()
        self.clock.now = NOW + STATE_TTL + timedelta(seconds=1)
        self.assertEqual(
            self.service.complete_authorization("code", "state-0"), "error"
        )
        self.request.assert_not_called()
        self.assertNotIn(WAHOO_STATE_KEY, self.values.data)

    def test_callback_error_or_missing_code_does_not_exchange(self):
        self.service.start_authorization()
        self.assertEqual(
            self.service.complete_authorization(None, "state-0", "access_denied"),
            "error",
        )
        self.request.assert_not_called()
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_failed_exchange_is_an_error_without_tokens(self):
        self.service.start_authorization()
        self.request.side_effect = AppError(502, "boom", upstream_status=401)
        self.assertEqual(
            self.service.complete_authorization("code", "state-0"), "error"
        )
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_fresh_token_is_returned_without_refresh(self):
        self.connect()
        self.request.reset_mock()
        self.assertEqual(self.service.access_token(), "access-1")
        self.request.assert_not_called()

    def test_refresh_rotates_and_persists_both_tokens(self):
        self.connect()
        self.clock.now = NOW + timedelta(seconds=3600 - 60)  # inside the margin
        self.request.return_value = grant_payload(
            access="access-2", refresh="refresh-2"
        )
        self.assertEqual(self.service.access_token(), "access-2")
        form = parse_qs(self.request.call_args.kwargs["raw_body"].decode("ascii"))
        self.assertEqual(form["grant_type"], ["refresh_token"])
        self.assertEqual(form["refresh_token"], ["refresh-1"])
        stored = json.loads(self.values.data[WAHOO_TOKENS_KEY])
        self.assertEqual(stored["refresh_token"], "refresh-2")
        self.assertEqual(stored["connected_at"], NOW.isoformat())

    def test_rejected_refresh_requires_reconnect_and_drops_tokens(self):
        self.connect()
        self.clock.now = NOW + timedelta(hours=2)
        self.request.side_effect = AppError(502, "bad", upstream_status=400)
        with self.assertRaises(AppError) as caught:
            self.service.access_token()
        self.assertEqual(caught.exception.reason, "wahoo_reconnect_required")
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_unauthorized_refresh_also_requires_reconnect(self):
        self.connect()
        self.clock.now = NOW + timedelta(hours=2)
        self.request.side_effect = AppError(502, "bad", upstream_status=401)
        with self.assertRaises(AppError) as caught:
            self.service.access_token()
        self.assertEqual(caught.exception.reason, "wahoo_reconnect_required")
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_invalidating_the_rejected_token_drops_the_grant(self):
        self.connect()
        self.service.invalidate_access_token("access-1")
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)
        self.assertFalse(self.service.status()["connected"])

    def test_invalidating_an_older_token_keeps_a_newer_grant(self):
        self.connect()
        self.service.invalidate_access_token("access-0")
        self.assertIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_unexpected_exchange_exception_still_ends_in_error_outcome(self):
        self.service.start_authorization()
        self.request.side_effect = TimeoutError("slow")
        self.assertEqual(
            self.service.complete_authorization("code", "state-0"), "error"
        )
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_transient_refresh_failure_keeps_tokens(self):
        self.connect()
        self.clock.now = NOW + timedelta(hours=2)
        self.request.side_effect = AppError(502, "down", upstream_status=503)
        with self.assertRaises(AppError):
            self.service.access_token()
        self.assertIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_access_token_when_not_connected(self):
        with self.assertRaises(AppError) as caught:
            self.service.access_token()
        self.assertEqual(caught.exception.reason, "wahoo_not_connected")

    def test_disconnect_revokes_remotely_then_deletes_tokens(self):
        self.connect()
        self.request.reset_mock()
        result = self.service.disconnect()
        self.assertEqual(self.request.call_args.args[0], "DELETE")
        self.assertTrue(result["remote_revoked"])
        self.assertFalse(result["connected"])
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)
        self.assertFalse(self.service.status()["connected"])

    def test_disconnect_succeeds_locally_when_remote_revoke_fails(self):
        self.connect()
        self.request.side_effect = AppError(502, "down", upstream_status=500)
        result = self.service.disconnect()
        self.assertFalse(result["remote_revoked"])
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_disconnect_during_code_exchange_prevents_reconnect(self):
        self.service.start_authorization()

        def exchange_while_disconnecting(*_args, **_kwargs):
            self.request.side_effect = None
            self.service.disconnect()
            return grant_payload()

        self.request.side_effect = exchange_while_disconnecting
        self.assertEqual(
            self.service.complete_authorization("code-1", "state-0"), "error"
        )
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)
        self.assertFalse(self.service.status()["connected"])

    def test_disconnect_deletes_tokens_after_the_configuration_was_removed(self):
        self.connect()
        self.config = make_config(WAHOO_CLIENT_SECRET="")
        result = self.service.disconnect()
        self.assertFalse(result["connected"])
        self.assertNotIn(WAHOO_TOKENS_KEY, self.values.data)

    def test_disconnect_when_never_connected_is_idempotent(self):
        self.assertFalse(self.service.disconnect()["connected"])
        self.request.assert_not_called()

    def test_status_projection_ignores_garbage(self):
        config = make_config()
        for raw in (None, "", "not-json", "[]", json.dumps({"access_token": "x"})):
            self.assertFalse(connection_status(config, raw)["connected"])

    def test_secret_keys_cover_tokens_and_state(self):
        self.assertEqual(WAHOO_SECRET_KEYS, {WAHOO_TOKENS_KEY, WAHOO_STATE_KEY})


class WahooRouteTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.gate = MagicMock()

    def callback(self, query, outcome):
        self.service.complete_authorization.return_value = outcome
        handler = SimpleNamespace(
            path=f"/api/wahoo/callback?{query}", send_bytes=Mock()
        )
        routes = WahooGetRoutes(lambda: self.service, self.gate)
        self.assertTrue(routes.handle(handler, "/api/wahoo/callback"))
        return handler.send_bytes.call_args

    def test_callback_redirects_to_fixed_targets_without_echo(self):
        call = self.callback("code=c1&state=s1", "connected")
        self.assertEqual(call.args[0], 302)
        self.assertEqual(call.args[3], {"Location": "/?wahoo=connected"})
        self.service.complete_authorization.assert_called_once_with("c1", "s1", None)
        call = self.callback("code=c1&state=s1", "error")
        self.assertEqual(call.args[3], {"Location": "/?wahoo=error"})
        for argument in call.args:
            self.assertNotIn("c1", str(argument))

    def test_other_paths_are_not_handled(self):
        routes = WahooGetRoutes(lambda: self.service, self.gate)
        self.assertFalse(routes.handle(SimpleNamespace(path="/x"), "/api/other"))
        post = WahooPostRoutes(lambda: self.service)
        self.assertFalse(post.handle(SimpleNamespace(), "/api/other"))

    def test_post_routes_dispatch_to_service(self):
        self.service.start_authorization.return_value = {"authorize_url": "u"}
        self.service.disconnect.return_value = {"status": "ok"}
        routes = WahooPostRoutes(lambda: self.service)
        handler = SimpleNamespace(read_json=Mock(return_value={}), send_json=Mock())
        self.assertTrue(routes.handle(handler, "/api/wahoo/connect"))
        handler.send_json.assert_called_with(200, {"authorize_url": "u"})
        self.assertTrue(routes.handle(handler, "/api/wahoo/disconnect"))
        handler.send_json.assert_called_with(200, {"status": "ok"})


class WahooRedactionTests(unittest.TestCase):
    def test_code_and_state_are_masked_in_request_targets(self):
        for key in ("code", "state", "client_secret"):
            self.assertIn(key, REDACTED_URL_QUERY_KEYS)
        text = (
            '"GET /api/wahoo/callback?code=SECRETCODE&state=SECRETSTATE&x=ok HTTP/1.1"'
        )
        redacted = redact_request_query(text)
        self.assertNotIn("SECRETCODE", redacted)
        self.assertNotIn("SECRETSTATE", redacted)
        self.assertIn("x=ok", redacted)
        self.assertEqual(redact_request_query(""), "")
        encoded = redact_request_query("GET /cb?%63ode=SECRETCODE HTTP/1.1")
        self.assertNotIn("SECRETCODE", encoded)


if __name__ == "__main__":
    unittest.main()
