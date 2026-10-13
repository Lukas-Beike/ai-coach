"""Read orchestration for the date-indexed daily planning context."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend.performance.canonical_inputs import resolve_reader
from backend.performance.daily_health import garmin_daily_health_by_date
from backend.performance.planning_recovery import planning_recovery_view
from backend.planning.context import build_daily_planning_context
from backend.runtime.ports import ObservationReader
from backend.weather.history import decode_history

# The Garmin snapshot is still read for the values without a canonical form: the
# morning body battery and the daily activity totals (steps, floors, calories).
_GARMIN_SNAPSHOT_KEY = "garmin_snapshot"
# Matches the shortest wellness history the compact snapshot keeps.
RECOVERY_WINDOW_DAYS = 42
_MORNING_BATTERY_HISTORY_KEY = "morning_body_battery_history"


def _decode_garmin_snapshot(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except TypeError, ValueError, RecursionError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


class DailyPlanningContextService:
    """Load local read signals through the active transaction and project them."""

    def __init__(
        self,
        database_manager: Any,
        key_value_repository: Any,
        checkin_service: Any,
        external_calendar_reader: Any,
        morning_body_battery_service: Any,
        activity_feedback_service: Any,
        today: Callable[[], date],
        calendar_window_days: int,
        observation_reader: Callable[[], ObservationReader],
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._checkin_service = checkin_service
        self._external_calendar_reader = external_calendar_reader
        self._morning_body_battery_service = morning_body_battery_service
        self._activity_feedback_service = activity_feedback_service
        self._today = today
        self._calendar_window_days = calendar_window_days
        self._observation_reader = observation_reader

    def _recovery_by_date(
        self,
        db: Any,
        today: date,
        wellness_rows: list[Any],
        garmin: dict[str, Any],
        history: Any,
    ) -> dict[str, dict[str, Any]]:
        """Recovery view of the trailing window ending on the athlete's local date.

        Sleep, HRV, resting HR, readiness, CTL and ATL come from canonical
        observations. The reader is resolved once, inside the caller's transaction.
        """
        return planning_recovery_view(
            resolve_reader(self._observation_reader(), db),
            db,
            start=today - timedelta(days=RECOVERY_WINDOW_DAYS),
            end=today,
            wellness_rows=wellness_rows,
            morning_battery_history=history,
            morning_body_battery=self._morning_body_battery_service.current(garmin),
        )

    def build(
        self,
        snapshot: Any = None,
        planned: Any = None,
        weather: Any = None,
        checkins: Any = None,
        calendar_events: Any = None,
    ) -> list[dict[str, Any]]:
        """Build a daily context from explicit inputs and bounded local reads."""
        today = self._today()
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        planned = planned if isinstance(planned, list) else []
        checkins = (
            checkins if isinstance(checkins, list) else self._checkin_service.list(30)
        )
        calendar_events = (
            calendar_events
            if isinstance(calendar_events, list)
            else self._external_calendar_reader.list_events(training_relevant_only=True)
        )
        weather_days = (
            weather.get("days")
            if isinstance(weather, dict) and isinstance(weather.get("days"), list)
            else []
        )

        # Form (TSB) has no canonical observation and is the only value read from them.
        wellness_rows = (
            snapshot.get("recent_wellness")
            if isinstance(snapshot.get("recent_wellness"), list)
            else []
        )
        with self._database_manager.unit_of_work() as db:
            garmin = _decode_garmin_snapshot(
                self._key_value_repository.get(db, _GARMIN_SNAPSHOT_KEY)
            )
            morning_battery_history = decode_history(
                self._key_value_repository.get(db, _MORNING_BATTERY_HISTORY_KEY)
            )
            recovery_by_date = self._recovery_by_date(
                db, today, wellness_rows, garmin, morning_battery_history
            )
        health_by_date = garmin_daily_health_by_date(garmin)

        return build_daily_planning_context(
            planned=planned,
            checkins=checkins,
            calendar_events=calendar_events,
            weather_days=weather_days,
            recovery_by_date=recovery_by_date,
            health_by_date=health_by_date,
            activity_feedback=self._activity_feedback_service.list(500),
            today=today,
            calendar_window_days=self._calendar_window_days,
        )
