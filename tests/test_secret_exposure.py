"""Stored and configured secrets never reach an export, a report or a log.

Distinctive sentinel values stand in for the Personal API key, the provider API
keys, the Garmin and Wahoo tokens, a session hash and APP_PASSWORD. They are
put into temporary configuration and credential storage through the real write
path, then every user-visible output is scanned: the privacy archive, the JSON
privacy projection, the diagnostics report (with its log projection) and the
log files. The encrypted backup keeps the credentials (a restore needs them), so
it is checked at the byte level instead, which needs SQLCipher.
"""

from __future__ import annotations

import io
import json
import logging
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import sqlcipher3
except ImportError:
    sqlcipher3 = None

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.export import (
    PrivacyArchiveExportConfig,
    PrivacyArchiveExportService,
)
from backend.config import Config
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.db.schema import configure_cipher, initialize_schema
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import (
    DiagnosticReportDependencies,
    DiagnosticReportService,
)
from backend.observability import Redactor, config_secret_values, configure_logging
from backend.privacy import PrivacyDataExportDependencies, PrivacyDataExportService
from backend.provider_credentials import (
    CREDENTIAL_KV_KEYS,
    GARMIN_TOKENS_KEY,
    PERSONAL_KEY_EXPIRES_FIELD,
    PERSONAL_KEY_FIELD,
    PROVIDER_CREDENTIALS_KEY,
    SECRET_FIELDS,
    WAHOO_STATE_KEY,
    WAHOO_TOKENS_KEY,
    ProviderCredentialService,
)
from backend.sync.wahoo_connection import WahooSecretRegistry

STAMP = "2026-10-01T08:00:00+00:00"
# Distinctive, never a real value; none contains another.
SENTINEL_NAMES = (
    "personal_api_key",
    "openai_api_key",
    "intervals_api_key",
    "wahoo_client_secret",
    "yazio_password",
    "garmin_password",
    "app_password",
    "garmin_token",
    "wahoo_access_token",
    "wahoo_oauth_state",
    "session_token_hash",
    "session_csrf_hash",
)
# Built from the names so no secret-like literal sits in the source; the shared
# "SENTINEL-" start and the closing "-end" keep any one from containing another.
SENTINELS = {name: f"SENTINEL-{name}-end" for name in SENTINEL_NAMES}
PERSONAL_KEY_EXPIRY = "2027-03-31"
# Server.py registers the configuration secrets, the Garmin tokens and the Wahoo
# tokens and login state with the redactor. The session hashes are never logged
# by design and so are not registered.
NOT_REGISTERED_WITH_THE_REDACTOR = frozenset(
    {"session_token_hash", "session_csrf_hash"}
)


def make_config() -> Config:
    """A configuration whose secret fields hold sentinels and the rest is neutral."""
    values: dict[str, object] = {}
    for field in fields(Config):
        if field.type in ("str", str):
            values[field.name] = ""
        elif field.type in ("int", int):
            values[field.name] = 0
        elif field.type in ("bool", bool):
            values[field.name] = False
    values.update(
        port=8090,
        openai_api_key=SENTINELS["openai_api_key"],
        openai_base_url="https://api.openai.invalid/v1",
        openai_model="model-test",
        intervals_api_key=SENTINELS["intervals_api_key"],
        garmin_password=SENTINELS["garmin_password"],
        garmin_personal_api_key=SENTINELS["personal_api_key"],
        garmin_personal_api_key_expires=PERSONAL_KEY_EXPIRY,
        app_password=SENTINELS["app_password"],
        wahoo_client_secret=SENTINELS["wahoo_client_secret"],
        yazio_password=SENTINELS["yazio_password"],
        data_retention_days=30,
        sync_history_earliest_date=date(2020, 1, 1),
    )
    return Config(**values)  # type: ignore[arg-type]


class _Manager:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def reader(self):
        yield self.db

    read_snapshot = reader

    @contextmanager
    def unit_of_work(self):
        yield self.db
        self.db.commit()


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Competitions:
    def list(self, db=None):
        return []


class _Adaptive:
    def latest_preview(self, db=None):
        return None

    def status(self, db=None):
        return {}


class _Profile:
    def get_from_db(self, _db):
        return {"name": "Synthetic athlete", "sex": "female"}


def scan(blob: bytes) -> list[str]:
    """Names of the sentinels found in ``blob``."""
    text = blob.decode("utf-8", errors="replace")
    return [name for name, value in SENTINELS.items() if value in text]


class SecretFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "athlete.db"
        self.db = sqlite3.connect(self.database_path)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA foreign_keys = ON")
        initialize_schema(self.db)
        self.db.commit()
        self.key_values = KeyValueRepository(lambda: STAMP)
        self.config = make_config()
        self.live_config = self.config
        self.store_secrets()

    def store_secrets(self) -> None:
        """Write every credential through the real service or its storage keys."""
        env = replace(
            self.config,
            garmin_personal_api_key="",
            garmin_personal_api_key_expires="",
            openai_api_key="",
            intervals_api_key="",
            wahoo_client_secret="",
            yazio_password="",
        )
        self.live_config = env

        def apply(config: Config) -> None:
            self.live_config = config

        ProviderCredentialService(
            env_config=env,
            database_manager=lambda: _Manager(self.db),
            database_lock=lambda: _Lock(),
            key_values=self.key_values,
            apply_config=apply,
            current_config=lambda: self.live_config,
        ).update(
            {
                PERSONAL_KEY_FIELD: SENTINELS["personal_api_key"],
                PERSONAL_KEY_EXPIRES_FIELD: PERSONAL_KEY_EXPIRY,
                "openai_api_key": SENTINELS["openai_api_key"],
                "intervals_api_key": SENTINELS["intervals_api_key"],
                "wahoo_client_secret": SENTINELS["wahoo_client_secret"],
                "yazio_password": SENTINELS["yazio_password"],
            }
        )
        self.key_values.set(
            self.db,
            GARMIN_TOKENS_KEY,
            json.dumps({"di_token": SENTINELS["garmin_token"]}),
        )
        self.key_values.set(
            self.db,
            WAHOO_TOKENS_KEY,
            json.dumps({"access_token": SENTINELS["wahoo_access_token"]}),
        )
        self.key_values.set(self.db, WAHOO_STATE_KEY, SENTINELS["wahoo_oauth_state"])
        self.db.execute(
            "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, "
            "last_seen) VALUES (?, ?, 9e12, ?, ?)",
            (
                SENTINELS["session_token_hash"],
                SENTINELS["session_csrf_hash"],
                STAMP,
                STAMP,
            ),
        )
        self.db.commit()

    def redactor(self) -> Redactor:
        wahoo = WahooSecretRegistry()
        wahoo.replace_tokens(self.key_values.get(self.db, WAHOO_TOKENS_KEY))
        wahoo.hold_state(SENTINELS["wahoo_oauth_state"])
        return Redactor(
            lambda: self.live_config,
            lambda: [SENTINELS["garmin_token"], *wahoo.values()],
        )


class SentinelPlacementTests(SecretFixture):
    def test_the_credentials_are_stored_only_under_the_credential_keys(self):
        # Positive control: the sentinels really are in the database ...
        kept = {
            row["key"]
            for row in self.db.execute("SELECT key, value FROM kv")
            if scan(row["value"].encode())
        }
        self.assertEqual(
            kept,
            {
                PROVIDER_CREDENTIALS_KEY,
                GARMIN_TOKENS_KEY,
                WAHOO_TOKENS_KEY,
                WAHOO_STATE_KEY,
            },
        )
        self.assertLessEqual(kept, CREDENTIAL_KV_KEYS)
        stored = json.loads(
            self.key_values.get(self.db, PROVIDER_CREDENTIALS_KEY) or "{}"
        )
        self.assertEqual(stored[PERSONAL_KEY_FIELD], SENTINELS["personal_api_key"])
        self.assertEqual(stored[PERSONAL_KEY_EXPIRES_FIELD], PERSONAL_KEY_EXPIRY)
        self.assertLessEqual({PERSONAL_KEY_FIELD}, SECRET_FIELDS)
        # ... and no other table holds one, apart from the session row the
        # restore scrubs.
        for table in [
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT IN ('kv', 'sessions')"
            )
        ]:
            with self.subTest(table=table):
                dump = json.dumps(
                    [list(row) for row in self.db.execute(f"SELECT * FROM {table}")],
                    default=str,
                )
                self.assertEqual(scan(dump.encode()), [])

    def test_the_live_configuration_and_the_redaction_cover_the_personal_key(self):
        self.assertEqual(
            self.live_config.garmin_personal_api_key, SENTINELS["personal_api_key"]
        )
        self.assertIn(
            SENTINELS["personal_api_key"], config_secret_values(self.live_config)
        )

    def test_every_secret_looking_configuration_field_is_redacted(self):
        secret_named = {
            field.name
            for field in fields(Config)
            if any(
                part in field.name
                for part in ("password", "secret", "token", "api_key", "email")
            )
            and not field.name.endswith("_expires")
        }
        probe = SimpleNamespace(**{name: f"probe-{name}" for name in secret_named})
        redacted = set(config_secret_values(probe))
        self.assertEqual(
            {f"probe-{name}" for name in secret_named} - redacted,
            set(),
            "a new secret configuration field must be listed in config_secret_values",
        )


class PrivacyExportSecretTests(SecretFixture):
    def archive_blobs(self) -> dict[str, bytes]:
        config = PrivacyArchiveExportConfig(
            data_dir=self.root,
            database_path=self.database_path,
            today=lambda: date(2026, 10, 1),
            utc_now=lambda: STAMP,
            maximum_bytes=50_000_000,
            minimum_free_bytes=0,
            time_limit_seconds=60,
            monotonic=lambda: 0.0,
            disk_usage=lambda _path: SimpleNamespace(free=10**12),
        )
        service = PrivacyArchiveExportService(
            _Manager(self.db),
            self.key_values,
            _Profile(),
            _Competitions(),
            _Adaptive(),
            config,
        )
        with patch(
            "backend.backup.export.planning_season.planning_state", return_value={}
        ):
            path = service.create_file()
        self.addCleanup(path.unlink, missing_ok=True)
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_the_privacy_archive_holds_no_secret(self):
        blobs = self.archive_blobs()
        self.assertIn("application_state.json", blobs)
        for name, blob in blobs.items():
            with self.subTest(member=name):
                self.assertEqual(scan(blob), [])
        state = json.loads(blobs["application_state.json"])
        self.assertFalse(set(state) & CREDENTIAL_KV_KEYS)
        self.assertNotIn(PERSONAL_KEY_EXPIRES_FIELD, json.dumps(state))

    def test_the_json_privacy_projection_holds_no_secret(self):
        service = PrivacyDataExportService(
            PrivacyDataExportDependencies(
                database_manager=_Manager(self.db),
                key_value_repository=self.key_values,
                profile_service=Mock(get=Mock(return_value={})),
                workout_library_service=Mock(list=Mock(return_value=[])),
                competition_service=Mock(list=Mock(return_value=[])),
                training_plan_service=Mock(list=Mock(return_value=[])),
                checkin_service=Mock(context=Mock(return_value={})),
                activity_feedback_service=Mock(context=Mock(return_value={})),
                adaptive_preview_service=Mock(
                    latest_preview=Mock(return_value=None),
                    status=Mock(return_value={}),
                ),
                external_calendar_reader=Mock(list_events=Mock(return_value=[])),
                local_now=lambda: datetime(2026, 10, 1, 8, tzinfo=UTC),
                utc_now=lambda: STAMP,
            )
        )
        with patch("backend.privacy.planning_season.planning_state", return_value={}):
            exported = service.export()
        self.assertEqual(
            scan(json.dumps(exported, default=str).encode()),
            [],
        )
        self.assertFalse(set(exported["application_state"]) & CREDENTIAL_KV_KEYS)


class DiagnosticsAndLogSecretTests(SecretFixture):
    def log_everywhere(self) -> tuple[Path, io.StringIO]:
        log_path = self.root / "logs" / "app.log"
        stream = io.StringIO()
        logger = logging.getLogger(f"synthetic.secret.{id(self)}")
        logger.handlers.clear()
        self.addCleanup(self.close_handlers, logger)
        configure_logging(logger, self.root, log_path, self.redactor(), stream=stream)
        for name, value in SENTINELS.items():
            if name in NOT_REGISTERED_WITH_THE_REDACTOR:
                continue
            logger.info(
                f"request with {value}",
                extra={"event": "synthetic", "context": {name: value, "list": [value]}},
            )
            try:
                raise RuntimeError(f"upstream rejected {value}")
            except RuntimeError:
                logger.warning("failed", exc_info=True, extra={"event": "synthetic"})
        for handler in logger.handlers:
            handler.flush()
        return log_path, stream

    @staticmethod
    def close_handlers(logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    def test_log_files_and_stream_hold_no_secret(self):
        log_path, stream = self.log_everywhere()
        written = log_path.read_bytes()
        self.assertIn(b"synthetic", written, "the log was written")
        self.assertEqual(scan(written), [])
        self.assertEqual(scan(stream.getvalue().encode()), [])

    def test_wahoo_tokens_are_redacted_from_logs(self):
        redactor = self.redactor()
        for name in ("wahoo_access_token", "wahoo_oauth_state"):
            text = redactor.redact_text(f"provider said {SENTINELS[name]}")
            self.assertEqual(scan(text.encode()), [], name)

    def test_the_diagnostics_report_and_its_log_projection_hold_no_secret(self):
        log_path, _stream = self.log_everywhere()
        redactor = self.redactor()
        values = {
            "last_sync_at": "sync-time",
            "last_sync_error": f"failed with {SENTINELS['openai_api_key']}",
            "last_external_calendar_sync_error": SENTINELS["intervals_api_key"],
            PROVIDER_CREDENTIALS_KEY: self.key_values.get(
                self.db, PROVIDER_CREDENTIALS_KEY
            ),
            GARMIN_TOKENS_KEY: self.key_values.get(self.db, GARMIN_TOKENS_KEY),
        }
        key_values = Mock()
        key_values.get.side_effect = lambda _db, key: values.get(key)
        sync_state = Mock()
        sync_state.latest_snapshot.return_value = {}
        canonical_rows = Mock()
        canonical_rows.activity_summaries.return_value = ()
        canonical_rows.observations.return_value = []
        garmin_projection = Mock()
        garmin_projection.public_state.return_value = {"configured": True}
        calendar_reader = Mock()
        calendar_reader.list_events.return_value = []
        profile = Mock()
        profile.get.return_value = {"name": "Synthetic athlete"}
        freshness = Mock()
        freshness.current.return_value = []
        coverage = Mock()
        coverage.coverage.return_value = ()
        capture = Mock()
        capture.status.return_value = {"active": False, "entries": 0}
        capture.entries.return_value = []
        database = Mock()
        database.execute.return_value = SimpleNamespace(
            fetchone=lambda: {"count": 0}, fetchall=list
        )
        manager = Mock()

        @contextmanager
        def read_snapshot():
            yield database

        manager.read_snapshot = read_snapshot
        service = DiagnosticReportService(
            DiagnosticReportDependencies(
                database_manager=manager,
                key_values=key_values,
                config=self.live_config,
                settings=SimpleNamespace(
                    selected_model=lambda: "model-test",
                    selected_thinking_level=lambda: "medium",
                    available_model_options=lambda: [{"id": "model-test"}],
                ),
                app_name="Test Coach",
                app_version="0.0.0",
                utc_now=lambda: STAMP,
                sync_state=sync_state,
                garmin_projection=garmin_projection,
                garmin_client_factory=SimpleNamespace(available=lambda: True),
                garmin_fixture_loader=SimpleNamespace(path=lambda: None),
                provider_state=SimpleNamespace(
                    summary=lambda provider: {"provider": provider}
                ),
                coach_history=SimpleNamespace(history=list),
                redactor=redactor,
                provider_freshness=freshness,
                profile=profile,
                garmin_sync_state=SimpleNamespace(core_error_entries=list),
                external_calendar_sync=SimpleNamespace(running=lambda: False),
                external_calendar_reader=calendar_reader,
                morning_checkin=SimpleNamespace(state=lambda: {"status": "waiting"}),
                workout_library_sync_state=SimpleNamespace(summary=dict),
                canonical_coverage=coverage,
                recent_logs=RecentLogEntriesService(log_path, redactor, lambda: STAMP),
                diagnostic_capture=capture,
                activity_rows=canonical_rows,
                observations=canonical_rows,
            )
        )
        report = service.report()
        self.assertGreater(len(report["logs"]), 0, "the log projection is not empty")
        self.assertEqual(scan(json.dumps(report, default=str).encode()), [])
        downloaded = RecentLogEntriesService(
            log_path, redactor, lambda: STAMP
        ).download()
        self.assertEqual(scan(downloaded), [])


@unittest.skipIf(sqlcipher3 is None, "SQLCipher is not installed here")
class EncryptedBackupSecretTests(unittest.TestCase):
    """Unrun without SQLCipher (Windows): run through tests/run_sqlcipher_tests.ps1."""

    def test_the_encrypted_backup_exposes_no_secret_or_plain_header(self):
        password = SENTINELS["app_password"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "athlete.db"
            manager = DatabaseManager(
                database_path,
                sqlcipher3,
                password=password,
                configure=configure_cipher,
                row_factory=row_factory,
                timeout=0.1,
            )
            try:
                with manager.unit_of_work() as db:
                    initialize_schema(db)
                    kv = KeyValueRepository(lambda: STAMP)
                    kv.set(
                        db,
                        PROVIDER_CREDENTIALS_KEY,
                        json.dumps({PERSONAL_KEY_FIELD: SENTINELS["personal_api_key"]}),
                    )
                    kv.set(
                        db,
                        GARMIN_TOKENS_KEY,
                        json.dumps({"di_token": SENTINELS["garmin_token"]}),
                    )
                backup = DatabaseBackupService(
                    manager,
                    Mock(),
                    DatabaseBackupConfig(
                        database_path=database_path,
                        data_dir=root,
                        maximum_bytes=50_000_000,
                        minimum_free_bytes=0,
                        time_limit_seconds=30,
                        monotonic=lambda: 0.0,
                        disk_usage=lambda _path: SimpleNamespace(free=10**12),
                    ),
                    Mock(),
                ).read_bytes()
            finally:
                manager.close()
        self.assertEqual(scan(backup), [])
        self.assertNotIn(password.encode(), backup)
        self.assertFalse(backup.startswith(b"SQLite format 3"))


if __name__ == "__main__":
    unittest.main()
