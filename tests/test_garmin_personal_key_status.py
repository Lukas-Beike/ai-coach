"""Garmin Personal API key expiry, rejection, SDK skip hint and redaction."""

from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import date
from typing import Any, cast
from unittest.mock import Mock, patch

from backend.backup.export import PrivacyArchiveExportService
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.observability import Redactor
from backend.provider_credentials import (
    PROVIDER_CREDENTIALS_KEY,
    credential_status,
    effective_config,
    validated_changes,
)
from backend.providers import http as provider_http
from backend.providers.connection_check_probes import build_probes
from backend.providers.connection_checks import (
    AUTH_FAILED,
    SUCCESS,
    ProviderConnectionChecks,
)
from backend.providers.garmin_personal import PERSONAL_KEY_REJECTED_REASON
from backend.sync.garmin_personal_status import (
    PERSONAL_KEY_WARNING_DAYS,
    personal_key_state,
    sdk_skipped_view,
)
from backend.sync.garmin_service import GarminRemoteReader
from tests.support import make_config

SYNTHETIC_KEY = "synthetic-personal-key-1723"
SYNTHETIC_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzeW50aGV0aWMifQ.c2lnbmF0dXJl"
TODAY = date(2026, 11, 6)


def _config(**changes: Any) -> Any:
    settings: dict[str, Any] = {
        "openai_base_url": "",
        "openai_model": "",
        "intervals_athlete_id": "",
        "data_retention_days": 30,
        "garmin_email": "",
        "garmin_password": "",
        "garmin_tokenstore": "missing-tokenstore",
        "garmin_personal_api_key": SYNTHETIC_KEY,
    }
    return make_config(**{**settings, **changes})


class PersonalKeyStateTests(unittest.TestCase):
    def test_state_follows_the_entered_expiry_date(self) -> None:
        cases = {
            "": ("expiry_missing", None),
            "not-a-date": ("expiry_missing", None),
            "2026-12-31": ("valid", 55),
            "2026-11-20": ("expiring", PERSONAL_KEY_WARNING_DAYS),
            "2026-11-06": ("expiring", 0),
            "2026-11-05": ("expired", -1),
        }
        for expires, (state, days_left) in cases.items():
            with self.subTest(expires=expires):
                view = personal_key_state(
                    _config(garmin_personal_api_key_expires=expires), TODAY
                )
                self.assertTrue(view["configured"])
                self.assertEqual(view["state"], state)
                self.assertEqual(view["days_left"], days_left)
                self.assertNotIn(SYNTHETIC_KEY, json.dumps(view))

    def test_a_rejected_key_wins_over_every_expiry_state(self) -> None:
        for expires in ("", "2026-12-31", "2026-11-05"):
            with self.subTest(expires=expires):
                view = personal_key_state(
                    _config(garmin_personal_api_key_expires=expires),
                    TODAY,
                    rejected=True,
                )
                self.assertEqual(view["state"], "rejected")

    def test_key_exchange_reports_acceptance_and_rejection(self) -> None:
        from backend.providers.garmin_personal import GarminPersonalClient
        from tests.test_garmin_personal_transport import (
            SYNTHETIC_KEY as TRANSPORT_KEY,
        )
        from tests.test_garmin_personal_transport import FakePersonalApi

        results: list[bool] = []
        GarminPersonalClient(
            TRANSPORT_KEY, opener=FakePersonalApi(), key_result=results.append
        ).verify_key()
        rejected = GarminPersonalClient(
            "expired-key-1723", opener=FakePersonalApi(), key_result=results.append
        )
        with self.assertRaises(provider_http.ProviderHTTPError):
            rejected.verify_key()
        self.assertEqual(results, [True, False])

    def test_without_a_key_only_the_flag_is_reported(self) -> None:
        view = personal_key_state(
            _config(
                garmin_personal_api_key="",
                garmin_personal_api_key_expires="2026-11-05",
            ),
            TODAY,
        )
        self.assertEqual(view, {"configured": False})

    def test_sdk_skip_view_keeps_only_known_reasons(self) -> None:
        at = "2026-11-06T08:00:00+00:00"
        self.assertEqual(
            sdk_skipped_view({"reason": "mfa_required", "at": at, "x": 1}),
            {"reason": "mfa_required", "at": at},
        )
        self.assertIsNone(sdk_skipped_view({"reason": "secret text", "at": at}))
        self.assertIsNone(sdk_skipped_view(None))


class ExpiryCredentialTests(unittest.TestCase):
    def test_expiry_must_be_an_iso_date(self) -> None:
        self.assertEqual(
            validated_changes({"garmin_personal_api_key_expires": " 2026-12-31 "}),
            {"garmin_personal_api_key_expires": "2026-12-31"},
        )
        with self.assertRaises(AppError) as rejected:
            validated_changes({"garmin_personal_api_key_expires": "31.12.2026"})
        self.assertEqual(rejected.exception.status, 400)

    def test_a_stored_key_never_takes_the_environment_expiry(self) -> None:
        env = _config(
            garmin_personal_api_key="env-key-1723",
            garmin_personal_api_key_expires="2027-01-31",
        )
        stored = {"garmin_personal_api_key": SYNTHETIC_KEY}

        effective = effective_config(env, stored)
        status = credential_status(env, stored)

        self.assertEqual(effective.garmin_personal_api_key_expires, "")
        expiry = status["fields"]["garmin_personal_api_key_expires"]
        self.assertEqual(expiry["source"], "none")
        self.assertEqual(expiry["value"], "")
        self.assertEqual(
            effective_config(env, {}).garmin_personal_api_key_expires, "2027-01-31"
        )


class _KeyValues:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, _db: Any, key: str) -> str | None:
        return self.values.get(key)

    def set(self, _db: Any, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, _db: Any, key: str) -> None:
        self.values.pop(key, None)


class KeyChangeClearsExpiryTests(unittest.TestCase):
    def test_saving_or_removing_the_key_clears_its_expiry(self) -> None:
        from contextlib import contextmanager, nullcontext

        from backend.provider_credentials import ProviderCredentialService

        key_values = _KeyValues()

        class Manager:
            @contextmanager
            def unit_of_work(self) -> Any:
                yield None

            reader = unit_of_work

        holder = {"config": _config(garmin_personal_api_key="")}
        service = ProviderCredentialService(
            env_config=holder["config"],
            database_manager=lambda: cast(DatabaseManager, Manager()),
            database_lock=nullcontext,
            key_values=cast(KeyValueRepository, key_values),
            apply_config=lambda config: holder.update(config=config),
            current_config=lambda: holder["config"],
        )

        def stored() -> dict[str, str]:
            return json.loads(key_values.values.get(PROVIDER_CREDENTIALS_KEY, "{}"))

        service.update(
            {
                "garmin_personal_api_key": SYNTHETIC_KEY,
                "garmin_personal_api_key_expires": "2026-12-31",
            }
        )
        self.assertEqual(stored()["garmin_personal_api_key_expires"], "2026-12-31")
        self.assertEqual(holder["config"].garmin_personal_api_key_expires, "2026-12-31")

        key_values.values["garmin_personal_key_rejected"] = "2026-11-06T08:00:00Z"
        service.update({"garmin_personal_api_key": "renewed-key-1723"})
        self.assertNotIn("garmin_personal_api_key_expires", stored())
        self.assertNotIn("garmin_personal_key_rejected", key_values.values)
        self.assertEqual(holder["config"].garmin_personal_api_key_expires, "")

        service.update({"garmin_personal_api_key_expires": "2027-02-01"})
        service.update({"garmin_personal_api_key": None})
        self.assertNotIn(PROVIDER_CREDENTIALS_KEY, key_values.values)


def _reader(config: Any, factory: Any, tokens: Any = None) -> GarminRemoteReader:
    return GarminRemoteReader(
        config,
        factory,
        Mock(),
        Mock(),
        lambda value: value,
        Mock(),
        lambda: "2026-11-06T08:00:00+00:00",
        lambda: TODAY,
        date(2000, 1, 1),
        90,
        -1,
        garmin_tokens=tokens,
    )


def _factory(login: Any) -> Any:
    sdk = Mock()
    sdk.login.side_effect = login
    factory = Mock()
    factory.available.return_value = True
    factory.create.return_value = sdk
    return factory


def _external_call(_service: str, _operation: str, call: Any, _details: Any) -> Any:
    return call()


class SdkSkipHintTests(unittest.TestCase):
    def test_failed_sdk_login_records_the_skip_and_a_success_clears_it(self) -> None:
        def fail(_argument: Any) -> Any:
            raise RuntimeError("synthetic SDK login failure")

        config = _config(garmin_email="athlete@example.invalid", garmin_password="x")
        failing = _reader(config, _factory(fail))
        failing._authenticated_client(_external_call)
        failing._state_service.record_sdk_skipped.assert_called_once_with(
            "login_failed"
        )

        working = _reader(config, _factory(lambda _argument: (None, None)))
        client, _argument = working._authenticated_client(_external_call)
        self.assertIsNotNone(client.sdk)
        working._state_service.clear_sdk_skipped.assert_called_once_with()
        working._state_service.record_sdk_skipped.assert_not_called()


class _Tokens:
    def __init__(self, connected: bool) -> None:
        self._connected = connected

    def connected(self) -> bool:
        return self._connected

    def login_argument(self) -> str:
        return "synthetic-token-blob"

    def write_back(self, _client: Any, _argument: str) -> None:
        pass


class CheckStoredLoginTests(unittest.TestCase):
    def _personal(self, error: BaseException | None = None) -> Mock:
        personal = Mock()
        if error is not None:
            personal.verify_key.side_effect = error
        return personal

    def test_key_alone_checks_only_the_token_exchange(self) -> None:
        factory = _factory(lambda _argument: (None, None))
        reader = _reader(_config(), factory, _Tokens(False))
        personal = self._personal()
        with patch(
            "backend.sync.garmin_service._personal_client", return_value=personal
        ):
            reader.check_stored_login()
        personal.verify_key.assert_called_once_with()
        factory.create.assert_not_called()

    def test_rejected_key_names_the_key_without_its_value(self) -> None:
        rejected = provider_http.classify_provider_status(401, "garmin")
        reader = _reader(_config(), _factory(None), _Tokens(True))
        with (
            patch(
                "backend.sync.garmin_service._personal_client",
                return_value=self._personal(rejected),
            ),
            self.assertRaises(AppError) as raised,
        ):
            reader.check_stored_login()
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.reason, PERSONAL_KEY_REJECTED_REASON)
        self.assertNotIn(SYNTHETIC_KEY, str(raised.exception))

    def test_unreachable_personal_api_is_not_a_rejection(self) -> None:
        reader = _reader(_config(), _factory(None), _Tokens(False))
        with (
            patch(
                "backend.sync.garmin_service._personal_client",
                return_value=self._personal(TimeoutError("synthetic")),
            ),
            self.assertRaises(AppError) as raised,
        ):
            reader.check_stored_login()
        self.assertEqual(raised.exception.status, 502)
        self.assertNotEqual(raised.exception.reason, PERSONAL_KEY_REJECTED_REASON)

    def test_valid_key_then_checks_the_connected_sdk_login(self) -> None:
        def fail(_argument: Any) -> Any:
            raise RuntimeError("synthetic SDK login failure")

        reader = _reader(_config(), _factory(fail), _Tokens(True))
        personal = self._personal()
        with (
            patch(
                "backend.sync.garmin_service._personal_client", return_value=personal
            ),
            self.assertRaises(AppError) as raised,
        ):
            reader.check_stored_login()
        personal.verify_key.assert_called_once_with()
        self.assertEqual(raised.exception.reason, "reconnect_required")


class GarminProbeTests(unittest.TestCase):
    def _checks(self, config: Any, login: Any) -> ProviderConnectionChecks:
        probes = build_probes(
            config=lambda: config,
            request=Mock(),
            default_openai_base_url="https://api.openai.com/v1",
            intervals_get=Mock(),
            wahoo_status=dict,
            wahoo_user=Mock(),
            garmin_connected=lambda: False,
            garmin_fingerprint=lambda: "",
            garmin_login=login,
        )
        return ProviderConnectionChecks({"garmin": probes["garmin"]})

    def test_key_alone_is_checkable_and_a_rejection_names_the_key(self) -> None:
        def reject() -> None:
            raise AppError(401, "rejected", reason=PERSONAL_KEY_REJECTED_REASON)

        checks = self._checks(_config(), reject)
        result = checks.check("garmin")
        self.assertEqual(result["status"], AUTH_FAILED)
        self.assertIn("Personal-API-Schlüssel", result["guidance"])
        self.assertEqual(checks.status("garmin")["guidance"], result["guidance"])

    def test_sdk_rejection_keeps_the_login_guidance(self) -> None:
        def reject() -> None:
            raise AppError(401, "rejected", reason="reconnect_required")

        result = self._checks(_config(), reject).check("garmin")
        self.assertEqual(result["status"], AUTH_FAILED)
        self.assertNotIn("Personal-API-Schlüssel", result["guidance"])

    def test_success_and_no_credentials(self) -> None:
        self.assertEqual(
            self._checks(_config(), lambda: None).check("garmin")["status"], SUCCESS
        )
        unconfigured = self._checks(_config(garmin_personal_api_key=""), Mock())
        self.assertEqual(unconfigured.status("garmin")["status"], "not_configured")


class RedactionTests(unittest.TestCase):
    def test_key_and_jwt_never_reach_logs_or_diagnostics(self) -> None:
        redactor = Redactor(lambda: _config())
        text = (
            f"ApiKey {SYNTHETIC_KEY} Authorization: Bearer {SYNTHETIC_JWT} "
            f"token={SYNTHETIC_JWT}"
        )
        for safe in (
            redactor.redact_text(text),
            json.dumps(redactor.sanitize_log_value({"detail": text})),
            json.dumps(redactor.sanitize_diagnostic_value({"detail": text})),
        ):
            self.assertNotIn(SYNTHETIC_KEY, safe)
            self.assertNotIn(SYNTHETIC_JWT, safe)

    def test_backup_export_omits_the_stored_key_and_expiry(self) -> None:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        db.executemany(
            "INSERT INTO kv VALUES (?, ?, '2026-11-06')",
            [
                (
                    PROVIDER_CREDENTIALS_KEY,
                    json.dumps(
                        {
                            "garmin_personal_api_key": SYNTHETIC_KEY,
                            "garmin_personal_api_key_expires": "2026-12-31",
                        }
                    ),
                ),
                ("last_garmin_sync_at", "2026-11-06T08:00:00Z"),
            ],
        )
        exported = json.dumps(PrivacyArchiveExportService._application_state(db))
        db.close()
        self.assertNotIn(SYNTHETIC_KEY, exported)
        self.assertNotIn(PROVIDER_CREDENTIALS_KEY, exported)
        self.assertIn("last_garmin_sync_at", exported)


if __name__ == "__main__":
    unittest.main()
