"""Build the bounded public bootstrap response from local application state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository


@dataclass(frozen=True)
class PublicBootstrapDependencies:
    database_manager: Callable[[], DatabaseManager]
    database_lock: Any
    config: Config
    app_name: str
    app_version: str
    key_values: KeyValueRepository
    sync_state_repository: Callable[[], Any]
    planned_unit_service: Callable[[], Any]
    competition_service: Callable[[], Any]
    external_calendar_reader: Callable[[], Any]
    profile_service: Callable[[], Any]
    provider_freshness_service: Callable[[], Any]
    garmin_sync_state_service: Callable[[], Any]
    garmin_sync_service: Callable[[], Any]
    sync_job_queue_service: Callable[[], Any]
    state_version_service: Callable[[], Any]
    coach_message_service: Callable[[], Any]
    training_plan_service: Callable[[], Any]
    local_calendar_events: Callable[..., Any]
    planning_state: Callable[..., Any]
    adaptive_replan_preview_service: Callable[[], Any]
    external_calendar_sync_service: Callable[[], Any]
    external_calendar_window_days: int
    planned_calendar_history_days: int
    planned_calendar_future_days: int
    garmin_projection_service: Callable[[], Any]
    diagnostic_capture: Any
    intervals_public_state: Callable[..., Any]
    intervals_sync_lock: Any
    workout_library_sync_running: Callable[[], bool]
    workout_library_sync_state_service: Callable[[], Any]
    full_provider_resync_service: Callable[[], Any]
    sync_public_state_service: Callable[[], Any]
    sync_period_defaults: dict[str, int]
    all_sync_days: int
    settings: Any
    local_date: Callable[[], Any]
    morning_checkin_state_service: Callable[[], Any]
    coach_quick_actions_service: Callable[[], Any]
    provider_state_service: Callable[[], Any]


class PublicBootstrapService:
    """Own the complete, bounded and local-only browser bootstrap projection."""

    def __init__(self, dependencies: PublicBootstrapDependencies) -> None:
        self._dependencies = dependencies

    def read(self) -> dict[str, Any]:
        deps = self._dependencies
        # Resolve the manager only after taking the shared lock; all reads below
        # then reuse this single unit of work, including nested service reads.
        with deps.database_lock, deps.database_manager().unit_of_work() as db:
            snapshot = deps.sync_state_repository().latest_snapshot()
            local_planned = deps.planned_unit_service().list(250)
            competitions = deps.competition_service().list(limit=100)
            relevant_external = deps.external_calendar_reader().list_events(
                250, training_relevant_only=True
            )
            profile = deps.profile_service().get()
            freshness = deps.provider_freshness_service().current(
                profile=deps.profile_service().get(),
                garmin_has_core_error=bool(
                    deps.garmin_sync_state_service().core_error_entries()
                ),
                garmin_tokenstore_exists=Path(deps.config.garmin_tokenstore).exists(),
            )
            jobs = deps.sync_job_queue_service().list()
            state_version_values = deps.state_version_service().versions()
            return {
                "schema_version": 3,
                "state_versions": state_version_values,
                "plan_revision": state_version_values.get("plan"),
                "app": {"name": deps.app_name, "version": deps.app_version},
                "skeleton": dict.fromkeys(("chat", "activities", "plan", "library", "performance", "feedback", "profile"), True),
                "messages": deps.coach_message_service().list(limit=100),
                "messages_next_cursor": None,
                "plans": deps.training_plan_service().list(limit=30),
                "library": [],
                "activities": [],
                "planned": local_planned,
                "training_calendar": local_planned,
                "calendar": deps.local_calendar_events(local_planned, competitions, relevant_external),
                "planning_view": {"source": "local", "local_count": len(local_planned), "remote_count": 0, "items": local_planned, "provider_window": {}},
                "planning_compliance": [],
                "weather": {},
                "parallel_cycling": [],
                "profile": profile,
                "competitions": competitions,
                "checkins": [],
                "local_feedback": {"today": None, "recent": [], "scope": "Only athlete-entered subjective feedback and constraints; wearable/provider values remain in their source sections."},
                "activity_feedback": {"recent": [], "scope": "Only athlete-entered notes about completed activities; this feedback is separate from daily check-ins and provider values."},
                "planning": deps.planning_state(
                    deps.competition_service().list(),
                    deps.local_date(),
                    deps.adaptive_replan_preview_service().latest_preview(),
                    deps.adaptive_replan_preview_service().status(),
                ),
                "external_calendar": deps.external_calendar_reader().state(
                    configured=bool(deps.config.calendar_ical_url),
                    running=deps.external_calendar_sync_service().running(),
                    window_days=deps.external_calendar_window_days,
                ),
                "daily_planning_context": [],
                "performance": {},
                "garmin": deps.garmin_projection_service().public_state(),
                "diagnostic_capture": deps.diagnostic_capture.status(),
                "intervals": deps.intervals_public_state(
                    configured=bool(deps.config.intervals_api_key),
                    running=deps.intervals_sync_lock.locked() or deps.workout_library_sync_running(),
                    status=deps.key_values.get(db, "sync_status") or None,
                    last_sync_at=deps.key_values.get(db, "last_sync_at"),
                    last_sync_error=deps.key_values.get(db, "last_sync_error") or None,
                    last_library_sync_at=deps.key_values.get(db, "last_library_sync_at"),
                    last_library_sync_error=deps.key_values.get(db, "last_library_sync_error") or None,
                    pagination_value=deps.key_values.get(db, "last_sync_pagination"),
                    snapshot=snapshot,
                    library_sync_state=deps.workout_library_sync_state_service().summary(),
                    today=deps.local_date(),
                    history_days=deps.planned_calendar_history_days,
                    future_days=deps.planned_calendar_future_days,
                ),
                "provider_freshness": freshness,
                "provider_states": bootstrap_provider_states(freshness),
                "garmin_sync": {
                    "running": deps.garmin_sync_service().running(),
                    "status": deps.key_values.get(db, "garmin_sync_status") or None,
                },
                "provider_resync": {
                    "intervals": deps.full_provider_resync_service().state("intervals", db),
                    "garmin": deps.full_provider_resync_service().state("garmin", db),
                },
                "sync": deps.sync_public_state_service().browser_state(
                    freshness=freshness, jobs=jobs
                ),
                "running_jobs": [job for job in jobs if job.get("status") in {"queued", "running"}],
                "library_sync": {"last_sync_at": deps.key_values.get(db, "last_library_sync_at"), "last_error": deps.key_values.get(db, "last_library_sync_error") or None, "state": deps.workout_library_sync_state_service().summary()},
                "sync_settings": {
                    "intervals_days": deps.sync_state_repository().sync_period(
                        "intervals", deps.sync_period_defaults, deps.all_sync_days
                    ),
                    "garmin_days": deps.sync_state_repository().sync_period(
                        "garmin", deps.sync_period_defaults, deps.all_sync_days
                    ),
                },
                "calendar_display": deps.settings.calendar_display_settings(),
                "competition_sync": {
                    "last_sync_at": deps.key_values.get(db, "last_competition_sync_at"), "last_error": deps.key_values.get(db, "last_competition_sync_error") or None,
                    "running": deps.key_values.get(db, "competition_sync_running") == "1", "status": deps.key_values.get(db, "competition_sync_status") or None,
                },
                "performance_refresh": {
                    "last_refresh_at": deps.key_values.get(db, "last_performance_refresh_at"), "last_error": deps.key_values.get(db, "last_performance_error") or None,
                    "running": deps.key_values.get(db, "performance_refresh_running") == "1",
                },
                "morning_checkin": deps.morning_checkin_state_service().state(),
                "coach_quick_actions": deps.coach_quick_actions_service().state(),
                "ai_provider": {"selected": deps.settings.selected_ai_provider(), "options": deps.settings.available_ai_providers()},
                "model": {"selected": deps.settings.selected_model(), "options": deps.settings.available_model_options()},
                "thinking_level": {"selected": deps.settings.selected_thinking_level(), "options": deps.settings.available_thinking_level_options()},
                "configured": {
                    "openai": bool(deps.config.openai_api_key), "gemini": bool(deps.config.gemini_api_key), "intervals": bool(deps.config.intervals_api_key),
                    "weather": bool(deps.profile_service().get().get("weather_location")), "external_calendar": bool(deps.config.calendar_ical_url),
                },
                "usage": deps.provider_state_service().summary(deps.settings.selected_ai_provider() or "openai"),
            }


def bootstrap_provider_states(freshness: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Project provider freshness into the small, stable bootstrap contract."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in freshness:
        if isinstance(item, dict) and item.get("provider"):
            grouped.setdefault(str(item["provider"]), []).append(item)
    state_map = {
        "not_configured": "not_configured",
        "syncing": "loading",
        "never_loaded": "loading",
        "fresh": "ready",
        "connected": "ready",
        "partial": "degraded",
        "stale": "stale",
        "error": "error",
    }
    result: dict[str, dict[str, Any]] = {}
    priority = {"error": 5, "stale": 4, "degraded": 3, "loading": 2, "ready": 1, "not_configured": 0}
    for provider, areas in grouped.items():
        projected = [state_map.get(str(item.get("state")), "error") for item in areas]
        status = max(projected, key=lambda value: priority[value]) if projected else "not_configured"
        result[provider] = {
            "status": status,
            "areas": {
                str(item.get("area")): {
                    "status": state_map.get(str(item.get("state")), "error"),
                    "last_success_at": item.get("last_success_at"),
                }
                for item in areas
            },
        }
    return result
