"""Local backup serialization and privacy archive creation."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend import change_history
from backend.canonical import garmin_payload
from backend.db import coach_store, garmin_store, planning_store
from backend.db.activity_detail_store import analysis_export_rows, stream_export_rows
from backend.db.canonical_domain_store import zone_configuration_export_rows
from backend.errors import AppError
from backend.observability import sanitized_provider_payload
from backend.planning import season as planning_season
from backend.provider_credentials import (
    CREDENTIAL_KV_KEYS,
    PROVIDER_CREDENTIALS_KEY,
    stored_visible_settings,
)
from backend.sync.jobs import job_export_rows, job_item_export_rows
from backend.weather import cache as weather_cache

if TYPE_CHECKING:
    from backend.athlete.profile import ProfileService
    from backend.db.manager import DatabaseManager
    from backend.db.repositories import KeyValueRepository
    from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
    from backend.planning.competition_service import CompetitionService


PayloadDecoder = Callable[[Any], Any]
Clock = Callable[[], float]
TimeoutErrorFactory = Callable[[], Exception]

# Version 3 adds activity_feedback.provider (schema v7) to activity_feedback.jsonl.
# Version 4 adds remote_links.jsonl and competition_sync_tombstones.provider
# (schema v8).
# Version 5 exports stored sports in the canonical vocabulary: competitions gain
# environment and sport_detail, workouts and planned units carry sport,
# environment and sport_detail instead of type (schema v9).
# Version 6 adds the canonical activity detail files (schema v10); stream
# channels carry decoded point lists with null for gaps.
# Version 7 adds sleep_periods, zone_configurations with decoded limit lists,
# categorical_observations, gear_items and gear_activity_links, including
# retired rows, plus activity_sessions.merged_into_retained and
# activity_feedback.session_id (schema v15).
# Version 8 names the start and planned duration of local planning records
# starts_at_local and planned_duration_s instead of start_date_local and
# moving_time: competitions, workouts, planned units and their stored conflicts,
# Coach plan artifacts, adaptive previews and planning.json (schema v16).
# Version 9 adds power_curve_points and power_curve_fetches, including retired
# rows (schema v17).
# Version 10 adds activity_feedback.session_rpe_rated_at (schema v18).
# Version 11 adds observations.state and observations.owner_record_id; retired
# observations are included (schema v21).
# Version 12 adds activity_strength_sets and activity_detail_sets.set_source
# (schema v22).
# Version 13 adds activity_feedback.purpose (schema v23).
# Version 14 adds provider_settings.json, the stored non-secret provider fields.
# Version 15 adds activity_detail_sets.hr_source, power_source and sensors
# (schema v24).
# Version 16 adds activity_detail_sets.dfa_alpha1, the stored first threshold
# estimate of a chest-strap stream set (schema v25).
# Version 17 exports the bookkeeping of snapshots (id, created_at, synced_at,
# recent_activity_count), workout_library (id, local_id, external_id, sync_*,
# last_synced_at, updated_at) and competitions (created_at, updated_at); both
# files now hold one object per row with the stored document under payload. It
# adds coach_action_proposals.jsonl without the session and action-token hashes
# (no schema change).
# Version 18 drops food_database_entries.jsonl: foods saved from a database
# lookup are rows of nutrition_products.jsonl with their origin, fetch time and
# details (schema v27).
# Version 19 adds external_calendar_decisions.jsonl, the athlete's training
# impact per calendar event (schema v28).
PRIVACY_EXPORT_FORMAT_VERSION = 19


class PrivacyArchiveExportService:
    """Create a bounded, local ZIP archive of durable athlete data."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_values: KeyValueRepository,
        profile: ProfileService,
        competitions: CompetitionService,
        adaptive_preview: AdaptiveReplanPreviewService,
        config: PrivacyArchiveExportConfig,
    ) -> None:
        self._database_manager = database_manager
        self._key_values = key_values
        self._profile = profile
        self._competitions = competitions
        self._adaptive_preview = adaptive_preview
        self._config = config

    @staticmethod
    def _application_state(db: Any) -> dict[str, Any]:
        return application_state(
            db,
            excluded_keys={
                "profile",
                "garmin_snapshot",
                garmin_payload.STATE_KEY,
                garmin_payload.RETIRED_SNAPSHOT_KEY,
                weather_cache.CACHE_KEY,
                *CREDENTIAL_KV_KEYS,
            },
        )

    def _write_jsonl(
        self,
        archive: Any,
        name: str,
        rows: Iterable[Mapping[str, Any]],
        deadline: float,
    ) -> None:
        write_jsonl_rows(
            archive,
            name,
            rows,
            deadline,
            now=self._config.monotonic,
            timeout_error=lambda: AppError(
                408, "Der Export überschreitet das Zeitlimit."
            ),
            max_bytes=self._config.maximum_bytes,
            size_error=lambda: AppError(
                413, "Der Export überschreitet das Größenlimit."
            ),
        )

    def create_file(self) -> Path:
        started = self._config.monotonic()
        self._config.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            database_size = self._config.database_path.stat().st_size
            free_bytes = self._config.disk_usage(self._config.data_dir).free
        except OSError as exc:
            raise AppError(503, "Der Export-Speicher ist nicht verfügbar.") from exc
        required_free = max(
            self._config.minimum_free_bytes,
            min(self._config.maximum_bytes, database_size * 2),
        )
        if free_bytes < required_free:
            raise AppError(
                507, "Für den Export ist nicht ausreichend freier Speicher verfügbar."
            )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".intervals-coach-export-", suffix=".zip", dir=self._config.data_dir
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        deadline = started + self._config.time_limit_seconds
        try:
            with (
                self._database_manager.reader() as db,
                _read_snapshot(db),
                zipfile.ZipFile(
                    temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
                ) as archive,
            ):
                archive.writestr(
                    "profile.json",
                    json.dumps(
                        self._profile.get_from_db(db),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                archive.writestr(
                    "application_state.json",
                    json.dumps(
                        self._application_state(db),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                archive.writestr(
                    "provider_settings.json",
                    json.dumps(
                        stored_visible_settings(
                            self._key_values.get(db, PROVIDER_CREDENTIALS_KEY)
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                for name, rows in PRIVACY_EXPORT_JSONL_SOURCES:
                    self._write_jsonl(archive, name, rows(db), deadline)
                archive.writestr(
                    "planning.json",
                    json.dumps(
                        planning_season.planning_state(
                            self._competitions.list(db=db),
                            self._config.today(),
                            self._adaptive_preview.latest_preview(db=db),
                            self._adaptive_preview.status(db=db),
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                archive.writestr(
                    "garmin_snapshot.json",
                    json.dumps(
                        garmin_store.read_view(db),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                archive.writestr(
                    "weather_cache.json",
                    json.dumps(
                        decode_payload(
                            self._key_values.get(db, weather_cache.CACHE_KEY)
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                if self._config.monotonic() > deadline:
                    raise AppError(408, "Der Export überschreitet das Zeitlimit.")
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        manifest(
                            archive.namelist(),
                            exported_at=self._config.utc_now(),
                            format_version=PRIVACY_EXPORT_FORMAT_VERSION,
                            jsonl_files=PRIVACY_EXPORT_JSONL_FILES,
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            if temporary.stat().st_size > self._config.maximum_bytes:
                raise AppError(413, "Der Export überschreitet das Größenlimit.")
            return temporary
        except BaseException:
            # The archive is plaintext athlete data; an interrupt must not leave it.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise


@contextmanager
def _read_snapshot(db: Any):
    """Keep one consistent WAL read view without serializing application writes."""
    db.execute("BEGIN")
    try:
        yield
    finally:
        db.rollback()


@dataclass(frozen=True)
class PrivacyArchiveExportConfig:
    data_dir: Path
    database_path: Path
    today: Callable[[], date]
    utc_now: Callable[[], str]
    maximum_bytes: int
    minimum_free_bytes: int
    time_limit_seconds: int
    monotonic: Clock = time.monotonic
    disk_usage: Callable[[Path], Any] = shutil.disk_usage


def decode_payload(value: Any) -> Any:
    """Decode a JSON payload, returning an empty object for invalid input."""
    try:
        return json.loads(value)
    except TypeError, ValueError:
        return {}


def sanitized_provider_row(
    row: Mapping[str, Any], *json_columns: str
) -> dict[str, Any]:
    """Copy a provider-table row, decoding and sanitizing its JSON columns."""
    result = dict(row)
    for column in json_columns:
        result[column] = sanitized_provider_payload(decode_payload(result[column]))
    return result


def iter_workout_library(
    db: Any, *, decode: PayloadDecoder = decode_payload
) -> Iterable[dict[str, Any]]:
    """Yield every workout-library row with its sync bookkeeping in the established order."""
    for row in planning_store.library_export_rows(db):
        yield {**dict(row), "payload": decode(row["payload"])}


def application_state(
    db: Any,
    *,
    excluded_keys: set[str],
    excluded_suffixes: tuple[str, ...] = ("_running", "_status"),
    decode: PayloadDecoder = decode_payload,
) -> dict[str, Any]:
    """Project exportable KV state while omitting sensitive/transient keys."""
    state: dict[str, Any] = {}
    for row in db.execute("SELECT key, value FROM kv ORDER BY key"):
        key = str(row["key"])
        if key in excluded_keys or key.endswith(excluded_suffixes):
            continue
        value = decode(row["value"])
        state[key] = value if value != {} or row["value"] == "{}" else row["value"]
    return state


def write_jsonl_rows(
    archive: Any,
    name: str,
    rows: Iterable[Mapping[str, Any]],
    deadline: float,
    *,
    now: Clock,
    timeout_error: TimeoutErrorFactory,
    max_bytes: int | None = None,
    size_error: TimeoutErrorFactory | None = None,
) -> None:
    """Write rows incrementally, preserving the export time and size limits.

    The size limit is checked against the archive written so far, so a large
    table stops the export before it fills the disk rather than at the end.
    """
    with archive.open(name, "w", force_zip64=True) as output:
        for row in rows:
            if now() > deadline:
                raise timeout_error()
            if max_bytes is not None and archive.fp.tell() > max_bytes:
                raise (size_error or timeout_error)()
            output.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
                + b"\n"
            )


def manifest(
    archive_names: Iterable[str],
    *,
    exported_at: str,
    format_version: int,
    jsonl_files: Iterable[str],
) -> dict[str, Any]:
    """Build the stable privacy-export manifest from archive names."""
    return {
        "format": "intervals-coach-privacy-export",
        "format_version": format_version,
        "exported_at": exported_at,
        "status": "complete",
        "categories": sorted(
            name.rsplit(".", 1)[0] for name in archive_names if name != "manifest.json"
        ),
        "jsonl_files": sorted(jsonl_files),
    }


RowSource = Callable[[Any], Iterable[Mapping[str, Any]]]


def _select(sql: str, row: Callable[[Any], Mapping[str, Any]] = dict) -> RowSource:
    return lambda db: (row(item) for item in db.execute(sql))


def _with_payload(row: Any) -> dict[str, Any]:
    return {**dict(row), "payload": decode_payload(row["payload"])}


def _sanitized(*columns: str) -> Callable[[Any], dict[str, Any]]:
    return lambda row: sanitized_provider_row(row, *columns)


def _public_change(row: Any) -> dict[str, Any]:
    return change_history.public_view(dict(row))


# Archive member and row source per exported table, in archive order. Explicit
# column lists leave out the columns tests/test_data_safety_coverage.py names;
# provider JSON columns are decoded and sanitized.
PRIVACY_EXPORT_JSONL_SOURCES: tuple[tuple[str, RowSource], ...] = (
    (
        "competitions.jsonl",
        _select(
            "SELECT id, name, event_date, starts_at_local, sport, environment, sport_detail, priority, category, distance, target, "
            "course_profile, notes, description, planned_duration_s, external_id, intervals_event_id, sync_dirty, "
            "sync_state, sync_conflict, last_synced_at, created_at, updated_at FROM competitions ORDER BY event_date, priority, name"
        ),
    ),
    (
        "competition_sync_tombstones.jsonl",
        _select(
            "SELECT intervals_event_id, external_id, created_at, provider FROM competition_sync_tombstones ORDER BY created_at"
        ),
    ),
    (
        "remote_links.jsonl",
        _select(
            "SELECT entity_kind, local_id, provider, remote_id, remote_external_id, baseline_hash, sync_state, last_synced_at "
            "FROM remote_links ORDER BY entity_kind, local_id, provider"
        ),
    ),
    ("messages.jsonl", lambda db: map(dict, coach_store.message_export_rows(db))),
    (
        "coach_plan_artifacts.jsonl",
        _select(
            "SELECT id, conversation_id, client_turn_id, base_revision, status, payload, created_at, updated_at FROM coach_plan_artifacts ORDER BY created_at"
        ),
    ),
    (
        "coach_commands.jsonl",
        lambda db: map(dict, coach_store.command_export_rows(db)),
    ),
    (
        "coach_action_proposals.jsonl",
        _select(
            "SELECT id, action_type, target_system, object_ids, diff, payload, payload_hash, status, expires_at, created_at, used_at "
            "FROM coach_action_proposals ORDER BY created_at"
        ),
    ),
    (
        "snapshots.jsonl",
        _select(
            "SELECT id, payload, created_at, synced_at, recent_activity_count "
            "FROM snapshots ORDER BY id",
            _with_payload,
        ),
    ),
    ("workout_library.jsonl", iter_workout_library),
    (
        "planned_units.jsonl",
        lambda db: map(_with_payload, planning_store.planned_unit_export_rows(db)),
    ),
    (
        "training_plans.jsonl",
        _select(
            "SELECT id, name, goal, start_date, end_date, status, created_at, updated_at FROM training_plans ORDER BY created_at DESC"
        ),
    ),
    (
        "plan_adjustments.jsonl",
        _select(
            "SELECT id, payload, status, created_at, applied_at FROM plan_adjustments ORDER BY created_at"
        ),
    ),
    (
        "change_history.jsonl",
        _select(
            "SELECT id, entity_type, entity_id, action, source, created_at, before_hash, after_hash, diff FROM change_history ORDER BY created_at",
            _public_change,
        ),
    ),
    (
        "provider_refresh_history.jsonl",
        _select(
            "SELECT id, provider, area, operation_id, trigger, started_at, finished_at, phase, status, error_code, next_retry_at FROM provider_refresh_history ORDER BY started_at"
        ),
    ),
    ("sync_jobs.jsonl", lambda db: map(dict, job_export_rows(db))),
    ("sync_job_items.jsonl", lambda db: map(dict, job_item_export_rows(db))),
    (
        "provider_sync_cursors.jsonl",
        _select(
            "SELECT provider, stream, cursor, high_water_mark, updated_at FROM provider_sync_cursors ORDER BY provider, stream"
        ),
    ),
    *(
        (f"{table}.jsonl", _select(f"SELECT * FROM {table}"))
        for table in (
            "athlete_checkins",
            "activity_feedback",
            "external_calendar_events",
            "external_calendar_decisions",
            "public_event_sources",
            "public_event_candidates",
            "nutrition_logs",
            "nutrition_sync_dates",
            "nutrition_templates",
            "nutrition_products",
        )
    ),
    (
        "provider_records.jsonl",
        _select(
            "SELECT id, provider, record_kind, source_record_id, payload, payload_hash, fetched_at, "
            "mapped_version, state, created_at, updated_at "
            "FROM provider_records ORDER BY provider, record_kind, source_record_id",
            _sanitized("payload"),
        ),
    ),
    (
        "activity_sessions.jsonl",
        _select(
            "SELECT activity_id, primary_provider, primary_provider_activity_id, link_kind, "
            "athlete_confirmed, state, merged_into, merged_into_retained, started_at, local_date, "
            "created_at, updated_at "
            "FROM activity_sessions ORDER BY started_at, activity_id"
        ),
    ),
    (
        "activity_records.jsonl",
        _select(
            "SELECT provider, provider_activity_id, activity_id, state, mapper_version, source_kind, "
            "recorded_by, source_record_id, sport, environment, started_at, local_date, duration_s, "
            "distance_m, load, load_model, avg_hr, avg_power, moving_duration_s, "
            "elevation_gain_m, intensity_pct, max_hr, normalized_power, avg_cadence, "
            "energy_kj, name, details, fetched_at, "
            "created_at, updated_at "
            "FROM activity_records ORDER BY started_at, provider, provider_activity_id",
            _sanitized("details"),
        ),
    ),
    (
        "observations.jsonl",
        _select(
            "SELECT id, natural_key, metric, value, unit, method, aggregation, source_kind, "
            "recorded_by, provider, source_record_id, sport, observed_on, observed_at, "
            "retrieved_at, label, details, mapper_version, state, owner_record_id, created_at, updated_at "
            "FROM observations ORDER BY observed_on, metric, id",
            _sanitized("details"),
        ),
    ),
    *(
        (f"{table}.jsonl", _select(f"SELECT * FROM {table} ORDER BY {order}"))
        for table, order in (
            ("activity_detail_sets", "provider, provider_activity_id, detail_kind"),
            ("activity_laps", "provider, provider_activity_id, lap_index"),
            (
                "activity_zone_times",
                "provider, provider_activity_id, detail_kind, zone_index",
            ),
            ("activity_strength_sets", "provider, provider_activity_id, set_index"),
        )
    ),
    ("activity_stream_channels.jsonl", stream_export_rows),
    ("activity_detail_analysis.jsonl", analysis_export_rows),
    *(
        (
            f"{table}.jsonl",
            _select(f"SELECT * FROM {table} ORDER BY {order}", _sanitized("details")),
        )
        for table, order in (
            ("sleep_periods", "started_at, provider"),
            ("categorical_observations", "observed_on, domain, natural_key"),
            ("gear_items", "provider, gear_id"),
            ("power_curve_points", "provider, duration_s"),
            ("power_curve_fetches", "provider, source_record_id"),
        )
    ),
    (
        "zone_configurations.jsonl",
        lambda db: (
            sanitized_provider_row(row, "details")
            for row in zone_configuration_export_rows(db)
        ),
    ),
    (
        "gear_activity_links.jsonl",
        _select(
            "SELECT * FROM gear_activity_links "
            "ORDER BY provider, gear_id, provider_activity_id"
        ),
    ),
)
PRIVACY_EXPORT_JSONL_FILES = {name for name, _rows in PRIVACY_EXPORT_JSONL_SOURCES}
