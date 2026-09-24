"""Local JSON privacy export projection."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.activities.feedback import ActivityFeedbackService
from backend.athlete.checkins import CheckinService
from backend.athlete.profile import DEFAULT_PROFILE, ProfileService
from backend.calendar import public_events as public_event_calendar
from backend.calendar.external import ExternalCalendarReader
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.planning import season as planning_season
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.competition_service import CompetitionService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.revision import PlanningRevisionService
from backend.planning.training_plans import TrainingPlanService
from backend.providers.openai import OpenAIResponsesClient
from backend.runtime.maintenance import MaintenanceGate
from backend.weather import cache as weather_cache


@dataclass(frozen=True)
class PrivacyDataExportDependencies:
    database_manager: DatabaseManager
    database_lock: AbstractContextManager[Any]
    key_value_repository: KeyValueRepository
    profile_service: ProfileService
    workout_library_service: WorkoutLibraryService
    competition_service: CompetitionService
    training_plan_service: TrainingPlanService
    checkin_service: CheckinService
    activity_feedback_service: ActivityFeedbackService
    adaptive_preview_service: AdaptiveReplanPreviewService
    external_calendar_reader: ExternalCalendarReader
    local_now: Callable[[], datetime]
    utc_now: Callable[[], str]


class PrivacyDataExportService:
    """Project durable local athlete data into the privacy JSON contract."""

    def __init__(self, dependencies: PrivacyDataExportDependencies):
        self._dependencies = dependencies

    def _stored_json(self, key: str) -> Any:
        dependencies = self._dependencies
        with dependencies.database_lock, dependencies.database_manager.unit_of_work() as db:
            value = dependencies.key_value_repository.get(db, key)
        try:
            return json.loads(value or "{}")
        except (TypeError, ValueError):
            return {}

    def export(self) -> dict[str, Any]:
        dependencies = self._dependencies
        with dependencies.database_lock, dependencies.database_manager.unit_of_work() as db:
            messages = [
                dict(row)
                for row in db.execute(
                    "SELECT role, content, attachments, created_at FROM messages ORDER BY id"
                ).fetchall()
            ]
            snapshots = [
                json.loads(row["payload"])
                for row in db.execute("SELECT payload FROM snapshots ORDER BY id").fetchall()
            ]
            library = dependencies.workout_library_service.list(include_archived=True)
            competitions = dependencies.competition_service.list()
            tombstones = [
                dict(row)
                for row in db.execute(
                    "SELECT intervals_event_id, external_id, created_at "
                    "FROM competition_sync_tombstones ORDER BY created_at"
                ).fetchall()
            ]
            adjustments = [
                dict(row)
                for row in db.execute(
                    "SELECT id, payload, status, created_at, applied_at "
                    "FROM plan_adjustments ORDER BY created_at"
                ).fetchall()
            ]
            public_calendar = public_event_calendar.state(db)
            kv_rows = db.execute("SELECT key, value FROM kv ORDER BY key").fetchall()

        application_state: dict[str, Any] = {}
        excluded_state = {"profile", "garmin_snapshot", weather_cache.CACHE_KEY}
        for row in kv_rows:
            key = str(row["key"])
            if key in excluded_state or key.endswith(("_running", "_status")):
                continue
            value = row["value"]
            try:
                application_state[key] = json.loads(value)
            except (TypeError, ValueError):
                application_state[key] = value

        garmin_data = self._stored_json("garmin_snapshot")
        weather_data = self._stored_json(weather_cache.CACHE_KEY)
        adaptive_preview = dependencies.adaptive_preview_service
        return {
            "exported_at": dependencies.utc_now(),
            "profile": dependencies.profile_service.get(),
            "application_state": application_state,
            "competitions": competitions,
            "competition_sync_tombstones": tombstones,
            "messages": messages,
            "snapshots": snapshots,
            "workout_library": library,
            "training_plans": dependencies.training_plan_service.list(),
            "plan_adjustments": adjustments,
            "local_feedback": dependencies.checkin_service.context(),
            "activity_feedback": dependencies.activity_feedback_service.context(),
            "planning": planning_season.planning_state(
                dependencies.competition_service.list(),
                dependencies.local_now().date(),
                adaptive_preview.latest_preview(),
                adaptive_preview.status(),
            ),
            "external_calendar": dependencies.external_calendar_reader.list_events(),
            "public_calendar": public_calendar,
            "garmin_snapshot": garmin_data,
            "weather_cache": weather_data,
        }


PRIVACY_DELETE_CONFIRMATION_TEXT = "LOKALE DATEN LÖSCHEN"

PRIVACY_DELETE_SCOPE = (
    ("chats", "Chats, Coach-Werkzeug- und Aktionsprotokolle", ("messages", "coach_commands", "coach_plan_artifacts", "coach_action_proposals")),
    ("snapshots", "Trainings-Snapshots", ("snapshots",)),
    ("library", "Workout-Bibliothek und geplante Einheiten", ("workout_library", "planned_units")),
    ("competitions", "Wettkämpfe und Sync-Vormerkungen", ("competitions", "competition_sync_tombstones")),
    ("plans", "Trainingspläne", ("training_plans", "planning_state")),
    ("checkins", "Tages-Check-ins", ("athlete_checkins",)),
    ("feedback", "Aktivitätsfeedback", ("activity_feedback",)),
    ("adaptive", "Adaptive Plananpassungen", ("plan_adjustments",)),
    ("calendars", "Kalenderquellen, Kandidaten und lokale Kalenderereignisse", ("public_event_sources", "public_event_candidates", "external_calendar_events")),
    ("sessions", "Anmeldesitzungen", ("sessions",)),
    ("settings", "Profil, Einstellungen, Syncstatus und lokale Caches", ("kv",)),
    ("history", "Lokale Änderungshistorie", ("change_history",)),
    ("provider_status", "Bereinigter Provider-Refresh-Verlauf", ("provider_refresh_history", "sync_job_items", "sync_jobs", "provider_sync_cursors")),
)
PRIVACY_REMOTE_SCOPE = (
    "Intervals.icu-Trainings-, Kalender- und Bibliotheksdaten bleiben unverändert.",
    "Garmin-Konto und Garmin-Daten bleiben unverändert.",
    "Externe Kalenderquelle und deren Anbieter bleiben unverändert.",
)


@dataclass(frozen=True)
class PrivacyDeleteDependencies:
    database_manager: DatabaseManager
    database_lock: AbstractContextManager[Any]
    key_value_repository: KeyValueRepository
    maintenance_gate: MaintenanceGate
    planning_revision_service: PlanningRevisionService
    openai_client: OpenAIResponsesClient
    logger: logging.Logger


class PrivacyDeleteService:
    """Own the preview and maintenance-gated deletion of local user data."""

    def __init__(self, dependencies: PrivacyDeleteDependencies):
        self._dependencies = dependencies

    @staticmethod
    def _counts(db: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for category, _label, tables in PRIVACY_DELETE_SCOPE:
            counts[category] = sum(
                int(db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
                for table in tables
            )
        return counts

    def preview(self) -> dict[str, Any]:
        dependencies = self._dependencies
        with dependencies.database_lock, dependencies.database_manager.unit_of_work() as db:
            counts = self._counts(db)
        return {
            "status": "preview",
            "confirmation_text": PRIVACY_DELETE_CONFIRMATION_TEXT,
            "categories": [
                {"id": category, "label": label, "records": counts[category]}
                for category, label, _tables in PRIVACY_DELETE_SCOPE
            ],
            "remote_untouched": list(PRIVACY_REMOTE_SCOPE),
            "openai_conversation": "Eine vorhandene OpenAI-Konversation wird vor dem Löschen zum Löschen angefragt; ein Fehlschlag wird separat ausgewiesen.",
        }

    def delete(self, confirm: Any) -> dict[str, Any]:
        if confirm != PRIVACY_DELETE_CONFIRMATION_TEXT:
            raise AppError(
                400,
                "Zum Löschen muss LOKALE DATEN LÖSCHEN bestätigt werden.",
            )
        dependencies = self._dependencies
        with dependencies.maintenance_gate.restore():
            with dependencies.database_lock, dependencies.database_manager.unit_of_work() as db:
                conversation_id = dependencies.key_value_repository.get(db, "openai_conversation_id") or ""
            remote_delete_attempted = bool(conversation_id)
            remote_deleted = False
            if conversation_id:
                try:
                    remote_deleted = dependencies.openai_client.delete_conversation(conversation_id)
                except Exception:
                    dependencies.logger.warning(
                        "Remote OpenAI conversation could not be deleted",
                        extra={"event": "privacy_remote_delete_failed"},
                        exc_info=True,
                    )
            with dependencies.database_lock, dependencies.database_manager.unit_of_work() as db:
                deleted_counts = self._counts(db)
                deleted_tables = dict.fromkeys(
                    table for _category, _label, tables in PRIVACY_DELETE_SCOPE for table in tables
                )
                for table in deleted_tables:
                    db.execute(f"DELETE FROM {table}")
                db.execute("DELETE FROM kv")
                dependencies.key_value_repository.set(db, "profile", json.dumps(DEFAULT_PROFILE))
                dependencies.planning_revision_service.mark_reset_pending()
            return {
                "status": "ok",
                "local_data_deleted": True,
                "deleted_categories": deleted_counts,
                "remote_delete_attempted": remote_delete_attempted,
                "remote_conversation_deleted": remote_deleted,
                "remote_untouched": list(PRIVACY_REMOTE_SCOPE),
            }
