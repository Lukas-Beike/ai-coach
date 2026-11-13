"""Build the bounded public bootstrap response from local application state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.canonical.public_metrics import neutral_calendar_state
from backend.canonical.vocabulary import ProviderId
from backend.coach.receipt_reads import monthly_turn_usage
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.provider_credentials import WAHOO_TOKENS_KEY, garmin_tokens_connected
from backend.sync.jobs import last_finished_at
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
from backend.sync.wahoo_connection import connection_status


@dataclass(frozen=True)
class PublicBootstrapDependencies:
    database_manager: Callable[[], DatabaseManager]
    database_lock: Any
    config: Config
    app_name: str
    app_version: str
    key_values: Any
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
    local_calendar_events: Callable[..., Any]
    planning_state: Callable[..., Any]
    adaptive_replan_preview_service: Callable[[], Any]
    external_calendar_sync_service: Callable[[], Any]
    external_calendar_window_days: int
    garmin_projection_service: Callable[[], Any]
    diagnostic_capture: Any
    intervals_public_state: Callable[..., Any]
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
    provider_credentials: Callable[[], Any] | None = None
    # Stale-threshold warning for the status strip; null in the bootstrap when none.
    threshold_warnings: Callable[[], dict[str, Any] | None] = lambda: None
    # Answers and tokens per model of a month's Coach turns, read in the transaction.
    coach_usage_reader: Callable[[Any, Any, str], dict[str, Any]] = monthly_turn_usage


class PublicBootstrapService:
    """Own the complete, bounded and local-only browser bootstrap projection."""

    def __init__(self, dependencies: PublicBootstrapDependencies) -> None:
        self._dependencies = dependencies

    def read(self) -> dict[str, Any]:
        deps = self._dependencies
        # One read-only WAL snapshot serves every read below, including nested
        # service reads, so the projection is consistent without the writer or
        # the shared database lock. A hidden write fails on the query-only
        # connection instead of racing.
        with deps.database_manager().read_snapshot() as db:
            local_planned = deps.planned_unit_service().list(250, push_state=True)
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
                garmin_tokenstore_exists=garmin_tokens_connected(
                    lambda key: deps.key_values.get_in_transaction(db, key),
                    deps.config.garmin_tokenstore,
                ),
                read_only=True,
            )
            jobs = deps.sync_job_queue_service().list()
            state_version_values = deps.state_version_service().versions()
            provider = deps.settings.selected_provider()
            provider_state = deps.provider_state_service()
            summaries = {
                name: provider_state.summary(name) for name in ("openai", "anthropic")
            }
            intervals_job_ok_at, intervals_job_failed_at = last_finished_at(
                db, ProviderId.INTERVALS.value
            )
            state = {
                "state_versions": state_version_values,
                "app": {"name": deps.app_name, "version": deps.app_version},
                "messages": deps.coach_message_service().list(limit=100),
                "messages_next_cursor": None,
                "library": [],
                "activities": [],
                "planned": local_planned,
                "calendar": deps.local_calendar_events(
                    local_planned, competitions, relevant_external
                ),
                "planning_compliance": [],
                "weather": {},
                "profile": profile,
                "competitions": competitions,
                "checkins": [],
                "local_feedback": {
                    "today": None,
                    "recent": [],
                    "scope": "Only athlete-entered subjective feedback and constraints; wearable/provider values remain in their source sections.",
                },
                "activity_feedback": {
                    "recent": [],
                    "scope": "Only athlete-entered notes, session RPE, deviation reasons and the session purpose marking about completed activities; a marking wins over the provider event type and the race hint; this feedback is separate from daily check-ins and provider values.",
                },
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
                ProviderId.GARMIN.value: deps.garmin_projection_service().public_state(),
                "diagnostic_capture": deps.diagnostic_capture.status(),
                ProviderId.INTERVALS.value: deps.intervals_public_state(
                    configured=bool(deps.config.intervals_api_key),
                    running=deps.workout_library_sync_running(),
                    last_library_sync_at=_library_activity_at(deps, db),
                    last_library_sync_error=deps.key_values.get_in_transaction(
                        db, "last_library_sync_error"
                    )
                    or None,
                    library_sync_state=deps.workout_library_sync_state_service().summary(),
                    last_job_ok_at=intervals_job_ok_at,
                    last_job_failed_at=intervals_job_failed_at,
                ),
                "provider_freshness": freshness,
                "provider_ids": {
                    member.name.lower(): member.value for member in ProviderId
                },
                "provider_labels": {
                    descriptor.provider_id: descriptor.label
                    for descriptor in DEFAULT_PROVIDER_REGISTRY.all()
                },
                "garmin_sync": {
                    "running": deps.garmin_sync_service().running(),
                    "status": deps.key_values.get_in_transaction(
                        db, "garmin_sync_status"
                    )
                    or None,
                },
                "provider_resync": {
                    provider_id: deps.full_provider_resync_service().state(
                        provider_id, db
                    )
                    for _, provider_id in DEFAULT_PROVIDER_REGISTRY.full_resync_routes()
                },
                "sync": deps.sync_public_state_service().browser_state(
                    freshness=freshness,
                    jobs=jobs,
                    state_versions=state_version_values,
                ),
                "library_sync": {
                    "last_sync_at": _library_activity_at(deps, db),
                    "last_error": deps.key_values.get_in_transaction(
                        db, "last_library_sync_error"
                    )
                    or None,
                    "state": deps.workout_library_sync_state_service().summary(),
                },
                "sync_settings": {
                    **{
                        f"{provider_id}_days": deps.sync_state_repository().sync_period(
                            provider_id, deps.sync_period_defaults, deps.all_sync_days
                        )
                        for provider_id in DEFAULT_PROVIDER_REGISTRY.sync_period_defaults()
                    },
                },
                "calendar_display": deps.settings.calendar_display_settings(),
                "morning_checkin": deps.morning_checkin_state_service().state(),
                "coach_quick_actions": deps.coach_quick_actions_service().state(),
                "model": {
                    "selected": deps.settings.selected_model(),
                    "provider": provider,
                    "options": deps.settings.available_model_options(),
                },
                "service_tier": deps.settings.service_tier_state(),
                "thinking_level": {
                    "selected": deps.settings.selected_thinking_level(),
                    "options": deps.settings.available_thinking_level_options(),
                },
                "configured": {
                    "openai": bool(deps.config.openai_api_key),
                    "anthropic": bool(deps.config.anthropic_api_key),
                    # Voice: a local transcription server needs no OpenAI key.
                    "transcription": bool(
                        deps.config.transcription_model
                        if deps.config.transcription_base_url
                        else deps.config.openai_api_key
                    ),
                    # The selected model's provider has its key.
                    "coach": deps.settings.coach_ready(),
                    ProviderId.INTERVALS.value: bool(deps.config.intervals_api_key),
                    "weather": bool(
                        deps.profile_service().get().get("weather_location")
                    ),
                    "external_calendar": bool(deps.config.calendar_ical_url),
                },
                ProviderId.WAHOO.value: connection_status(
                    deps.config,
                    deps.key_values.get_in_transaction(db, WAHOO_TOKENS_KEY),
                ),
                "credentials": (
                    deps.provider_credentials().status()
                    if deps.provider_credentials is not None
                    else None
                ),
                "usage": summaries[provider],
                "usage_month": deps.coach_usage_reader(
                    db, deps.local_date(), profile.get("timezone")
                ),
                "provider_status": {
                    name: summary.get("status") or {}
                    for name, summary in summaries.items()
                },
            }
            # Always present, so a cleared warning also clears on a client that merges bootstraps.
            state["threshold_warnings"] = deps.threshold_warnings() or None
            return neutral_calendar_state(state)


def _library_activity_at(deps: Any, db: Any) -> str | None:
    return deps.key_values.get_in_transaction(db, "last_library_push_at") or None
