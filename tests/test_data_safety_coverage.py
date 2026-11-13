"""Backup, restore, privacy export and privacy delete cover every stored data kind.

The guards fail when a table, an export column or a key/value family is added
without a decision: each one is either covered or listed below as excluded, with
its reason. They run on plain SQLite with the real schema, export and delete
services, so they need no SQLCipher. Release 1.13.40 to schema v22 added the data
kinds seeded by ``DataKindFixture``.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from contextlib import closing, contextmanager, nullcontext
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from backend.athlete.profile import ProfileService
from backend.backup import export as export_module
from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.export import (
    PRIVACY_EXPORT_FORMAT_VERSION,
    PRIVACY_EXPORT_JSONL_FILES,
    PrivacyArchiveExportConfig,
    PrivacyArchiveExportService,
)
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.canonical.activity_detail import (
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ActivityStrengthSet,
    ActivityStrengthSetSet,
    ZoneBucket,
    ZoneDistribution,
)
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.section_items import SectionItem
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ExerciseCategory,
    LapKind,
    LapSource,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    StreamChannel,
    StreamResolution,
    StrengthSetSource,
    StrengthSetType,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db import canonical_store, garmin_store
from backend.db.activity_detail_store import replace_detail_set, save_analysis
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.db.schema import (
    CURRENT_DATABASE_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    initialize_schema,
)
from backend.performance.local_tss import METHOD_ID as LOCAL_LOAD_METHOD
from backend.performance.session_metrics import METHOD_ID as SESSION_METRICS_METHOD
from backend.privacy import (
    PRIVACY_DELETE_CONFIRMATION_TEXT,
    PRIVACY_DELETE_SCOPE,
    PrivacyDeleteDependencies,
    PrivacyDeleteService,
)
from backend.provider_credentials import CREDENTIAL_KV_KEYS

STAMP = "2026-10-01T08:00:00+00:00"
SENTINEL_NOTE = "synthetic-note-sentinel"

# Export disposition of every table. A table is "exported" through the named
# archive member(s), or excluded with the reason.
EXPORTED_TABLE_MEMBERS: dict[str, tuple[str, ...]] = {
    "provider_records": ("provider_records.jsonl", "garmin_snapshot.json"),
    "activity_sessions": ("activity_sessions.jsonl",),
    "activity_records": ("activity_records.jsonl",),
    "observations": ("observations.jsonl",),
    "activity_detail_sets": ("activity_detail_sets.jsonl",),
    "activity_stream_channels": ("activity_stream_channels.jsonl",),
    "activity_laps": ("activity_laps.jsonl",),
    "activity_zone_times": ("activity_zone_times.jsonl",),
    "activity_strength_sets": ("activity_strength_sets.jsonl",),
    "activity_detail_analysis": ("activity_detail_analysis.jsonl",),
    "sleep_periods": ("sleep_periods.jsonl",),
    "zone_configurations": ("zone_configurations.jsonl",),
    "categorical_observations": ("categorical_observations.jsonl",),
    "gear_items": ("gear_items.jsonl",),
    "gear_activity_links": ("gear_activity_links.jsonl",),
    "power_curve_points": ("power_curve_points.jsonl",),
    "power_curve_fetches": ("power_curve_fetches.jsonl",),
    "athlete_checkins": ("athlete_checkins.jsonl",),
    "activity_feedback": ("activity_feedback.jsonl",),
    "external_calendar_events": ("external_calendar_events.jsonl",),
    "external_calendar_decisions": ("external_calendar_decisions.jsonl",),
    "public_event_sources": ("public_event_sources.jsonl",),
    "public_event_candidates": ("public_event_candidates.jsonl",),
    "competitions": ("competitions.jsonl",),
    "competition_sync_tombstones": ("competition_sync_tombstones.jsonl",),
    "remote_links": ("remote_links.jsonl",),
    "messages": ("messages.jsonl",),
    "coach_plan_artifacts": ("coach_plan_artifacts.jsonl",),
    "coach_commands": ("coach_commands.jsonl",),
    "coach_action_proposals": ("coach_action_proposals.jsonl",),
    "snapshots": ("snapshots.jsonl",),
    "workout_library": ("workout_library.jsonl",),
    "planned_units": ("planned_units.jsonl",),
    "training_plans": ("training_plans.jsonl",),
    "plan_adjustments": ("plan_adjustments.jsonl",),
    "change_history": ("change_history.jsonl",),
    "provider_refresh_history": ("provider_refresh_history.jsonl",),
    "sync_jobs": ("sync_jobs.jsonl",),
    "sync_job_items": ("sync_job_items.jsonl",),
    "provider_sync_cursors": ("provider_sync_cursors.jsonl",),
    "nutrition_logs": ("nutrition_logs.jsonl",),
    "nutrition_sync_dates": ("nutrition_sync_dates.jsonl",),
    "nutrition_templates": ("nutrition_templates.jsonl",),
    "nutrition_products": ("nutrition_products.jsonl",),
    # Every key/value row except the excluded keys, in four members.
    "kv": (
        "application_state.json",
        "profile.json",
        "garmin_snapshot.json",
        "weather_cache.json",
    ),
}
EXPORT_EXCLUDED_TABLES: dict[str, str] = {
    "sessions": "login sessions hold credential hashes; restore scrubs them too",
    "planning_state": "a revision counter; planning.json carries the planning data",
}
# Export columns left out of an explicit SELECT, with the reason. A new column of
# an explicitly selected table fails the guard until it is exported or listed.
EXPORT_COLUMNS_NOT_EXPORTED: dict[str, dict[str, str]] = {
    "competition_sync_tombstones": {"id": "surrogate key"},
    "messages": {"id": "surrogate key", "client_turn_id": "idempotency key"},
    "activity_stream_channels": {
        "detail_kind": "constant for stream channels",
        "data": "exported decoded as values",
    },
    "coach_action_proposals": {
        "session_csrf_hash": "credential hash binding the proposal to a session",
        "action_token_hash": "credential hash of the one-use action token",
    },
    "provider_records": {"observed_on": "index copy of a day inside the payload"},
    "kv": {"updated_at": "bookkeeping"},
}
# Schema version -> export format version that documents it. Bump both together.
# Format 14 adds provider_settings.json without a schema change; format 17
# adds table bookkeeping and coach_action_proposals.jsonl, also without one.
EXPORT_FORMAT_FOR_SCHEMA = {22: 12, 23: 14, 24: 15, 25: 17, 26: 17, 27: 18, 28: 19}

# Key/value families (exact key or prefix ending in ":") and what the privacy
# export does with them. "exported": application_state.json; "excluded": never
# exported, with the reason; "dropped": removed by the _running/_status rule.
KV_EXPORT_DISPOSITION: dict[str, str] = {
    "provider_credentials": "excluded: API keys and the Personal API key; only the non-secret fields leave, in provider_settings.json",
    "garmin_oauth_tokens": "excluded: Garmin tokens",
    "garmin_tokenstore_state": "excluded: connection state of the Garmin token file",
    "wahoo_oauth_tokens": "excluded: Wahoo tokens",
    "wahoo_oauth_state": "excluded: Wahoo OAuth state",
    "profile": "excluded: exported as profile.json",
    "garmin_snapshot": "excluded: rebuilt as garmin_snapshot.json",
    "garmin_state": "excluded: rebuilt as garmin_snapshot.json",
    "garmin_snapshot_legacy": "excluded: retired copy of garmin_snapshot.json",
    "weather_cache": "excluded: exported as weather_cache.json",
    "garmin_personal_key_rejected": "exported",
    "garmin_sdk_threshold_failures": "exported",
    "garmin_sdk_skipped": "exported",
    "rating_backfill_removal_state": "exported",
    "garmin_activity_detail_backfill": "exported",
    "garmin_metric_export_fields": "exported",
    "garmin_metric_export_enabled": "exported",
    "intervals_ingest_enabled": "exported",
    "intervals_purge_state": "exported",
    "local_load_state": "exported",
    "session_metrics_state": "exported",
    "activity_weather_state": "exported",
    "activity_routes": "exported",
    "activity_routes_state": "exported",
    "session_analysis_state": "exported",
    "session_focus_backfill_state": "exported",
    "profile_weekly_plan_removal_state": "exported",
    "session_rebundle_state": "exported",
    "canonical_backfill_state": "exported",
    "equipment:": "exported",
    "equipment_assignment:": "exported",
    "last_garmin_metric_export_status": "dropped: _status suffix",
    "morning_checkin_status": "dropped: _status suffix",
    "sync_running": "dropped: _running suffix",
}
KV_SECRET_NAME = re.compile(
    r"token|secret|password|credential|oauth|api_key", re.IGNORECASE
)


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


def provenance(provider: ProviderId | None, **overrides) -> Provenance:
    values = {
        "provider": provider,
        "source_kind": SourceKind.PROVIDER_REPORTED,
        "source_record_id": None,
        "recorded_by": RecordingOrigin.GARMIN,
        "retrieved_at": datetime(2026, 10, 1, 8, tzinfo=UTC),
        "label": None,
    }
    values.update(overrides)
    return Provenance(**cast(Any, values))


class DataKindFixture(unittest.TestCase):
    """A schema-initialized SQLite file with the data kinds added since 1.13.40."""

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

    def kv_set(self, key: str, value: str) -> None:
        self.key_values.set(self.db, key, value)

    def seed_session(self) -> None:
        self.db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, started_at, created_at, updated_at) "
            "VALUES ('act_1', 'garmin', 'g1', ?, ?, ?)",
            (STAMP, STAMP, STAMP),
        )
        self.db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "state, mapper_version, source_kind, recorded_by, sport, environment, "
            "started_at, load_model, details, fetched_at, created_at, updated_at) "
            "VALUES ('garmin', 'g1', 'act_1', 'active', 1, 'provider_reported', "
            "'garmin', 'strength', 'indoor', ?, 'unknown', ?, ?, ?, ?)",
            (
                STAMP,
                json.dumps({"rpe": 6.0, "feel": 75, "min_hr": 52}),
                STAMP,
                STAMP,
                STAMP,
            ),
        )

    def seed_derived_observations(self) -> None:
        for kind, method, value in (
            (MetricKind.SESSION_LOAD, LOCAL_LOAD_METHOD, 55.0),
            (MetricKind.EFFICIENCY_FACTOR, SESSION_METRICS_METHOD, 1.4),
        ):
            canonical_store.upsert_observation(
                self.db,
                Observation(
                    kind=kind,
                    value=MetricValue(value, kind.unit),
                    observed_on=date(2026, 10, 1),
                    observed_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
                    provenance=provenance(
                        None,
                        source_kind=SourceKind.DERIVED,
                        source_record_id="act_1",
                        retrieved_at=None,
                        label="derived",
                    ),
                    sport=Sport.RIDE,
                    method=method,
                    method_version=1,
                    input_fingerprint="f" * 64,
                ),
                mapper_version=1,
                now=STAMP,
                owner="act_1",
            )

    def seed_garmin_rating(self) -> None:
        garmin_store.put_section(
            self.db,
            "activity_ratings",
            [
                SectionItem(
                    key="g1",
                    observed_on="2026-10-01",
                    value={
                        "activityId": "g1",
                        "directWorkoutRpe": 60,
                        "directWorkoutFeel": 75,
                        "minHR": 52,
                    },
                )
            ],
            fetched_at=STAMP,
            now=STAMP,
            mapper_version=1,
            replace=False,
        )

    def seed_detail(self) -> None:
        header = {
            "provider_activity_id": "g1",
            "provenance": provenance(ProviderId.GARMIN),
            "origin": ActivityDetailOrigin.FETCH,
        }
        details = (
            ActivityStreamSet(
                **cast(Any, header),
                resolution=StreamResolution.FULL,
                channels={
                    StreamChannel.TIME_S: (0.0, 1.0),
                    StreamChannel.HEART_RATE_BPM: (120.0, 121.0),
                },
            ),
            ActivityLapSet(
                **cast(Any, header),
                lap_source=LapSource.DEVICE_LAPS,
                laps=(ActivityLap(0, LapKind.LAP, 0.0, 1.0, avg_hr=120.0),),
            ),
            ZoneDistribution(
                **cast(Any, header),
                metric=ZoneMetric.HEART_RATE,
                boundary_source=ZoneBoundarySource.UNKNOWN,
                buckets=(ZoneBucket(1, 1.0),),
            ),
            ActivityStrengthSetSet(
                **cast(Any, header),
                source=StrengthSetSource.FIT_SET_MESSAGES,
                sets=(
                    ActivityStrengthSet(
                        index=0,
                        set_type=StrengthSetType.ACTIVE,
                        exercise_category=ExerciseCategory.DEADLIFT,
                        exercise_name="BARBELL_DEADLIFT",
                        reps=5,
                        weight_kg=80.0,
                        duration_s=30.0,
                    ),
                ),
            ),
        )
        for detail in details:
            replace_detail_set(
                self.db, detail, mapper_version=1, summary_sha256=None, now=STAMP
            )
        save_analysis(
            self.db,
            "act_1",
            analysis_version=1,
            input_sha256="b" * 64,
            payload={
                "hr_histogram": {"bin_width": 1, "counts": {"120": 30, "121": 12}},
                "zone_times": {"heart_rate": [10, 20, 30, 0, 0]},
            },
            now=STAMP,
        )

    def _seed_bookkeeping_rows(self) -> None:
        self.db.execute(
            "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
            "VALUES ('{\"marker\": 1}', ?, ?, 3)",
            (STAMP, STAMP),
        )
        self.db.execute(
            "INSERT INTO workout_library(id, local_id, external_id, payload, sync_state, "
            "sync_error, last_synced_at, updated_at) VALUES "
            "('lib-1', 'local-1', 'ext-1', '{\"name\": \"Easy\", \"sport\": \"run\"}', "
            "'synced', 'none', ?, ?)",
            (STAMP, STAMP),
        )
        self.db.execute(
            "INSERT INTO competitions(id, name, event_date, sport, priority, distance, "
            "target, course_profile, notes, created_at, updated_at) VALUES "
            "('race-1', 'Synthetic Race', '2026-10-10', 'run', 'A', '10 km', '', '', '', ?, ?)",
            (STAMP, STAMP),
        )
        self.db.execute(
            "INSERT INTO coach_action_proposals(id, session_csrf_hash, action_type, "
            "target_system, object_ids, diff, payload, payload_hash, action_token_hash, "
            "status, expires_at, created_at) VALUES ('prop-1', 'synthetic-session-hash', "
            "'local_coach_write', 'local', '[]', '{}', '{}', 'payload-hash', "
            "'synthetic-token-hash', 'ready', 1.0, ?)",
            (STAMP,),
        )
        self.db.commit()

    def _seed_everything(self) -> None:
        self.seed_session()
        self.seed_derived_observations()
        self.seed_garmin_rating()
        self.seed_detail()
        for entity_kind, local_id, provider in (
            ("planned_unit", "pu-1", "garmin"),
            ("library_workout", "lib-1", "garmin"),
            ("observation", "weight", "intervals"),
        ):
            self.db.execute(
                "INSERT INTO remote_links(entity_kind, local_id, provider, remote_id, "
                "sync_state) VALUES (?, ?, ?, ?, 'synced')",
                (entity_kind, local_id, provider, f"remote-{local_id}"),
            )
        self.db.execute(
            "INSERT INTO change_history(id, entity_type, entity_id, action, source, "
            "created_at, before_hash, after_hash, diff) VALUES "
            "('chg-1', 'nutrition_entry', 'meal-1', 'update', 'api', ?, 'a', 'b', ?)",
            (
                STAMP,
                json.dumps(
                    {
                        "fields": {"kcal": {"before": 100, "after": 250}},
                        "before_present": True,
                        "after_present": True,
                    }
                ),
            ),
        )
        for stream in ("rating_history", "wellness_history"):
            self.db.execute(
                "INSERT INTO provider_sync_cursors(provider, stream, cursor, "
                "updated_at) VALUES ('garmin', ?, '2026-09-01', ?)",
                (stream, STAMP),
            )
        self.kv_set("profile", json.dumps({"name": "Synthetic", "sex": "female"}))
        self.kv_set(
            "garmin_metric_export_fields", json.dumps(["weight", "threshold_hr"])
        )
        self.kv_set("garmin_metric_export_enabled", "true")
        self.kv_set("intervals_purge_state", json.dumps({"status": "done"}))
        self.kv_set("intervals_ingest_enabled", "0")
        self.kv_set("rating_backfill_removal_state", json.dumps({"status": "finished"}))
        self.kv_set("local_load_state", json.dumps({"stage": "local_load"}))
        self.kv_set("session_metrics_state", json.dumps({"stage": "metrics"}))
        self.db.commit()

    def profile_service(self) -> ProfileService:
        return ProfileService(
            _Manager(self.db),
            ProfileRepository(self.key_values),
            self.key_values,
            on_location_changed=lambda *_args, **_kwargs: None,
            mutation_coordinator=threading.RLock(),
        )

    def _export_archive(self) -> zipfile.ZipFile:
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
            cast(Any, _Manager(self.db)),
            self.key_values,
            self.profile_service(),
            cast(Any, _Competitions()),
            cast(Any, _Adaptive()),
            config,
        )
        with patch(
            "backend.backup.export.planning_season.planning_state", return_value={}
        ):
            path = service.create_file()
        self.addCleanup(path.unlink, missing_ok=True)
        archive = zipfile.ZipFile(path)
        self.addCleanup(archive.close)
        return archive

    def _delete_service(self) -> PrivacyDeleteService:
        return PrivacyDeleteService(
            PrivacyDeleteDependencies(
                database_manager=cast(Any, _Manager(self.db)),
                database_lock=_Lock(),
                key_value_repository=self.key_values,
                maintenance_gate=cast(Any, _Gate()),
                profile_mutation_coordinator=threading.RLock(),
                planning_revision_service=cast(Any, _PlanningRevision()),
                openai_client=cast(Any, _OpenAI()),
                logger=Mock(),
                diagnostics_suspended=nullcontext,
            )
        )

    @staticmethod
    def lines(archive: zipfile.ZipFile, name: str) -> list[dict]:
        return [json.loads(line) for line in archive.read(name).splitlines() if line]


class CoverageGuardTests(DataKindFixture):
    def test_every_table_is_exported_or_excluded_with_a_reason(self):
        schema_tables = set(CURRENT_DATABASE_SCHEMA)
        created = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertEqual(created, schema_tables)
        decided = set(EXPORTED_TABLE_MEMBERS) | set(EXPORT_EXCLUDED_TABLES)
        self.assertEqual(
            schema_tables - decided,
            set(),
            "a new table needs an export decision in this test and in backend/backup/export.py",
        )
        self.assertEqual(decided - schema_tables, set(), "a decided table is gone")
        self.assertFalse(set(EXPORTED_TABLE_MEMBERS) & set(EXPORT_EXCLUDED_TABLES))
        for table, reason in EXPORT_EXCLUDED_TABLES.items():
            self.assertTrue(reason, table)

    def test_every_export_member_is_decided_and_present_in_a_real_archive(self):
        jsonl = {
            member
            for members in EXPORTED_TABLE_MEMBERS.values()
            for member in members
            if member.endswith(".jsonl")
        }
        self.assertEqual(jsonl, set(PRIVACY_EXPORT_JSONL_FILES))
        archive = self._export_archive()
        names = set(archive.namelist())
        for members in EXPORTED_TABLE_MEMBERS.values():
            self.assertLessEqual(set(members), names)
        manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["format_version"], PRIVACY_EXPORT_FORMAT_VERSION)
        self.assertEqual(set(manifest["jsonl_files"]), set(PRIVACY_EXPORT_JSONL_FILES))

    def test_export_format_version_follows_the_schema_version(self):
        self.assertEqual(
            EXPORT_FORMAT_FOR_SCHEMA.get(CURRENT_SCHEMA_VERSION),
            PRIVACY_EXPORT_FORMAT_VERSION,
            "a schema change needs an export format decision: add the new pair here",
        )

    def test_exported_rows_carry_every_live_column_but_the_listed_ones(self):
        self._seed_everything()
        self._seed_bookkeeping_rows()
        archive = self._export_archive()
        checked = set()
        for table, members in EXPORTED_TABLE_MEMBERS.items():
            if len(members) != 1 or not members[0].endswith(".jsonl"):
                continue
            lines = archive.read(members[0]).splitlines()
            if not lines:
                continue
            keys = set(json.loads(lines[0]))
            allowed = set(EXPORT_COLUMNS_NOT_EXPORTED.get(table, {}))
            with self.subTest(table=table):
                self.assertEqual(
                    CURRENT_DATABASE_SCHEMA[table] - keys - allowed,
                    set(),
                    "an exported row lacks a live column that is not listed",
                )
                self.assertEqual(keys & allowed, set(), "a listed column is exported")
            checked.add(table)
        self.assertLessEqual(
            {"snapshots", "workout_library", "competitions", "coach_action_proposals"},
            checked,
        )
        exported = b"".join(archive.read(name) for name in archive.namelist())
        self.assertNotIn(b"synthetic-session-hash", exported)
        self.assertNotIn(b"synthetic-token-hash", exported)

    def test_explicit_export_columns_cover_every_column_but_the_listed_ones(self):
        source = Path(export_module.__file__).read_text(encoding="utf-8")
        # The persistence owners hold the column lists of some exported tables.
        for store in (
            Path(export_module.__file__).parents[1].joinpath("db").glob("*.py")
        ):
            text = store.read_text(encoding="utf-8")
            source += "".join(
                ast.get_source_segment(text, node) or ""
                for node in ast.walk(ast.parse(text))
                if isinstance(node, ast.FunctionDef)
                and node.name.endswith("export_rows")
            )
        joined = re.sub(r'"\s*\n\s*"', "", source)
        checked = set()
        for match in re.finditer(r'"SELECT (.*?) FROM (\w+)', joined):
            columns, table = match.group(1), match.group(2)
            if columns.strip() == "*" or table not in CURRENT_DATABASE_SCHEMA:
                continue
            selected = {part.strip().split(" AS ")[-1] for part in columns.split(",")}
            allowed = set(EXPORT_COLUMNS_NOT_EXPORTED.get(table, {}))
            with self.subTest(table=table):
                self.assertEqual(
                    CURRENT_DATABASE_SCHEMA[table] - selected - allowed,
                    set(),
                    "a column is neither exported nor listed as excluded",
                )
                self.assertEqual(selected - CURRENT_DATABASE_SCHEMA[table], set())
            checked.add(table)
        # The listed exclusions only name columns that exist and are really missing.
        for table, columns in EXPORT_COLUMNS_NOT_EXPORTED.items():
            if table in checked:
                self.assertLessEqual(set(columns), CURRENT_DATABASE_SCHEMA[table])
        # #2710: column lists that moved into the persistence owners stay checked.
        self.assertLessEqual(
            {
                "observations",
                "activity_records",
                "provider_sync_cursors",
                "messages",
                "coach_commands",
                "planned_units",
                "workout_library",
            },
            checked,
        )

    def test_delete_scope_lists_every_table_exactly_as_the_schema_does(self):
        scoped = {
            table
            for _category, _label, tables in PRIVACY_DELETE_SCOPE
            for table in tables
        }
        self.assertEqual(scoped, set(CURRENT_DATABASE_SCHEMA))

    def test_the_listed_kv_families_are_exported_or_excluded_with_a_reason(self):
        for key, disposition in KV_EXPORT_DISPOSITION.items():
            with self.subTest(key=key):
                self.assertRegex(disposition, r"^(exported|excluded: .+|dropped: .+)$")
                self.kv_set(key, json.dumps({"value": 1}))
        self.db.commit()
        state = PrivacyArchiveExportService._application_state(self.db)
        for key, disposition in KV_EXPORT_DISPOSITION.items():
            with self.subTest(key=key):
                self.assertEqual(key in state, disposition == "exported")
        # Every credential key the application defines stays excluded.
        self.assertFalse(set(state) & CREDENTIAL_KV_KEYS)

    def test_literal_secret_named_kv_keys_in_the_code_are_excluded_from_the_export(
        self,
    ):
        names: set[str] = set()
        pattern = re.compile(r"^[a-z][a-z0-9_]*$")
        for path in Path("backend").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                    if isinstance(node, ast.AnnAssign)
                    else []
                )
                value = getattr(node, "value", None)
                if not (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and pattern.match(value.value)
                ):
                    continue
                if any(
                    isinstance(target, ast.Name)
                    and re.search(r"(STATE|_KEY|TOKENS?|CREDENTIALS?)$", target.id)
                    for target in targets
                ):
                    names.add(value.value)
        secret_named = {name for name in names if KV_SECRET_NAME.search(name)}
        # Payload field names, not key/value rows.
        secret_named -= {"garmin_personal_api_key", "garmin_personal_api_key_expires"}
        self.assertIn("provider_credentials", secret_named)
        unexcluded = {name for name in secret_named if name not in CREDENTIAL_KV_KEYS}
        self.assertEqual(
            unexcluded,
            set(),
            "a secret-named key/value key must be added to CREDENTIAL_KV_KEYS",
        )


class DataKindExportTests(DataKindFixture):
    def test_every_new_data_kind_reaches_the_privacy_export(self):
        self._seed_everything()
        archive = self._export_archive()
        observations = self.lines(archive, "observations.jsonl")
        self.assertEqual(
            {
                (row["metric"], row["method"], row["source_kind"])
                for row in observations
            },
            {
                ("session_load", LOCAL_LOAD_METHOD, "derived"),
                ("efficiency_factor", SESSION_METRICS_METHOD, "derived"),
            },
        )
        self.assertEqual({row["owner_record_id"] for row in observations}, {"act_1"})
        self.assertTrue(all(row["state"] == "active" for row in observations))

        snapshot = json.loads(archive.read("garmin_snapshot.json"))
        self.assertEqual(
            snapshot["activity_ratings"][0]["directWorkoutRpe"], 60, "RPE rating"
        )
        self.assertEqual(snapshot["activity_ratings"][0]["directWorkoutFeel"], 75)
        self.assertEqual(snapshot["activity_ratings"][0]["minHR"], 52)
        records = self.lines(archive, "activity_records.jsonl")
        self.assertEqual(records[0]["details"]["min_hr"], 52)

        sets = self.lines(archive, "activity_strength_sets.jsonl")
        self.assertEqual(
            [(row["exercise_name"], row["reps"], row["weight_kg"]) for row in sets],
            [("BARBELL_DEADLIFT", 5, 80.0)],
        )
        detail_sets = {
            row["detail_kind"]: row
            for row in self.lines(archive, "activity_detail_sets.jsonl")
        }
        self.assertEqual(detail_sets["strength_sets"]["set_source"], "fit_set_messages")
        self.assertLessEqual(
            {"streams", "laps", "strength_sets"}, set(detail_sets), "FIT-derived parts"
        )
        self.assertEqual(len(self.lines(archive, "activity_stream_channels.jsonl")), 2)
        self.assertEqual(len(self.lines(archive, "activity_laps.jsonl")), 1)

        analysis = self.lines(archive, "activity_detail_analysis.jsonl")[0]["payload"]
        self.assertEqual(analysis["hr_histogram"]["counts"]["120"], 30)
        self.assertEqual(analysis["zone_times"]["heart_rate"], [10, 20, 30, 0, 0])

        links = {
            (row["entity_kind"], row["provider"])
            for row in self.lines(archive, "remote_links.jsonl")
        }
        self.assertLessEqual(
            {("planned_unit", "garmin"), ("library_workout", "garmin")}, links
        )
        self.assertIn(("observation", "intervals"), links)

        history = self.lines(archive, "change_history.jsonl")[0]
        self.assertEqual(history["entity_type"], "nutrition_entry")
        self.assertEqual(history["diff"]["fields"], {"kcal": {"changed": True}})
        self.assertNotIn("250", json.dumps(history), "values stay out of history")

        cursors = {
            (row["provider"], row["stream"])
            for row in self.lines(archive, "provider_sync_cursors.jsonl")
        }
        self.assertEqual(
            cursors, {("garmin", "rating_history"), ("garmin", "wellness_history")}
        )

        self.assertEqual(json.loads(archive.read("profile.json"))["sex"], "female")
        state = json.loads(archive.read("application_state.json"))
        self.assertEqual(
            state["garmin_metric_export_fields"], ["weight", "threshold_hr"]
        )
        self.assertIs(state["garmin_metric_export_enabled"], True)
        self.assertEqual(state["intervals_purge_state"], {"status": "done"})
        self.assertEqual(state["local_load_state"], {"stage": "local_load"})
        self.assertEqual(state["session_metrics_state"], {"stage": "metrics"})
        self.assertEqual(state["rating_backfill_removal_state"], {"status": "finished"})


class DataKindDeleteTests(DataKindFixture):
    def test_the_privacy_delete_removes_every_new_data_kind(self):
        self._seed_everything()
        tables = {
            table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in CURRENT_DATABASE_SCHEMA
        }
        for table in (
            "observations",
            "provider_records",
            "activity_strength_sets",
            "activity_detail_sets",
            "activity_detail_analysis",
            "remote_links",
            "change_history",
            "provider_sync_cursors",
        ):
            self.assertGreater(tables[table], 0, table)
        result = self._delete_service().delete(PRIVACY_DELETE_CONFIRMATION_TEXT)
        self.assertTrue(result["local_data_deleted"])
        for table in set(CURRENT_DATABASE_SCHEMA) - {"kv"}:
            with self.subTest(table=table):
                self.assertEqual(
                    self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )
        keys = {row[0] for row in self.db.execute("SELECT key FROM kv")}
        self.assertEqual(keys, {"profile", "garmin_tokenstore_state"})
        profile = json.loads(
            self.db.execute("SELECT value FROM kv WHERE key = 'profile'").fetchone()[0]
        )
        self.assertEqual(profile["sex"], "")

    def test_the_privacy_preview_counts_every_remote_link_kind_it_deletes(self):
        # The metric-export link (entity kind "observation") is deleted with the
        # others and counted under the provider data group.
        self._seed_everything()
        preview = self._delete_service().preview()
        counted = {item["id"]: item["records"] for item in preview["categories"]}
        links = self.db.execute("SELECT COUNT(*) FROM remote_links").fetchone()[0]
        self.assertEqual(links, 3)
        observation_links = self.db.execute(
            "SELECT COUNT(*) FROM remote_links WHERE entity_kind = 'observation'"
        ).fetchone()[0]
        self.assertEqual(observation_links, 1)
        provider_tables = next(
            tables
            for category, _label, tables in PRIVACY_DELETE_SCOPE
            if category == "provider_data"
        )
        provider_rows = sum(
            self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in provider_tables
            if table != "remote_links"
        )
        self.assertEqual(counted["provider_data"], provider_rows + observation_links)
        self.assertEqual(
            self._delete_service().delete(PRIVACY_DELETE_CONFIRMATION_TEXT)[
                "deleted_categories"
            ]["provider_data"],
            counted["provider_data"],
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM remote_links").fetchone()[0], 0
        )


class BackupRestoreRoundTripTests(DataKindFixture):
    def test_backup_restore_keeps_every_table_row_for_row(self):
        self._seed_everything()
        self.db.execute(
            "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, "
            "last_seen) VALUES ('t', 'c', 9e12, ?, ?)",
            (STAMP, STAMP),
        )
        self.db.commit()
        manager = DatabaseManager(self.database_path, sqlite3, timeout=1.0)
        self.addCleanup(manager.close)
        backup = DatabaseBackupService(
            manager,
            Mock(),
            DatabaseBackupConfig(
                database_path=self.database_path,
                data_dir=self.root,
                maximum_bytes=50_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=30,
                monotonic=lambda: 0.0,
                disk_usage=lambda _path: SimpleNamespace(free=10**12),
            ),
            Mock(),
        ).read_bytes()
        staged = self.root / "restore.db"
        staged.write_bytes(backup)
        DatabaseRestoreValidationService(
            DatabaseRestoreValidationConfig(
                data_dir=self.root,
                maximum_bytes=50_000_000,
                app_password="",
                sqlcipher_available=False,
                sqlite_backend=sqlite3,
                configure_cipher=Mock(),
                row_factory=sqlite3.Row,
                schema_is_current=database_schema_is_current,
                startup_invariants=lambda _db: None,
                migrate_schema=migrate_schema,
            )
        ).validate(staged)
        with closing(sqlite3.connect(staged)) as restored:
            restored.row_factory = sqlite3.Row
            self.assertEqual(
                restored.execute("PRAGMA user_version").fetchone()[0],
                CURRENT_SCHEMA_VERSION,
            )
            for table in sorted(CURRENT_DATABASE_SCHEMA):
                with self.subTest(table=table):
                    order = "key" if table == "kv" else "rowid"
                    query = f"SELECT * FROM {table} ORDER BY {order}"
                    original = [tuple(row) for row in self.db.execute(query)]
                    kept = [tuple(row) for row in restored.execute(query)]
                    if table == "sessions":
                        self.assertEqual(kept, [], "restore scrubs sessions")
                        self.assertEqual(len(original), 1)
                    else:
                        self.assertEqual(kept, original)
        self.assertGreater(
            self.db.execute("SELECT COUNT(*) FROM activity_strength_sets").fetchone()[
                0
            ],
            0,
        )


if __name__ == "__main__":
    unittest.main()
