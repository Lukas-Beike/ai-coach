"""Privacy-safe projection of the application's diagnostic report."""

from __future__ import annotations

import platform
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.athlete.profile import ProfileService
from backend.calendar.external import ExternalCalendarReader
from backend.coach.morning import MorningCheckinStateService
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.diagnostics.history import CoachDiagnosticHistoryService
from backend.diagnostics.logs import RecentLogEntriesService
from backend.observability import DiagnosticCapture, Redactor
from backend.providers.garmin import GarminClientFactory
from backend.providers.state import ProviderStateService
from backend.settings import SettingsService
from backend.sync.external_calendar import ExternalCalendarSyncService
from backend.sync.freshness import ProviderFreshnessService
from backend.sync.garmin import GarminFixtureLoader, GarminSyncStateService
from backend.sync.garmin_projection_service import GarminProjectionService
from backend.sync.library import WorkoutLibrarySyncStateService
from backend.sync.state import SyncStateRepository


@dataclass(frozen=True)
class DiagnosticReportDependencies:
    """Concrete application owners required to compose a diagnostic report."""

    database_manager: DatabaseManager
    db_lock: Any
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
    recent_logs: RecentLogEntriesService
    diagnostic_capture: DiagnosticCapture


class DiagnosticReportService:
    """Orchestrate existing local projections into the diagnostics API shape."""

    def __init__(self, dependencies: DiagnosticReportDependencies) -> None:
        self._deps = dependencies

    def _get_value(self, key: str) -> str | None:
        with self._deps.db_lock, self._deps.database_manager.unit_of_work() as db:
            return self._deps.key_values.get(db, key)

    def _database_counts(self) -> dict[str, int]:
        queries = {
            "messages": "SELECT COUNT(*) AS count FROM messages",
            "workout_library": "SELECT COUNT(*) AS count FROM workout_library",
            "competitions": "SELECT COUNT(*) AS count FROM competitions",
            "athlete_checkins": "SELECT COUNT(*) AS count FROM athlete_checkins",
            "activity_feedback": "SELECT COUNT(*) AS count FROM activity_feedback",
        }
        with self._deps.db_lock, self._deps.database_manager.unit_of_work() as db:
            return {
                name: db.execute(query).fetchone()["count"]
                for name, query in queries.items()
            }

    def report(self) -> dict[str, Any]:
        deps = self._deps
        snapshot = deps.sync_state.latest_snapshot()
        garmin_status = deps.garmin_projection.public_state()
        database_counts = self._database_counts()
        return {
            "generated_at": deps.utc_now(),
            "app": {"name": deps.app_name, "version": deps.app_version},
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "configuration": {
                "openai_configured": bool(deps.config.openai_api_key),
                "gemini_configured": bool(deps.config.gemini_api_key),
                "ai_provider": deps.settings.selected_ai_provider(),
                "intervals_configured": bool(deps.config.intervals_api_key),
                "garmin_library_available": deps.garmin_client_factory.available(),
                "garmin_configured": garmin_status["configured"],
                "garmin_fixture_configured": deps.garmin_fixture_loader.path() is not None,
                "model": deps.settings.selected_model(),
                "thinking_level": deps.settings.selected_thinking_level(),
                "available_models": [
                    option["id"] for option in deps.settings.available_model_options()
                ],
            },
            "openai": deps.provider_state.summary("openai"),
            "gemini": deps.provider_state.summary("gemini"),
            "coach_commands": deps.coach_history.history(),
            "sync": {
                "last_success": self._get_value("last_sync_at"),
                "last_error": deps.redactor.redact_text(
                    self._get_value("last_sync_error") or ""
                ) or None,
                "running": self._get_value("sync_running") == "1",
                "snapshot_counts": {
                    "activities": len(snapshot.get("recent_activities", [])) if snapshot else 0,
                    "wellness": len(snapshot.get("recent_wellness", [])) if snapshot else 0,
                    "calendar_events": len(snapshot.get("upcoming_calendar", [])) if snapshot else 0,
                },
            },
            "performance_refresh": {
                "last_refresh": self._get_value("last_performance_refresh_at"),
                "last_error": deps.redactor.redact_text(
                    self._get_value("last_performance_error") or ""
                ) or None,
                "running": self._get_value("performance_refresh_running") == "1",
            },
            "garmin": garmin_status,
            "provider_freshness": deps.provider_freshness.current(
                profile=deps.profile.get(),
                garmin_has_core_error=bool(deps.garmin_sync_state.core_error_entries()),
                garmin_tokenstore_exists=Path(deps.config.garmin_tokenstore).exists(),
            ),
            "external_calendar": {
                "configured": bool(deps.config.calendar_ical_url),
                "last_sync_at": self._get_value("last_external_calendar_sync_at"),
                "last_error": deps.redactor.redact_text(
                    self._get_value("last_external_calendar_sync_error") or ""
                ) or None,
                "running": deps.external_calendar_sync.running(),
                "events": len(deps.external_calendar_reader.list_events()),
            },
            "morning_checkin": deps.morning_checkin.state(),
            "database": {
                **database_counts,
                "workout_library_state": deps.workout_library_sync_state.summary(),
                "external_calendar_events": len(deps.external_calendar_reader.list_events()),
            },
            "logs": deps.recent_logs.list(),
            "debug_capture": {
                **deps.diagnostic_capture.status(),
                "entries": deps.diagnostic_capture.entries(),
            },
            "note": (
                "Zugangsdaten, Tokens, Rohantworten und Athleteninhalte sind ausgeschlossen; "
                "die optionale Diagnoseaufzeichnung speichert nur technische Antwortformen "
                "und Metadaten."
            ),
        }
