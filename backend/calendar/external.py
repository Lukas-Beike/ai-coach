"""Read-only queries and state projection for an external iCalendar feed."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

_LOCAL_MIDNIGHT = "T00:00:00"


def _event_query_parts(db: Any, training_relevant_only: bool) -> tuple[str, str]:
    # [NO_TRAINING] deliberately sets training_relevant=0, but remains a
    # blocking event for callers that otherwise request only relevant events.
    columns = {
        str(row["name"])
        for row in db.execute("PRAGMA table_info(external_calendar_events)")
    }
    no_training_column = "no_training" in columns
    no_training_projection = "no_training, " if no_training_column else ""
    marker_filter = (
        " OR no_training = 1 OR no_intensity = 1 OR short_only = 1"
        if no_training_column
        else " OR no_intensity = 1 OR short_only = 1"
    )
    relevance_filter = (
        " AND (training_relevant = 1"
        + marker_filter
        + " OR instr(upper(name), '[NO_TRAINING]') > 0)"
        if training_relevant_only
        else ""
    )
    select_columns = (
        "id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, "
        f"training_relevant, {no_training_projection}no_intensity, short_only, updated_at"
    )
    return select_columns, relevance_filter


def list_events(
    db: Any,
    *,
    today: date,
    limit: Any = 300,
    training_relevant_only: bool = False,
) -> list[dict[str, Any]]:
    select_columns, relevance_filter = _event_query_parts(db, training_relevant_only)
    rows = db.execute(
        f"SELECT {select_columns} FROM external_calendar_events "
        f"WHERE end_local > ?{relevance_filter} ORDER BY start_local LIMIT ?",
        (today.isoformat() + _LOCAL_MIDNIGHT, max(1, min(int(limit), 1000))),
    ).fetchall()
    return [dict(row) for row in rows]


def list_events_in_window(
    db: Any,
    *,
    today: date,
    window_days: int,
    training_relevant_only: bool = False,
) -> list[dict[str, Any]]:
    """Return every event overlapping the bounded local window, without a row cap."""
    select_columns, relevance_filter = _event_query_parts(db, training_relevant_only)
    window_start = today - timedelta(days=window_days)
    window_end = today + timedelta(days=window_days + 1)
    rows = db.execute(
        f"SELECT {select_columns} FROM external_calendar_events "
        f"WHERE end_local > ? AND start_local < ?{relevance_filter} ORDER BY start_local",
        (
            window_start.isoformat() + _LOCAL_MIDNIGHT,
            window_end.isoformat() + _LOCAL_MIDNIGHT,
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def state(
    db: Any,
    *,
    configured: bool,
    running: bool,
    today: date,
    window_days: int,
) -> dict[str, Any]:
    last_sync_row = db.execute(
        "SELECT value FROM kv WHERE key = ?", ("last_external_calendar_sync_at",)
    ).fetchone()
    last_error_row = db.execute(
        "SELECT value FROM kv WHERE key = ?", ("last_external_calendar_sync_error",)
    ).fetchone()
    last_error = last_error_row["value"] if last_error_row else None
    return {
        "configured": configured,
        "provider": "iCalendar",
        "read_only": True,
        "running": running,
        "last_sync_at": last_sync_row["value"] if last_sync_row else None,
        "last_error": last_error or None,
        "events": list_events(db, today=today),
        "window_days": window_days,
    }


class ExternalCalendarReader:
    """Own external-calendar read transactions for application callers."""

    def __init__(self, database_manager: Any, today: Callable[[], date]) -> None:
        self._database_manager = database_manager
        self._today = today

    def list_events(
        self, limit: Any = 300, training_relevant_only: bool = False
    ) -> list[dict[str, Any]]:
        with self._database_manager.unit_of_work() as db:
            return list_events(
                db,
                today=self._today(),
                limit=limit,
                training_relevant_only=training_relevant_only,
            )

    def list_events_in_window(
        self, window_days: int, training_relevant_only: bool = False
    ) -> list[dict[str, Any]]:
        with self._database_manager.unit_of_work() as db:
            return list_events_in_window(
                db,
                today=self._today(),
                window_days=window_days,
                training_relevant_only=training_relevant_only,
            )

    def state(
        self, *, configured: bool, running: bool, window_days: int
    ) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            return state(
                db,
                configured=configured,
                running=running,
                today=self._today(),
                window_days=window_days,
            )
