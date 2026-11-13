"""Read-only queries and state projection for an external iCalendar feed."""

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

_LOCAL_MIDNIGHT = "T00:00:00"


# Every stored event with the athlete's decision applied: an occurrence decision
# wins over a series decision (empty occurrence start), which wins over the
# description markers. A decision replaces the marker flags; without one, the
# markers name the impact, else it stays "open". The alias keeps the table name,
# so callers filter on the effective flags.
_DECIDED_EVENTS = """(
    SELECT id, uid, name, event_date, start_local, end_local, duration_minutes,
        all_day, updated_at, decision_scope, recurring,
        CASE WHEN decision IS NULL THEN training_relevant ELSE decision <> 'none' END
            AS training_relevant,
        CASE WHEN decision IS NULL THEN no_training ELSE decision = 'block' END
            AS no_training,
        CASE WHEN decision IS NULL THEN no_intensity ELSE decision = 'easy' END
            AS no_intensity,
        CASE WHEN decision IS NULL THEN short_only ELSE decision = 'short' END
            AS short_only,
        COALESCE(decision, CASE
            WHEN no_training = 1 THEN 'block'
            WHEN short_only = 1 THEN 'short'
            WHEN no_intensity = 1 THEN 'easy'
            ELSE 'open' END) AS impact
    FROM (
        SELECT e.*, COALESCE(o.impact, s.impact) AS decision,
            CASE WHEN o.impact IS NOT NULL THEN 'event'
                WHEN s.impact IS NOT NULL THEN 'series' END AS decision_scope,
            (SELECT COUNT(*) FROM external_calendar_events r WHERE r.uid = e.uid) > 1
                AS recurring
        FROM external_calendar_events e
        LEFT JOIN external_calendar_decisions o
            ON o.uid = e.uid AND o.occurrence_start = e.start_local
        LEFT JOIN external_calendar_decisions s
            ON s.uid = e.uid AND s.occurrence_start = ''
    )
) AS external_calendar_events"""

# Undecided events count for the notice from today through this many days ahead.
UNDECIDED_NOTICE_DAYS = 14


def _event_query_parts(training_relevant_only: bool) -> tuple[str, str]:
    # [NO_TRAINING] deliberately sets training_relevant=0, but remains a
    # blocking event for callers that otherwise request only relevant events.
    relevance_filter = (
        " AND (training_relevant = 1 OR no_training = 1 OR no_intensity = 1"
        " OR short_only = 1)"
        if training_relevant_only
        else ""
    )
    select_columns = (
        "id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, "
        "training_relevant, no_training, no_intensity, short_only, impact, "
        "decision_scope, recurring, updated_at"
    )
    return select_columns, relevance_filter


def list_events(
    db: Any,
    *,
    today: date,
    limit: Any = 300,
    training_relevant_only: bool = False,
) -> list[dict[str, Any]]:
    select_columns, relevance_filter = _event_query_parts(training_relevant_only)
    rows = db.execute(
        f"SELECT {select_columns} FROM {_DECIDED_EVENTS} "
        f"WHERE end_local > ?{relevance_filter} ORDER BY start_local LIMIT ?",
        (today.isoformat() + _LOCAL_MIDNIGHT, max(1, min(int(limit), 1000))),
    ).fetchall()
    return [dict(row) for row in rows]


def event_counts(db: Any, *, today: date) -> dict[str, int]:
    """Count the stored events and those not yet over, in one query."""
    row = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(end_local > ?), 0) AS upcoming "
        "FROM external_calendar_events",
        (today.isoformat() + _LOCAL_MIDNIGHT,),
    ).fetchone()
    return {"total": row["total"], "upcoming": row["upcoming"]}


def list_events_in_window(
    db: Any,
    *,
    today: date,
    window_days: int,
    training_relevant_only: bool = False,
) -> list[dict[str, Any]]:
    """Return every event overlapping the bounded local window, without a row cap."""
    select_columns, relevance_filter = _event_query_parts(training_relevant_only)
    window_start = today - timedelta(days=window_days)
    window_end = today + timedelta(days=window_days + 1)
    rows = db.execute(
        f"SELECT {select_columns} FROM {_DECIDED_EVENTS} "
        f"WHERE end_local > ? AND start_local < ?{relevance_filter} ORDER BY start_local",
        (
            window_start.isoformat() + _LOCAL_MIDNIGHT,
            window_end.isoformat() + _LOCAL_MIDNIGHT,
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def undecided_upcoming(db: Any, *, today: date) -> int:
    """Count the open events from today through the notice window."""
    row = db.execute(
        f"SELECT COUNT(*) AS count FROM {_DECIDED_EVENTS} "
        "WHERE impact = 'open' AND end_local > ? AND start_local < ?",
        (
            today.isoformat() + _LOCAL_MIDNIGHT,
            (today + timedelta(days=UNDECIDED_NOTICE_DAYS + 1)).isoformat()
            + _LOCAL_MIDNIGHT,
        ),
    ).fetchone()
    return int(row["count"])


def _skipped_count(raw: Any) -> int:
    """Count the components the last sync skipped; the kv value is a reason map."""
    try:
        reasons = json.loads(raw) if raw else {}
        return sum(int(count) for count in reasons.values())
    except TypeError, ValueError, AttributeError:
        return 0


def state(
    db: Any,
    *,
    configured: bool,
    running: bool,
    today: date,
    window_days: int,
) -> dict[str, Any]:
    last_sync = _kv_value(db, "last_external_calendar_sync_at")
    last_error = _kv_value(db, "last_external_calendar_sync_error")
    skipped = _kv_value(db, "last_external_calendar_sync_skipped")
    return {
        "configured": configured,
        "provider": "iCalendar",
        "read_only": True,
        "running": running,
        "last_sync_at": last_sync,
        "last_error": last_error or None,
        "skipped_events": _skipped_count(skipped or ""),
        "events": list_events(db, today=today),
        "undecided_upcoming": undecided_upcoming(db, today=today),
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
        with self._database_manager.reader() as db:
            return list_events(
                db,
                today=self._today(),
                limit=limit,
                training_relevant_only=training_relevant_only,
            )

    def event_counts(self, db: Any) -> dict[str, int]:
        """Count the events on a connection the caller already holds."""
        return event_counts(db, today=self._today())

    def list_events_in_window(
        self, window_days: int, training_relevant_only: bool = False
    ) -> list[dict[str, Any]]:
        with self._database_manager.reader() as db:
            return list_events_in_window(
                db,
                today=self._today(),
                window_days=window_days,
                training_relevant_only=training_relevant_only,
            )

    def state(
        self, *, configured: bool, running: bool, window_days: int
    ) -> dict[str, Any]:
        with self._database_manager.reader() as db:
            return state(
                db,
                configured=configured,
                running=running,
                today=self._today(),
                window_days=window_days,
            )


def _kv_value(db: Any, key: str) -> str | None:
    row = db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
