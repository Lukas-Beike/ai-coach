"""Local JSON privacy export projection."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.activities.feedback import ActivityFeedbackService
from backend.athlete.checkins import CheckinService
from backend.athlete.profile import ProfileService
from backend.calendar import public_events as public_event_calendar
from backend.calendar.external import ExternalCalendarReader
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.planning import season as planning_season
from backend.planning.adaptive_preview_service import AdaptiveReplanPreviewService
from backend.planning.competition_service import CompetitionService
from backend.planning.library_service import WorkoutLibraryService
from backend.planning.training_plans import TrainingPlanService
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
