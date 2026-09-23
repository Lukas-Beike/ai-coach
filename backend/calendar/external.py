"""Read-only queries and state projection for an external iCalendar feed."""

from collections.abc import Callable
from datetime import date
from typing import Any


def list_events(
    db: Any,
    *,
    today: date,
    limit: Any = 300,
    training_relevant_only: bool = False,
) -> list[dict[str, Any]]:
    relevance_filter = " AND training_relevant = 1" if training_relevant_only else ""
    rows = db.execute(
        "SELECT id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, "
        "training_relevant, no_intensity, short_only, updated_at "
        f"FROM external_calendar_events WHERE end_local > ?{relevance_filter} "
        "ORDER BY start_local LIMIT ?",
        (today.isoformat() + "T00:00:00", max(1, min(int(limit), 1000))),
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
