"""Read orchestration for the date-indexed daily planning context."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.performance.canonical_inputs import resolve_reader
from backend.performance.canonical_recovery import read_daily_recovery
from backend.performance.daily_health import garmin_daily_health_by_date
from backend.performance.planning_recovery import (
    planning_recovery_by_date,
    with_canonical_recovery,
)
from backend.planning.context import build_daily_planning_context
from backend.weather.history import decode_history

_GARMIN_SNAPSHOT_KEY = "garmin_snapshot"
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
        canonical_reader: Callable[[], Any] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._checkin_service = checkin_service
        self._external_calendar_reader = external_calendar_reader
        self._morning_body_battery_service = morning_body_battery_service
        self._activity_feedback_service = activity_feedback_service
        self._today = today
        self._calendar_window_days = calendar_window_days
        self._canonical_reader = canonical_reader

    def _recovery_by_date(
        self, db: Any, wellness_rows: list[Any], garmin: dict[str, Any], history: Any
    ) -> dict[str, dict[str, Any]]:
        """Legacy recovery view, with switched values taken from canonical reads.

        Without a canonical reader the legacy view is returned unchanged. The reader
        is resolved once, inside the caller's transaction.
        """
        recovery_by_date = planning_recovery_by_date(
            wellness_rows,
            garmin,
            history,
            self._morning_body_battery_service.current(garmin),
        )
        if self._canonical_reader is None or not recovery_by_date:
            return recovery_by_date
        days = sorted(recovery_by_date)
        reader = resolve_reader(self._canonical_reader(), db)
        canonical = read_daily_recovery(
            reader,
            db,
            start=date.fromisoformat(days[0]),
            end=date.fromisoformat(days[-1]),
        )
        return with_canonical_recovery(recovery_by_date, canonical)

    def build(
        self,
        snapshot: Any = None,
        planned: Any = None,
        weather: Any = None,
        checkins: Any = None,
        calendar_events: Any = None,
    ) -> list[dict[str, Any]]:
        """Build a daily context from explicit inputs and bounded local reads."""
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
                db, wellness_rows, garmin, morning_battery_history
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
            today=self._today(),
            calendar_window_days=self._calendar_window_days,
        )
