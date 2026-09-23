"""Project calendar and daily planning data for the public bootstrap state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.athlete.checkins import CheckinService
from backend.calendar.external import ExternalCalendarReader
from backend.planning import calendar_read_model
from backend.planning.competition_service import CompetitionService
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.sync.external_calendar import ExternalCalendarSyncService


@dataclass(frozen=True)
class PublicStateCalendarData:
    checkins: list[dict[str, Any]]
    competitions: list[dict[str, Any]]
    external_calendar: dict[str, Any]
    daily_context: list[dict[str, Any]]
    calendar_projection: dict[str, Any]


class PublicStateCalendarProjection:
    """Read calendar projections inside the caller-owned bootstrap UOW."""

    def __init__(
        self,
        checkins: CheckinService,
        competitions: CompetitionService,
        external_calendar: ExternalCalendarReader,
        external_calendar_sync: ExternalCalendarSyncService,
        daily_context: DailyPlanningContextService,
        *,
        external_calendar_configured: bool,
        external_calendar_window_days: int,
        default_workout_name: str,
        today: Callable[[], date],
    ) -> None:
        self._checkins = checkins
        self._competitions = competitions
        self._external_calendar = external_calendar
        self._external_calendar_sync = external_calendar_sync
        self._daily_context = daily_context
        self._external_calendar_configured = external_calendar_configured
        self._external_calendar_window_days = external_calendar_window_days
        self._default_workout_name = default_workout_name
        self._today = today

    def read(
        self,
        snapshot: dict[str, Any],
        canonical_planned: list[dict[str, Any]],
        local_planned: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        weather: dict[str, Any],
        calendar_window: dict[str, Any],
    ) -> PublicStateCalendarData:
        """Read and project calendar data without opening a transaction."""
        checkins = self._checkins.list(30)
        competitions = self._competitions.list()
        external_calendar = self._external_calendar.state(
            configured=self._external_calendar_configured,
            running=self._external_calendar_sync.running(),
            window_days=self._external_calendar_window_days,
        )
        daily_context = self._daily_context.build(
            snapshot,
            canonical_planned,
            weather,
            checkins,
            self._external_calendar.list_events(
                50, training_relevant_only=True
            ),
        )
        calendar_projection = calendar_read_model.project_planning_calendar(
            local_planned,
            activities,
            weather,
            competitions,
            (
                external_calendar.get("events")
                if isinstance(external_calendar, dict)
                else []
            ),
            today=self._today(),
            provider_window=calendar_window,
            default_name=self._default_workout_name,
        )
        return PublicStateCalendarData(
            checkins,
            competitions,
            external_calendar,
            daily_context,
            calendar_projection,
        )
