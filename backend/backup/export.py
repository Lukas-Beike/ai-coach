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
from backend.db.activity_detail_store import analysis_export_rows, stream_export_rows
from backend.errors import AppError
from backend.observability import sanitized_provider_payload
from backend.planning import season as planning_season
from backend.provider_credentials import CREDENTIAL_KV_KEYS
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
PRIVACY_EXPORT_FORMAT_VERSION = 6
PRIVACY_EXPORT_JSONL_FILES = {
    "provider_records.jsonl",
    "activity_sessions.jsonl",
    "activity_records.jsonl",
    "observations.jsonl",
    "activity_detail_sets.jsonl",
    "activity_stream_channels.jsonl",
    "activity_laps.jsonl",
    "activity_zone_times.jsonl",
    "activity_detail_analysis.jsonl",
    "athlete_checkins.jsonl",
    "activity_feedback.jsonl",
    "external_calendar_events.jsonl",
    "public_event_sources.jsonl",
    "public_event_candidates.jsonl",
    "competitions.jsonl",
    "competition_sync_tombstones.jsonl",
    "remote_links.jsonl",
    "messages.jsonl",
    "coach_plan_artifacts.jsonl",
    "coach_commands.jsonl",
    "snapshots.jsonl",
    "workout_library.jsonl",
    "planned_units.jsonl",
    "training_plans.jsonl",
    "plan_adjustments.jsonl",
    "change_history.jsonl",
    "provider_refresh_history.jsonl",
    "sync_jobs.jsonl",
    "sync_job_items.jsonl",
    "provider_sync_cursors.jsonl",
    "nutrition_logs.jsonl",
    "nutrition_sync_dates.jsonl",
    "nutrition_templates.jsonl",
    "nutrition_products.jsonl",
}


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
    def _planned_units(db: Any) -> Iterable[dict[str, Any]]:
        for row in db.execute(
            "SELECT id, local_id, external_id, payload, sync_dirty, sync_state, sync_error, sync_conflict, baseline_hash, last_synced_at, plan_id, revision, tombstone, command_id, created_at, updated_at "
            "FROM planned_units ORDER BY updated_at"
        ):
            yield {**dict(row), "payload": decode_payload(row["payload"])}

    @staticmethod
    def _application_state(db: Any) -> dict[str, Any]:
        return application_state(
            db,
            excluded_keys={
                "profile",
                "garmin_snapshot",
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
                self._write_jsonl(
                    archive,
                    "competitions.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, name, event_date, start_date_local, sport, environment, sport_detail, priority, category, distance, target, "
                            "course_profile, notes, description, moving_time, external_id, intervals_event_id, sync_dirty, "
                            "sync_state, sync_conflict, last_synced_at FROM competitions ORDER BY event_date, priority, name"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "competition_sync_tombstones.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT intervals_event_id, external_id, created_at, provider FROM competition_sync_tombstones ORDER BY created_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "remote_links.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT entity_kind, local_id, provider, remote_id, remote_external_id, baseline_hash, sync_state, last_synced_at "
                            "FROM remote_links ORDER BY entity_kind, local_id, provider"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "messages.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT role, content, attachments, created_at FROM messages ORDER BY id"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "coach_plan_artifacts.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, conversation_id, client_turn_id, base_revision, status, payload, created_at, updated_at FROM coach_plan_artifacts ORDER BY created_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "coach_commands.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, client_turn_id, conversation_id, intent, target_system, artifact_id, status, receipt, error_class, created_at, updated_at FROM coach_commands ORDER BY created_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "snapshots.jsonl",
                    (
                        decode_payload(row["payload"])
                        for row in db.execute(
                            "SELECT payload FROM snapshots ORDER BY id"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive, "workout_library.jsonl", iter_workout_library(db), deadline
                )
                self._write_jsonl(
                    archive, "planned_units.jsonl", self._planned_units(db), deadline
                )
                self._write_jsonl(
                    archive,
                    "training_plans.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, name, goal, start_date, end_date, status, created_at, updated_at FROM training_plans ORDER BY created_at DESC"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "plan_adjustments.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, payload, status, created_at, applied_at FROM plan_adjustments ORDER BY created_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "change_history.jsonl",
                    (
                        change_history.public_view(dict(row))
                        for row in db.execute(
                            "SELECT id, entity_type, entity_id, action, source, created_at, before_hash, after_hash, diff FROM change_history ORDER BY created_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "provider_refresh_history.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, provider, area, operation_id, trigger, started_at, finished_at, phase, status, error_code, next_retry_at FROM provider_refresh_history ORDER BY started_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "sync_jobs.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, provider, type, status, payload, requested_by, attempts, progress_total, progress_completed, error_class, available_at, started_at, finished_at, created_at, updated_at FROM sync_jobs ORDER BY created_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "sync_job_items.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT id, job_id, item_key, operation, payload_hash, remote_id, status, attempts, error_class, error_detail, created_at, updated_at FROM sync_job_items ORDER BY created_at"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "provider_sync_cursors.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT provider, stream, cursor, high_water_mark, updated_at FROM provider_sync_cursors ORDER BY provider, stream"
                        )
                    ),
                    deadline,
                )
                for table in (
                    "athlete_checkins",
                    "activity_feedback",
                    "external_calendar_events",
                    "public_event_sources",
                    "public_event_candidates",
                    "nutrition_logs",
                    "nutrition_sync_dates",
                    "nutrition_templates",
                    "nutrition_products",
                ):
                    self._write_jsonl(
                        archive,
                        table + ".jsonl",
                        (dict(row) for row in db.execute(f"SELECT * FROM {table}")),
                        deadline,
                    )
                self._write_jsonl(
                    archive,
                    "provider_records.jsonl",
                    (
                        sanitized_provider_row(row, "payload")
                        for row in db.execute(
                            "SELECT id, provider, record_kind, source_record_id, payload, payload_hash, fetched_at, "
                            "mapped_version, state, created_at, updated_at "
                            "FROM provider_records ORDER BY provider, record_kind, source_record_id"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "activity_sessions.jsonl",
                    (
                        dict(row)
                        for row in db.execute(
                            "SELECT activity_id, primary_provider, primary_provider_activity_id, link_kind, "
                            "athlete_confirmed, state, merged_into, started_at, local_date, created_at, updated_at "
                            "FROM activity_sessions ORDER BY started_at, activity_id"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "activity_records.jsonl",
                    (
                        sanitized_provider_row(row, "details")
                        for row in db.execute(
                            "SELECT provider, provider_activity_id, activity_id, state, mapper_version, source_kind, "
                            "recorded_by, source_record_id, sport, environment, started_at, local_date, duration_s, "
                            "distance_m, load, load_model, avg_hr, avg_power, moving_duration_s, "
                            "elevation_gain_m, intensity_pct, max_hr, normalized_power, avg_cadence, "
                            "energy_kj, name, details, fetched_at, "
                            "created_at, updated_at "
                            "FROM activity_records ORDER BY started_at, provider, provider_activity_id"
                        )
                    ),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "observations.jsonl",
                    (
                        sanitized_provider_row(row, "details")
                        for row in db.execute(
                            "SELECT id, natural_key, metric, value, unit, method, aggregation, source_kind, "
                            "recorded_by, provider, source_record_id, sport, observed_on, observed_at, "
                            "retrieved_at, label, details, mapper_version, created_at, updated_at "
                            "FROM observations ORDER BY observed_on, metric, id"
                        )
                    ),
                    deadline,
                )
                for table, order in (
                    ("activity_detail_sets", "provider, provider_activity_id, detail_kind"),
                    ("activity_laps", "provider, provider_activity_id, lap_index"),
                    (
                        "activity_zone_times",
                        "provider, provider_activity_id, detail_kind, zone_index",
                    ),
                ):
                    self._write_jsonl(
                        archive,
                        table + ".jsonl",
                        (
                            dict(row)
                            for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")
                        ),
                        deadline,
                    )
                self._write_jsonl(
                    archive,
                    "activity_stream_channels.jsonl",
                    stream_export_rows(db),
                    deadline,
                )
                self._write_jsonl(
                    archive,
                    "activity_detail_analysis.jsonl",
                    analysis_export_rows(db),
                    deadline,
                )
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
                        decode_payload(self._key_values.get(db, "garmin_snapshot")),
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
        except Exception:
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
    """Yield all workout-library payloads in the established order."""
    for row in db.execute(
        "SELECT payload FROM workout_library "
        "ORDER BY lower(json_extract(payload, '$.sport')), lower(json_extract(payload, '$.name'))"
    ):
        payload = decode(row["payload"])
        if isinstance(payload, dict):
            yield payload


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
) -> None:
    """Write rows incrementally, preserving the export time limit."""
    with archive.open(name, "w", force_zip64=True) as output:
        for row in rows:
            if now() > deadline:
                raise timeout_error()
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
