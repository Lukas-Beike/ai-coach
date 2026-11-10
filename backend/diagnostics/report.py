"""Privacy-safe projection of the application's diagnostic report."""

from __future__ import annotations

import logging
import platform
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from backend.athlete.profile import ProfileService
from backend.calendar.external import ExternalCalendarReader
from backend.canonical.vocabulary import ProviderId
from backend.coach.morning import MorningCheckinStateService
from backend.config import DEFAULT_OPENAI_BASE_URL, Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.diagnostics.canonical_backfill import (
    CanonicalBackfillStatusReader,
    summarize_canonical_backfill,
)
from backend.diagnostics.canonical_counts import activity_count, wellness_day_count
from backend.diagnostics.canonical_coverage import summarize_canonical_coverage
from backend.diagnostics.canonical_read import (
    CanonicalReadStatusReader,
    summarize_canonical_read,
)
from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.plan_sync import summarize_plan_sync
from backend.diagnostics.provider_composition import summarize_provider_composition
from backend.diagnostics.rating_backfill import summarize_rating_backfill
from backend.diagnostics.session_conflicts import summarize_session_conflicts
from backend.diagnostics.stream_backfill import summarize_stream_backfill
from backend.diagnostics.wahoo_state import summarize_wahoo
from backend.observability import DiagnosticCapture, Redactor
from backend.provider_credentials import garmin_tokens_connected
from backend.providers.garmin import GarminClientFactory
from backend.providers.state import ProviderStateService
from backend.runtime.memory import process_memory
from backend.runtime.ports import (
    ActivityRowAndSummaryReader,
    ObservationReader,
    ProviderCoverageReader,
)
from backend.settings import SettingsService
from backend.sync.activity_routes import summarize_activity_routes
from backend.sync.activity_weather import summarize_activity_weather
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.freshness import ProviderFreshnessService
from backend.sync.garmin import GarminFixtureLoader, GarminSyncStateService
from backend.sync.garmin_projection_service import GarminProjectionService
from backend.sync.library import WorkoutLibrarySyncStateService
from backend.sync.local_load import summarize_local_load
from backend.sync.profile_weekly_plan_removal import (
    summarize_profile_weekly_plan_removal,
)
from backend.sync.session_analysis_stage import summarize_session_analysis
from backend.sync.session_focus_backfill import summarize_session_focus_backfill
from backend.sync.session_metrics import summarize_session_metrics
from backend.sync.state import SyncStateRepository

LOGGER = logging.getLogger("intervals_coach")


@dataclass(frozen=True)
class DiagnosticReportDependencies:
    """Concrete application owners required to compose a diagnostic report."""

    database_manager: DatabaseManager
    key_values: KeyValueRepository
    config: Config
    settings: SettingsService
    app_name: str
    app_version: str
    utc_now: Callable[[], str]
    sync_state: SyncStateRepository
    garmin_projection: GarminProjectionService
    garmin_client_factory: GarminClientFactory
    garmin_fixture_loader: GarminFixtureLoader
    provider_state: ProviderStateService
    coach_history: CoachDiagnosticHistoryService
    redactor: Redactor
    provider_freshness: ProviderFreshnessService
    profile: ProfileService
    garmin_sync_state: GarminSyncStateService
    external_calendar_sync: ExternalCalendarSyncService
    external_calendar_reader: ExternalCalendarReader
    morning_checkin: MorningCheckinStateService
    workout_library_sync_state: WorkoutLibrarySyncStateService
    canonical_coverage: ProviderCoverageReader
    recent_logs: RecentLogEntriesService
    diagnostic_capture: DiagnosticCapture
    canonical_backfill: CanonicalBackfillStatusReader | None = None
    canonical_read: CanonicalReadStatusReader | None = None
    activity_rows: ActivityRowAndSummaryReader | None = None
    observations: ObservationReader | None = None


class DiagnosticReportService:
    """Orchestrate existing local projections into the diagnostics API shape."""

    def __init__(self, dependencies: DiagnosticReportDependencies) -> None:
        self._deps = dependencies

    def _get_value(self, db: Any, key: str) -> str | None:
        return self._deps.key_values.get(db, key)

    def _database_counts(self, db: Any) -> dict[str, int]:
        queries = {
            "messages": "SELECT COUNT(*) AS count FROM messages",
            "workout_library": "SELECT COUNT(*) AS count FROM workout_library",
            "competitions": "SELECT COUNT(*) AS count FROM competitions",
            "athlete_checkins": "SELECT COUNT(*) AS count FROM athlete_checkins",
            "activity_feedback": "SELECT COUNT(*) AS count FROM activity_feedback",
            "change_history": "SELECT COUNT(*) AS count FROM change_history",
        }
        counts = {
            name: db.execute(query).fetchone()["count"]
            for name, query in queries.items()
        }
        counts["garmin_snapshot_bytes"] = self._garmin_snapshot_bytes(db)
        return counts

    @staticmethod
    def _garmin_snapshot_bytes(db: Any) -> int:
        # octet_length uses stored byte lengths without fetching the JSON payload.
        return db.execute(
            "SELECT COALESCE(SUM(octet_length(value)), 0) AS count "
            "FROM kv WHERE key = 'garmin_snapshot'"
        ).fetchone()["count"]

    def clear(self) -> dict[str, Any]:
        """Clear the captured technical diagnostic entries."""
        return self._deps.diagnostic_capture.clear()

    @staticmethod
    def _section(name: str, build: Callable[[], Any]) -> Any:
        """Build one report section; a failing one must not break the endpoint."""
        try:
            return build()
        except Exception as exc:  # noqa: BLE001 - one bad row must not hide the report.
            LOGGER.warning(
                "Diagnostics section unavailable",
                extra={
                    "event": "diagnostics_section_unavailable",
                    "context": {"section": name, "error_type": type(exc).__name__},
                },
            )
            return {"status": "unavailable"}

    @staticmethod
    def _schema_version(db: Any) -> int:
        return int(db.execute("PRAGMA user_version").fetchone()["user_version"])

    def report(self) -> dict[str, Any]:
        deps = self._deps
        section = self._section
        diagnostic_capture_entries = deps.diagnostic_capture.entries()
        diagnostic_capture_status = deps.diagnostic_capture.status()
        # Reading the rotated log files must not hold the WAL snapshot open.
        log_entries = deps.recent_logs.report_entries()
        # The report only reads, so it takes one WAL snapshot instead of the writer.
        with deps.database_manager.read_snapshot() as db:
            garmin_status = section(
                ProviderId.GARMIN.value, deps.garmin_projection.public_state
            )

            def configuration() -> dict[str, Any]:
                return {
                    "openai_configured": bool(deps.config.openai_api_key),
                    # Only whether the endpoint differs from the default, never the URL.
                    "openai_base_url_custom": deps.config.openai_base_url
                    != DEFAULT_OPENAI_BASE_URL,
                    "intervals_configured": bool(deps.config.intervals_api_key),
                    "garmin_library_available": deps.garmin_client_factory.available(),
                    "garmin_configured": garmin_status.get("configured"),
                    "garmin_fixture_configured": deps.garmin_fixture_loader.path()
                    is not None,
                    "model": deps.settings.selected_model(),
                    "thinking_level": deps.settings.selected_thinking_level(),
                    "available_models": [
                        option["id"]
                        for option in deps.settings.available_model_options()
                    ],
                }

            def sync() -> dict[str, Any]:
                snapshot = deps.sync_state.latest_snapshot()
                return {
                    "last_success": self._get_value(db, "last_sync_at"),
                    "last_error": deps.redactor.redact_text(
                        self._get_value(db, "last_sync_error") or ""
                    )
                    or None,
                    "snapshot_counts": {
                        "activities": activity_count(deps.activity_rows, db),
                        "wellness": wellness_day_count(
                            deps.observations,
                            db,
                            date.fromisoformat(deps.utc_now()[:10]),
                        ),
                        "calendar_events": len(snapshot.get("upcoming_calendar", []))
                        if snapshot
                        else 0,
                    },
                }

            def provider_freshness() -> Any:
                return deps.provider_freshness.current(
                    profile=deps.profile.get(),
                    garmin_has_core_error=bool(
                        deps.garmin_sync_state.core_error_entries()
                    ),
                    garmin_tokenstore_exists=garmin_tokens_connected(
                        lambda key: deps.key_values.get(db, key),
                        deps.config.garmin_tokenstore,
                    ),
                    read_only=True,
                )

            def external_calendar() -> dict[str, Any]:
                return {
                    "configured": bool(deps.config.calendar_ical_url),
                    "last_sync_at": self._get_value(
                        db, "last_external_calendar_sync_at"
                    ),
                    "last_error": deps.redactor.redact_text(
                        self._get_value(db, "last_external_calendar_sync_error") or ""
                    )
                    or None,
                    "running": deps.external_calendar_sync.running(),
                    "events": len(deps.external_calendar_reader.list_events()),
                }

            def database() -> dict[str, Any]:
                return {
                    "schema_version": self._schema_version(db),
                    **self._database_counts(db),
                    "workout_library_state": deps.workout_library_sync_state.summary(),
                    "external_calendar_events": len(
                        deps.external_calendar_reader.list_events()
                    ),
                }

            key_values = deps.key_values
            return {
                "generated_at": deps.utc_now(),
                "app": {"name": deps.app_name, "version": deps.app_version},
                "runtime": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "process_memory": process_memory(),
                },
                "configuration": section("configuration", configuration),
                "openai": section(
                    "openai", lambda: deps.provider_state.summary("openai")
                ),
                "coach_commands": section("coach_commands", deps.coach_history.history),
                "sync": section("sync", sync),
                ProviderId.GARMIN.value: garmin_status,
                "provider_freshness": section("provider_freshness", provider_freshness),
                "external_calendar": section("external_calendar", external_calendar),
                "morning_checkin": section(
                    "morning_checkin", deps.morning_checkin.state
                ),
                "database": section("database", database),
                ProviderId.WAHOO.value: section(
                    ProviderId.WAHOO.value,
                    lambda: summarize_wahoo(
                        key_values,
                        db,
                        deps.config,
                        deps.redactor.redact_text,
                        datetime.fromisoformat(deps.utc_now()),
                    ),
                ),
                "plan_sync": section("plan_sync", lambda: summarize_plan_sync(db)),
                "canonical_coverage": summarize_canonical_coverage(
                    deps.canonical_coverage, db
                ),
                "canonical_backfill": summarize_canonical_backfill(
                    deps.canonical_backfill, db
                ),
                "canonical_read": summarize_canonical_read(deps.canonical_read, db),
                "canonical_session_conflicts": section(
                    "canonical_session_conflicts",
                    lambda: summarize_session_conflicts(db),
                ),
                "canonical_provider_composition": section(
                    "canonical_provider_composition",
                    lambda: summarize_provider_composition(db),
                ),
                "local_load": section(
                    "local_load", lambda: summarize_local_load(key_values, db)
                ),
                "rating_backfill": section(
                    "rating_backfill",
                    lambda: summarize_rating_backfill(
                        key_values, db, deps.config.sync_history_earliest_date
                    ),
                ),
                "stream_backfill": section(
                    "stream_backfill",
                    lambda: summarize_stream_backfill(
                        key_values, db, deps.config.sync_history_earliest_date
                    ),
                ),
                "session_metrics": section(
                    "session_metrics",
                    lambda: summarize_session_metrics(key_values, db),
                ),
                "activity_weather": section(
                    "activity_weather",
                    lambda: summarize_activity_weather(key_values, db),
                ),
                "activity_routes": section(
                    "activity_routes",
                    lambda: summarize_activity_routes(key_values, db),
                ),
                "session_analysis": section(
                    "session_analysis",
                    lambda: summarize_session_analysis(key_values, db),
                ),
                "session_focus_backfill": section(
                    "session_focus_backfill",
                    lambda: summarize_session_focus_backfill(key_values, db),
                ),
                "profile_weekly_plan_removal": section(
                    "profile_weekly_plan_removal",
                    lambda: summarize_profile_weekly_plan_removal(key_values, db),
                ),
                "logs": log_entries,
                "debug_capture": {
                    **diagnostic_capture_status,
                    "entries": diagnostic_capture_entries,
                },
                "note": (
                    "Die Diagnose enthält technische Anfrageformen, Provider-Metadaten und "
                    "Fehlerdetails. Anfragen an Garmin, Wahoo, Intervals.icu und weitere "
                    "Dienste sowie alle Antworten werden nur als Form gespeichert "
                    "(Feldnamen, Typen, Längen), nie mit Werten. Anfragen an OpenAI können "
                    "Dialog- und Trainingskontext des Coaches enthalten. Zugangsdaten, "
                    "Schlüssel, Tokens, Sitzungsdaten und OpenAI-Fehlertexte werden vor dem "
                    "Speichern entfernt. Binäre Inhalte werden ausgelassen; Einträge älter "
                    "als 7 Tage entfallen; Größenlimits und Kürzungen sind ausgewiesen."
                ),
            }
