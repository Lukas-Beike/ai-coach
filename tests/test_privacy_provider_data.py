"""Privacy export format v2 and deletion of canonical provider data (schema v6)."""

import json
import logging
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.backup.export import (
    PRIVACY_EXPORT_FORMAT_VERSION,
    PRIVACY_EXPORT_JSONL_FILES,
    PrivacyArchiveExportConfig,
    PrivacyArchiveExportService,
)
from backend.db.schema import initialize_schema
from backend.observability import REDACTED_VALUE, sanitized_provider_payload
from backend.privacy import (
    PRIVACY_DELETE_SCOPE,
    PrivacyDeleteDependencies,
    PrivacyDeleteService,
)

STAMP = "2026-10-01T08:00:00+00:00"
PROVIDER = "synthetic-provider"
PROVIDER_FILES = (
    "provider_records.jsonl",
    "activity_sessions.jsonl",
    "activity_records.jsonl",
    "observations.jsonl",
)
SECRET_PAYLOAD = {
    "name": "Synthetic ride",
    "access_token": "synthetic-secret-value",
    "nested": {
        "apiKey": "synthetic-key",
        "laps": [{"Cookie": "synthetic", "split": 1}],
    },
}
SIGNED_URL = "https://files.invalid/ride.fit?X-Amz-Signature=synthetic-signature"
SECRET_DETAILS = {
    "download": SIGNED_URL,
    "client_secret": "synthetic-client-secret",
    "splits": [{"index": 1}],
}


class _Manager:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def reader(self):
        yield self.db

    @contextmanager
    def unit_of_work(self):
        yield self.db
        self.db.commit()


class _KeyValues:
    def __init__(self):
        self.values = {}

    def get(self, _db, key):
        return self.values.get(key)

    def set(self, _db, key, value):
        self.values[key] = value


class _Profile:
    def get_from_db(self, _db):
        return {}


class _Competitions:
    def list(self, db=None):
        return []


class _Adaptive:
    def latest_preview(self, db=None):
        return None

    def status(self, db=None):
        return {}


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Gate:
    @contextmanager
    def restore(self):
        yield


class _PlanningRevision:
    def mark_reset_pending(self):
        return None


class _OpenAI:
    def delete_conversation(self, _conversation_id):
        raise AssertionError("no conversation was stored")


def seed_provider_rows(db):
    db.execute(
        "INSERT INTO provider_records(provider, record_kind, source_record_id, payload, "
        "payload_hash, fetched_at, created_at, updated_at) "
        "VALUES (?, 'activity', 'rec-1', ?, ?, ?, ?, ?)",
        (PROVIDER, json.dumps(SECRET_PAYLOAD), "a" * 64, STAMP, STAMP, STAMP),
    )
    db.execute(
        "INSERT INTO activity_sessions(activity_id, primary_provider, "
        "primary_provider_activity_id, started_at, created_at, updated_at) "
        "VALUES ('act_1', ?, 'act-1', ?, ?, ?)",
        (PROVIDER, STAMP, STAMP, STAMP),
    )
    db.execute(
        "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
        "mapper_version, source_kind, recorded_by, sport, environment, started_at, "
        "duration_s, distance_m, load, load_model, avg_hr, avg_power, name, details, "
        "fetched_at, created_at, updated_at) "
        "VALUES (?, 'act-1', 'act_1', 1, 'provider_reported', 'manual', 'ride', "
        "'outdoor', ?, 3600.0, 30000.0, 55.0, 'unknown', 140.0, 210.0, "
        "'Synthetic ride', ?, ?, ?, ?)",
        (PROVIDER, STAMP, json.dumps(SECRET_DETAILS), STAMP, STAMP, STAMP),
    )
    db.execute(
        "INSERT INTO observations(natural_key, metric, value, unit, source_kind, "
        "recorded_by, provider, observed_on, mapper_version, created_at, updated_at) "
        "VALUES ('weight-1', 'weight', 72.5, 'kg', 'provider_reported', 'manual', ?, "
        "'2026-10-01', 1, ?, ?)",
        (PROVIDER, STAMP, STAMP),
    )
    db.commit()


def seed_remote_link_rows(db):
    for kind, local_id, remote_id in (
        ("competition", "1", "event-1"),
        ("library_workout", "lib-1", "event-2"),
        ("planned_unit", "u-1", "event-3"),
    ):
        db.execute(
            "INSERT INTO remote_links(entity_kind, local_id, provider, remote_id, "
            "sync_state) VALUES (?, ?, 'intervals', ?, 'synced')",
            (kind, local_id, remote_id),
        )
    db.execute(
        "INSERT INTO competition_sync_tombstones(intervals_event_id, external_id, "
        "created_at, provider) VALUES ('event-9', 'external-9', ?, 'intervals')",
        (STAMP,),
    )
    db.commit()


class ProviderDataFixture(unittest.TestCase):
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


class PrivacyExportProviderTests(ProviderDataFixture):
    def export(self):
        config = PrivacyArchiveExportConfig(
            data_dir=self.root,
            database_path=self.database_path,
            today=lambda: date(2026, 10, 1),
            utc_now=lambda: STAMP,
            maximum_bytes=10_000_000,
            minimum_free_bytes=0,
            time_limit_seconds=60,
            monotonic=lambda: 0.0,
            disk_usage=lambda _path: SimpleNamespace(free=10**12),
        )
        service = PrivacyArchiveExportService(
            _Manager(self.db),
            _KeyValues(),
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
        return zipfile.ZipFile(path)

    @staticmethod
    def lines(archive, name):
        return [json.loads(line) for line in archive.read(name).splitlines() if line]

    def test_format_version_five_lists_the_provider_and_remote_link_files(self):
        self.assertEqual(PRIVACY_EXPORT_FORMAT_VERSION, 5)
        expected = {*PROVIDER_FILES, "remote_links.jsonl"}
        self.assertLessEqual(expected, PRIVACY_EXPORT_JSONL_FILES)
        with self.export() as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["format_version"], 5)
            self.assertLessEqual(expected, set(manifest["jsonl_files"]))
            self.assertLessEqual(expected, set(archive.namelist()))

    def test_remote_links_and_tombstone_providers_are_exported(self):
        seed_remote_link_rows(self.db)
        with self.export() as archive:
            links = self.lines(archive, "remote_links.jsonl")
            tombstones = self.lines(archive, "competition_sync_tombstones.jsonl")
        self.assertEqual(
            [(row["entity_kind"], row["local_id"]) for row in links],
            [
                ("competition", "1"),
                ("library_workout", "lib-1"),
                ("planned_unit", "u-1"),
            ],
        )
        self.assertEqual(links[0]["provider"], "intervals")
        self.assertEqual(links[0]["remote_id"], "event-1")
        self.assertEqual(links[0]["sync_state"], "synced")
        self.assertEqual(tombstones[0]["provider"], "intervals")

    def test_empty_remote_links_export_an_empty_file(self):
        with self.export() as archive:
            self.assertEqual(archive.read("remote_links.jsonl"), b"")

    def test_provider_rows_are_exported_with_sanitized_payloads(self):
        seed_provider_rows(self.db)
        with self.export() as archive:
            records = self.lines(archive, "provider_records.jsonl")
            raw = archive.read("provider_records.jsonl")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source_record_id"], "rec-1")
            self.assertEqual(records[0]["payload_hash"], "a" * 64)
            self.assertEqual(
                records[0]["payload"],
                {"name": "Synthetic ride", "nested": {"laps": [{"split": 1}]}},
            )
            for leaked in (b"synthetic-secret-value", b"synthetic-key", b"Cookie"):
                self.assertNotIn(leaked, raw)

            session = self.lines(archive, "activity_sessions.jsonl")
            self.assertEqual(session[0]["activity_id"], "act_1")
            self.assertEqual(session[0]["primary_provider_activity_id"], "act-1")

            activity = self.lines(archive, "activity_records.jsonl")
            self.assertEqual(activity[0]["activity_id"], "act_1")
            self.assertEqual(activity[0]["load"], 55.0)
            self.assertEqual(activity[0]["load_model"], "unknown")
            for typed in (
                "moving_duration_s",
                "elevation_gain_m",
                "intensity_pct",
                "max_hr",
                "normalized_power",
                "avg_cadence",
                "energy_kj",
            ):
                with self.subTest(column=typed):
                    self.assertIn(typed, activity[0])
                    self.assertIsNone(activity[0][typed])
            self.assertNotIn("payload", activity[0])
            self.assertEqual(activity[0]["details"]["download"], REDACTED_VALUE)
            self.assertNotIn("client_secret", activity[0]["details"])
            activity_raw = archive.read("activity_records.jsonl")
            for leaked in (b"X-Amz-Signature", b"synthetic-client-secret"):
                self.assertNotIn(leaked, activity_raw)

            observation = self.lines(archive, "observations.jsonl")
            self.assertEqual(observation[0]["natural_key"], "weight-1")
            self.assertEqual(observation[0]["metric"], "weight")
            self.assertEqual(observation[0]["unit"], "kg")
            self.assertEqual(observation[0]["value"], 72.5)
            self.assertEqual(observation[0]["mapper_version"], 1)

    def test_empty_provider_tables_export_empty_files(self):
        with self.export() as archive:
            for name in PROVIDER_FILES:
                with self.subTest(name=name):
                    self.assertEqual(archive.read(name), b"")

    def test_feedback_archive_includes_the_feedback_provider(self):
        self.db.execute(
            "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, "
            "notes, session_rpe, deviation_reason, created_at, updated_at, provider) "
            "VALUES ('act_1', 'Synthetic ride', '2026-10-01', 'felt good', 5, '', ?, ?, "
            "'intervals')",
            (STAMP, STAMP),
        )
        self.db.commit()
        with self.export() as archive:
            rows = self.lines(archive, "activity_feedback.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            set(rows[0]),
            {
                "activity_id",
                "activity_name",
                "activity_date",
                "notes",
                "session_rpe",
                "deviation_reason",
                "created_at",
                "updated_at",
                "provider",
            },
        )
        self.assertEqual(rows[0]["notes"], "felt good")
        self.assertEqual(rows[0]["provider"], "intervals")


class SanitizedProviderPayloadTests(unittest.TestCase):
    def test_credential_like_keys_are_removed_at_every_depth(self):
        value = {
            "a": [1, {"refresh_token": "x", "b": None}],
            "Secret": 1,
            "Authorization": "Bearer x",
            "password_hint": "x",
            "credentials": {},
            "ok": "y",
        }
        self.assertEqual(
            sanitized_provider_payload(value),
            {"a": [1, {"b": None}], "ok": "y"},
        )

    def test_signed_download_urls_are_redacted(self):
        for url in (
            "https://files.invalid/a?X-Amz-Signature=abc",
            "https://files.invalid/a?signature=abc",
            "https://files.invalid/a?token=abc",
        ):
            with self.subTest(url=url):
                self.assertEqual(sanitized_provider_payload([url]), [REDACTED_VALUE])

    def test_plain_text_and_unsigned_urls_pass_through(self):
        self.assertEqual(
            sanitized_provider_payload("token=not-a-url"), "token=not-a-url"
        )
        self.assertEqual(
            sanitized_provider_payload("https://files.invalid/a.fit"),
            "https://files.invalid/a.fit",
        )

    def test_scalars_pass_through_unchanged(self):
        self.assertEqual(sanitized_provider_payload("text"), "text")
        self.assertEqual(sanitized_provider_payload(3), 3)
        self.assertIsNone(sanitized_provider_payload(None))


class PrivacyDeleteProviderTests(ProviderDataFixture):
    def service(self):
        database = _Manager(self.db)
        return PrivacyDeleteService(
            PrivacyDeleteDependencies(
                database_manager=database,
                database_lock=_Lock(),
                key_value_repository=_KeyValues(),
                maintenance_gate=_Gate(),
                planning_revision_service=_PlanningRevision(),
                openai_client=_OpenAI(),
                logger=logging.getLogger("test.privacy.provider"),
            )
        )

    def test_provider_data_is_a_scope_category_with_children_first(self):
        scope = {category: tables for category, _label, tables in PRIVACY_DELETE_SCOPE}
        self.assertEqual(
            set(scope["provider_data"]),
            {
                "observations",
                "activity_records",
                "activity_sessions",
                "provider_records",
            },
        )
        self.assertLess(
            scope["provider_data"].index("activity_records"),
            scope["provider_data"].index("activity_sessions"),
        )

    def test_preview_counts_provider_rows(self):
        seed_provider_rows(self.db)
        preview = self.service().preview()
        counts = {item["id"]: item["records"] for item in preview["categories"]}
        self.assertEqual(counts["provider_data"], 4)

    def test_delete_removes_provider_rows_without_foreign_key_errors(self):
        seed_provider_rows(self.db)
        result = self.service().delete("LOKALE DATEN LÖSCHEN")
        self.assertEqual(result["deleted_categories"]["provider_data"], 4)
        for table in (
            "observations",
            "activity_records",
            "activity_sessions",
            "provider_records",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    0,
                )

    def test_remote_links_are_listed_with_the_entities_they_belong_to(self):
        scope = {category: tables for category, _label, tables in PRIVACY_DELETE_SCOPE}
        self.assertIn("remote_links", scope["library"])
        self.assertIn("remote_links", scope["competitions"])

    def test_preview_counts_remote_links_by_owning_group(self):
        seed_remote_link_rows(self.db)
        preview = self.service().preview()
        counts = {item["id"]: item["records"] for item in preview["categories"]}
        # Two library links, one competition link and one tombstone.
        self.assertEqual(counts["library"], 2)
        self.assertEqual(counts["competitions"], 2)

    def test_delete_removes_every_remote_link(self):
        seed_remote_link_rows(self.db)
        result = self.service().delete("LOKALE DATEN LÖSCHEN")
        self.assertEqual(result["deleted_categories"]["library"], 2)
        self.assertEqual(result["deleted_categories"]["competitions"], 2)
        for table in ("remote_links", "competition_sync_tombstones"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )


if __name__ == "__main__":
    unittest.main()
