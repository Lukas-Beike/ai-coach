import threading

"""Privacy export format v2 and deletion of canonical provider data (schema v6)."""

import json
import logging
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import contextmanager, nullcontext
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from canonical_domain_support import (
    GEAR_SOURCE,
    SETTINGS_SOURCE,
    WATCH_CONTEXT,
    WELLNESS_SOURCE,
    gear_item,
    gear_link,
    sleep_period,
    status,
    zone_configuration,
)
from canonical_domain_support import provenance as domain_provenance

from backend.backup.export import (
    PRIVACY_EXPORT_FORMAT_VERSION,
    PRIVACY_EXPORT_JSONL_FILES,
    PrivacyArchiveExportConfig,
    PrivacyArchiveExportService,
)
from backend.backup.recovery_copies import RecoveryCopies
from backend.canonical.activity_detail import (
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneBucket,
    ZoneDistribution,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    RemoteEntityKind,
    SourceKind,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db.activity_detail_store import replace_detail_set, save_analysis
from backend.db.canonical_domain_store import (
    replace_categorical_observations,
    replace_gear_activity_links,
    replace_gear_items,
    replace_sleep_periods,
    replace_zone_configurations,
)
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.diagnostics.logs import RecentLogEntriesService
from backend.errors import AppError
from backend.observability import REDACTED_VALUE, sanitized_provider_payload
from backend.privacy import (
    _REMOTE_LINK_KINDS_BY_CATEGORY,
    PRIVACY_DELETE_SCOPE,
    PrivacyDeleteDependencies,
    PrivacyDeleteService,
)
from backend.provider_credentials import WAHOO_TOKENS_KEY
from backend.providers.wahoo_oauth import WahooOAuthClient
from backend.sync.wahoo_connection import WahooConnectionService
from tests.test_wahoo_connection import make_config

STAMP = "2026-10-01T08:00:00+00:00"
PROVIDER = "synthetic-provider"
PROVIDER_FILES = (
    "provider_records.jsonl",
    "activity_sessions.jsonl",
    "activity_records.jsonl",
    "observations.jsonl",
)
DETAIL_FILES = (
    "activity_detail_sets.jsonl",
    "activity_stream_channels.jsonl",
    "activity_laps.jsonl",
    "activity_zone_times.jsonl",
    "activity_strength_sets.jsonl",
    "activity_detail_analysis.jsonl",
)
DETAIL_TABLES = tuple(name.removesuffix(".jsonl") for name in DETAIL_FILES)
DOMAIN_FILES = (
    "sleep_periods.jsonl",
    "zone_configurations.jsonl",
    "categorical_observations.jsonl",
    "gear_items.jsonl",
    "gear_activity_links.jsonl",
    "power_curve_points.jsonl",
    "power_curve_fetches.jsonl",
)
DOMAIN_TABLES = tuple(name.removesuffix(".jsonl") for name in DOMAIN_FILES)
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

    read_snapshot = reader

    @contextmanager
    def unit_of_work(self):
        yield self.db
        self.db.commit()

    def reclaim_space(self):
        return True


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
    def restore(self, before_wait=None):
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


def seed_detail_rows(db):
    """Add an Intervals.icu record with one set of every detail kind to act_1."""
    db.execute(
        "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
        "mapper_version, source_kind, recorded_by, sport, environment, started_at, "
        "load_model, fetched_at, created_at, updated_at) "
        "VALUES ('intervals', 'i1', 'act_1', 1, 'provider_reported', 'garmin', "
        "'ride', 'outdoor', ?, 'unknown', ?, ?, ?)",
        (STAMP, STAMP, STAMP, STAMP),
    )
    provenance = Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=RecordingOrigin.GARMIN,
        retrieved_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
        label=None,
    )
    header = {
        "provider_activity_id": "i1",
        "provenance": provenance,
        "origin": ActivityDetailOrigin.FETCH,
    }
    details = (
        ActivityStreamSet(
            **header,
            resolution=StreamResolution.FULL,
            channels={
                StreamChannel.TIME_S: (0.0, 1.0),
                StreamChannel.POWER_W: (200.0, None),
            },
        ),
        ActivityLapSet(
            **header,
            lap_source=LapSource.DEVICE_LAPS,
            laps=(ActivityLap(0, LapKind.LAP, 0.0, 1.0, avg_power=200.0),),
        ),
        ZoneDistribution(
            **header,
            metric=ZoneMetric.POWER,
            boundary_source=ZoneBoundarySource.UNKNOWN,
            buckets=(ZoneBucket(1, 1.0),),
        ),
    )
    for detail in details:
        replace_detail_set(db, detail, mapper_version=1, summary_sha256=None, now=STAMP)
    save_analysis(
        db,
        "act_1",
        analysis_version=1,
        input_sha256="b" * 64,
        payload={"score": 0.5},
        now=STAMP,
    )
    db.commit()


def seed_remote_link_rows(db):
    for kind, local_id, remote_id in (
        ("competition", "1", "event-1"),
        ("library_workout", "lib-1", "event-2"),
        ("planned_unit", "u-1", "event-3"),
        ("observation", "obs-1", "metric-1"),
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


def seed_domain_rows(db):
    """Add one row to every v15 domain table and retire one gear link."""
    garmin = {"provider": ProviderId.GARMIN, "mapper_version": 1, "now": STAMP}
    intervals = {**garmin, "provider": ProviderId.INTERVALS}
    replace_sleep_periods(
        db,
        source_record_id=WELLNESS_SOURCE,
        periods=[sleep_period(provenance=domain_provenance(context=WATCH_CONTEXT))],
        **garmin,
    )
    replace_categorical_observations(
        db, source_record_id=WELLNESS_SOURCE, observations=[status()], **garmin
    )
    replace_zone_configurations(
        db,
        source_record_id=SETTINGS_SOURCE,
        configurations=[zone_configuration()],
        **intervals,
    )
    replace_gear_items(
        db, source_record_id=GEAR_SOURCE, items=[gear_item()], **intervals
    )
    for links in ([gear_link("i1001"), gear_link("i1002")], [gear_link("i1002")]):
        replace_gear_activity_links(
            db, source_record_id=GEAR_SOURCE, links=links, **intervals
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
    def setUp(self):
        super().setUp()
        self.key_values_seed: dict[str, str] = {}

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
        self.key_values = _KeyValues()
        self.key_values.values.update(self.key_values_seed)
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
        return zipfile.ZipFile(path)

    @staticmethod
    def lines(archive, name):
        return [json.loads(line) for line in archive.read(name).splitlines() if line]

    def test_format_version_lists_provider_detail_domain_and_link_files(self):
        self.assertEqual(PRIVACY_EXPORT_FORMAT_VERSION, 17)
        expected = {
            *PROVIDER_FILES,
            *DETAIL_FILES,
            *DOMAIN_FILES,
            "remote_links.jsonl",
        }
        self.assertLessEqual(expected, PRIVACY_EXPORT_JSONL_FILES)
        with self.export() as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["format_version"], 17)
            self.assertLessEqual(expected, set(manifest["jsonl_files"]))
            self.assertLessEqual(expected, set(archive.namelist()))

    def test_stored_non_secret_provider_fields_are_exported_without_secrets(self):
        self.key_values_seed = {
            "provider_credentials": json.dumps(
                {
                    "garmin_personal_api_key": "secret-personal-key",
                    "garmin_personal_api_key_expires": "2027-01-31",
                    "intervals_api_key": "secret-intervals-key",
                    "intervals_athlete_id": "i12345",
                    "wahoo_client_id": "wahoo-client-1",
                    "wahoo_client_secret": "secret-wahoo-client",
                    "openai_base_url": "https://llm.example.invalid/v1",
                    "openai_api_key": "secret-openai-key",
                    "garmin_email": "athlete@example.invalid",
                }
            )
        }
        with self.export() as archive:
            raw = archive.read("provider_settings.json").decode("utf-8")
            everything = b"".join(archive.read(name) for name in archive.namelist())
        self.assertEqual(
            json.loads(raw),
            {
                "garmin_personal_api_key_expires": "2027-01-31",
                "intervals_athlete_id": "i12345",
                "openai_base_url": "https://llm.example.invalid/v1",
                "wahoo_client_id": "wahoo-client-1",
            },
        )
        for secret in (b"secret-", b"athlete@example.invalid"):
            self.assertNotIn(secret, everything)

    def test_provider_settings_are_empty_without_stored_credentials(self):
        with self.export() as archive:
            self.assertEqual(json.loads(archive.read("provider_settings.json")), {})

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
                ("observation", "obs-1"),
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

    def test_activity_detail_rows_are_exported_with_decoded_streams(self):
        seed_provider_rows(self.db)
        seed_detail_rows(self.db)
        with self.export() as archive:
            sets = self.lines(archive, "activity_detail_sets.jsonl")
            channels = self.lines(archive, "activity_stream_channels.jsonl")
            laps = self.lines(archive, "activity_laps.jsonl")
            zones = self.lines(archive, "activity_zone_times.jsonl")
            analysis = self.lines(archive, "activity_detail_analysis.jsonl")
        self.assertEqual(
            [row["detail_kind"] for row in sets], ["laps", "power_zones", "streams"]
        )
        self.assertEqual(
            {row["channel"]: row["values"] for row in channels},
            {"power_w": [200.0, None], "time_s": [0.0, 1.0]},
        )
        self.assertNotIn("data", channels[0])
        self.assertEqual(laps[0]["avg_power"], 200.0)
        self.assertEqual(zones[0]["seconds"], 1.0)
        self.assertEqual(analysis[0]["payload"], {"score": 0.5})

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

    def test_domain_rows_are_exported_with_decoded_details_and_limits(self):
        seed_domain_rows(self.db)
        with self.export() as archive:
            sleep = self.lines(archive, "sleep_periods.jsonl")
            zones = self.lines(archive, "zone_configurations.jsonl")
            statuses = self.lines(archive, "categorical_observations.jsonl")
            gear = self.lines(archive, "gear_items.jsonl")
            links = self.lines(archive, "gear_activity_links.jsonl")
        self.assertEqual(sleep[0]["started_at"], "2026-10-19T22:30:00+00:00")
        self.assertEqual(sleep[0]["details"], {"context": WATCH_CONTEXT.as_details()})
        self.assertEqual(zones[0]["limits"], [130.0, 145.0, 160.0, 172.0, 192.0])
        self.assertIsNone(zones[0]["percent_limits"])
        self.assertEqual(zones[0]["details"], {})
        self.assertEqual(
            (statuses[0]["domain"], statuses[0]["code"]),
            ("training_status", "PRODUCTIVE"),
        )
        self.assertEqual(gear[0]["total_activities"], 321)
        self.assertEqual(
            [(row["provider_activity_id"], row["state"]) for row in links],
            [("i1001", "retired"), ("i1002", "active")],
        )

    def test_merge_retention_and_feedback_sessions_are_exported(self):
        seed_provider_rows(self.db)
        self.db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, state, merged_into_retained, started_at, "
            "created_at, updated_at) VALUES ('act_2', ?, 'act-2', 'deleted', 'act_1', "
            "?, ?, ?)",
            (PROVIDER, STAMP, STAMP, STAMP),
        )
        self.db.execute(
            "INSERT INTO activity_feedback(activity_id, activity_name, activity_date, "
            "notes, session_rpe, deviation_reason, created_at, updated_at, provider, "
            "session_id) VALUES ('act-2', 'Synthetic ride', '2026-10-01', '', 5, '', "
            "?, ?, ?, 'act_2')",
            (STAMP, STAMP, PROVIDER),
        )
        self.db.commit()
        with self.export() as archive:
            sessions = self.lines(archive, "activity_sessions.jsonl")
            feedback = self.lines(archive, "activity_feedback.jsonl")
        self.assertEqual(
            {row["activity_id"]: row["merged_into_retained"] for row in sessions},
            {"act_1": None, "act_2": "act_1"},
        )
        self.assertEqual(feedback[0]["session_id"], "act_2")

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
                "session_id",
                "session_rpe_rated_at",
                "purpose",
            },
        )
        self.assertEqual(rows[0]["notes"], "felt good")
        self.assertIsNone(rows[0]["purpose"])
        self.assertEqual(rows[0]["provider"], "intervals")
        self.assertIsNone(rows[0]["session_id"])
        self.assertIsNone(rows[0]["session_rpe_rated_at"])


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
    def service(self, **extra):
        database = _Manager(self.db)
        self.key_values = _KeyValues()
        return PrivacyDeleteService(
            PrivacyDeleteDependencies(
                profile_mutation_coordinator=threading.RLock(),
                database_manager=database,
                database_lock=_Lock(),
                key_value_repository=self.key_values,
                maintenance_gate=_Gate(),
                planning_revision_service=_PlanningRevision(),
                openai_client=_OpenAI(),
                logger=logging.getLogger("test.privacy.provider"),
                diagnostics_suspended=nullcontext,
                **extra,
            )
        )

    def test_delete_cancels_a_pending_garmin_login(self):
        cancelled: list[bool] = []
        self.service(cancel_garmin_login=lambda: cancelled.append(True)).delete(
            "LOKALE DATEN LÖSCHEN"
        )
        self.assertEqual(cancelled, [True])

    def test_delete_clears_every_garmin_capability_pause(self):
        for key, value in (
            ("garmin_capability_activities", '{"count":3}'),
            ("garmin_capability_wellness_backfill_sleep", '{"count":3}'),
            ("gps_tracks_enabled", "0"),
        ):
            self.db.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, "2026-11-09T08:00:00+00:00"),
            )
        service = self.service()
        service.delete("LOKALE DATEN LÖSCHEN")
        remaining = self.db.execute(
            "SELECT key FROM kv WHERE instr(key, 'capability') > 0"
        ).fetchall()
        self.assertEqual(remaining, [])
        # A switched-off GPS setting survives the erasure (#2137, K-002) ...
        self.assertEqual(self.key_values.values.get("gps_tracks_enabled"), "0")
        # ... and one that was on stays absent, which means on.
        self.key_values.values.clear()
        service.delete("LOKALE DATEN LÖSCHEN")
        self.assertNotIn("gps_tracks_enabled", self.key_values.values)

    def connected_wahoo(self, request):
        """A real Wahoo connection service over the fixture database, already connected."""
        config = make_config()
        service = WahooConnectionService(
            config=lambda: config,
            oauth=lambda: WahooOAuthClient(lambda: config, request),
            database_manager=lambda: _Manager(self.db),
            database_lock=lambda: MagicMock(),
            key_values=KeyValueRepository(lambda: "2026-11-09T08:00:00+00:00"),
            utc_now=lambda: "2026-11-09T08:00:00+00:00",
            token_factory=lambda: "state-1",
        )
        service.start_authorization()
        request.return_value = {
            "access_token": "access-synthetic",
            "refresh_token": "refresh-synthetic",
            "expires_in": 3600,
        }
        self.assertEqual(
            service.complete_authorization("code-1", "state-1"), "connected"
        )
        request.reset_mock()
        return service

    def wahoo_tokens_stored(self):
        return (
            self.db.execute(
                "SELECT 1 FROM kv WHERE key = ?", (WAHOO_TOKENS_KEY,)
            ).fetchone()
            is not None
        )

    def test_delete_revokes_the_wahoo_grant_before_wiping_the_tokens(self):
        request = Mock()
        wahoo = self.connected_wahoo(request)
        self.assertTrue(self.wahoo_tokens_stored())
        result = self.service(disconnect_wahoo=wahoo.disconnect).delete(
            "LOKALE DATEN LÖSCHEN"
        )
        self.assertEqual(request.call_args.args[0], "DELETE")
        self.assertTrue(result["wahoo_revoke_attempted"])
        self.assertTrue(result["wahoo_revoked"])
        self.assertFalse(self.wahoo_tokens_stored())
        self.assertFalse(wahoo.status()["connected"])
        self.assertTrue(
            any("Wahoo" in line for line in result["remote_untouched"]),
        )
        self.assertNotIn("synthetic", json.dumps(result))

    def test_a_failed_wahoo_revoke_is_reported_and_the_purge_completes(self):
        request = Mock()
        wahoo = self.connected_wahoo(request)
        request.side_effect = AppError(502, "down", upstream_status=500)
        result = self.service(disconnect_wahoo=wahoo.disconnect).delete(
            "LOKALE DATEN LÖSCHEN"
        )
        self.assertTrue(result["local_data_deleted"])
        self.assertTrue(result["wahoo_revoke_attempted"])
        self.assertFalse(result["wahoo_revoked"])
        self.assertFalse(self.wahoo_tokens_stored())

    def test_a_crashing_wahoo_disconnect_does_not_block_the_purge(self):
        def explode():
            raise RuntimeError("synthetic")

        result = self.service(disconnect_wahoo=explode).delete("LOKALE DATEN LÖSCHEN")
        self.assertTrue(result["local_data_deleted"])
        self.assertTrue(result["wahoo_revoke_attempted"])
        self.assertFalse(result["wahoo_revoked"])

    def test_a_purge_without_a_wahoo_grant_attempts_no_revoke(self):
        request = Mock()
        wahoo = self.connected_wahoo(request)
        wahoo.disconnect()
        request.reset_mock()
        result = self.service(disconnect_wahoo=wahoo.disconnect).delete(
            "LOKALE DATEN LÖSCHEN"
        )
        request.assert_not_called()
        self.assertFalse(result["wahoo_revoke_attempted"])
        self.assertFalse(result["wahoo_revoked"])

    def seed_recovery_files(self):
        stamp = "20261101120000-" + "a" * 32
        names = (
            f"{self.database_path.name}.pre-restore-{stamp}",
            f"{self.database_path.name}.pre-intervals-purge-v1-{stamp}",
            "intervals-purge-v1.done",
        )
        for name in names:
            (self.root / name).write_bytes(b"synthetic")
        # The server log files beside the database (#2137, G-209).
        for name in ("intervals-coach.log", "intervals-coach.log.1"):
            (self.root / name).write_text('{"message":"synthetic"}\n')
        return names

    def log_files(self):
        return RecentLogEntriesService(
            self.root / "intervals-coach.log", Mock(), lambda: "2026-11-11"
        )

    def test_the_preview_counts_recovery_copies_and_the_delete_erases_them(self):
        names = self.seed_recovery_files()
        keep = self.root / "unrelated.txt"
        keep.write_text("keep")
        copies = RecoveryCopies(self.root, self.database_path.name)
        service = self.service(recovery_copies=copies, log_files=self.log_files())
        counts = {
            item["id"]: item["records"] for item in service.preview()["categories"]
        }
        self.assertEqual((counts["recovery_copies"], counts["server_logs"]), (3, 2))
        result = service.delete("LOKALE DATEN LÖSCHEN")
        self.assertEqual(result["deleted_categories"]["recovery_copies"], 3)
        self.assertEqual(result["deleted_categories"]["server_logs"], 2)
        self.assertEqual(result["recovery_copies_failed"], 0)
        self.assertFalse(result["log_files_failed"])
        for name in names:
            self.assertFalse((self.root / name).exists())
        self.assertFalse((self.root / "intervals-coach.log.1").exists())
        self.assertEqual((self.root / "intervals-coach.log").read_text(), "")
        self.assertTrue(keep.exists())
        self.assertTrue(self.database_path.exists())

    def test_a_recovery_copy_that_cannot_be_removed_is_reported_not_raised(self):
        self.seed_recovery_files()
        service = self.service(
            recovery_copies=RecoveryCopies(self.root, self.database_path.name),
            log_files=self.log_files(),
        )
        with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
            result = service.delete("LOKALE DATEN LÖSCHEN")
        self.assertEqual(result["recovery_copies_failed"], 3)
        self.assertTrue(result["log_files_failed"])
        self.assertEqual(result["deleted_categories"]["recovery_copies"], 0)
        self.assertTrue(result["local_data_deleted"])

    def test_provider_data_is_a_scope_category_with_children_first(self):
        scope = {category: tables for category, _label, tables in PRIVACY_DELETE_SCOPE}
        self.assertEqual(
            set(scope["provider_data"]),
            {
                "observations",
                *DOMAIN_TABLES,
                *DETAIL_TABLES,
                "activity_records",
                "activity_sessions",
                "provider_records",
                "remote_links",
            },
        )
        order = scope["provider_data"].index
        for child, parent in (
            ("activity_stream_channels", "activity_detail_sets"),
            ("activity_laps", "activity_detail_sets"),
            ("activity_zone_times", "activity_detail_sets"),
            ("activity_strength_sets", "activity_detail_sets"),
            ("activity_detail_sets", "activity_records"),
            ("activity_detail_analysis", "activity_sessions"),
            ("activity_records", "activity_sessions"),
        ):
            with self.subTest(child=child):
                self.assertLess(order(child), order(parent))

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

    def test_delete_removes_activity_detail_rows_before_their_parents(self):
        seed_provider_rows(self.db)
        seed_detail_rows(self.db)
        self.service().delete("LOKALE DATEN LÖSCHEN")
        for table in (*DETAIL_TABLES, "activity_records", "activity_sessions"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    0,
                )

    def test_remote_links_are_listed_with_the_entities_they_belong_to(self):
        scope = {category: tables for category, _label, tables in PRIVACY_DELETE_SCOPE}
        self.assertIn("remote_links", scope["library"])
        self.assertIn("remote_links", scope["competitions"])
        self.assertIn("remote_links", scope["provider_data"])

    def test_preview_counts_remote_links_by_owning_group(self):
        seed_remote_link_rows(self.db)
        preview = self.service().preview()
        counts = {item["id"]: item["records"] for item in preview["categories"]}
        # Two library links, one competition link and one tombstone.
        self.assertEqual(counts["library"], 2)
        self.assertEqual(counts["competitions"], 2)
        # The metric-export link counts as provider data (no other rows seeded).
        self.assertEqual(counts["provider_data"], 1)

    def test_the_privacy_preview_counts_every_remote_link_kind_it_deletes(self):
        seed_remote_link_rows(self.db)
        owners = [
            kind for kinds in _REMOTE_LINK_KINDS_BY_CATEGORY.values() for kind in kinds
        ]
        self.assertCountEqual(owners, list(RemoteEntityKind))
        counted = sum(
            PrivacyDeleteService._table_count(self.db, category, "remote_links")
            for category in _REMOTE_LINK_KINDS_BY_CATEGORY
        )
        total = self.db.execute("SELECT COUNT(*) FROM remote_links").fetchone()[0]
        self.assertEqual(counted, total)
        self.assertEqual(total, 4)

    def test_delete_removes_every_remote_link(self):
        seed_remote_link_rows(self.db)
        result = self.service().delete("LOKALE DATEN LÖSCHEN")
        self.assertEqual(result["deleted_categories"]["library"], 2)
        self.assertEqual(result["deleted_categories"]["competitions"], 2)
        self.assertEqual(result["deleted_categories"]["provider_data"], 1)
        for table in ("remote_links", "competition_sync_tombstones"):
            with self.subTest(table=table):
                self.assertEqual(
                    self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )


if __name__ == "__main__":
    unittest.main()
