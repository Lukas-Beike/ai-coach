"""The athlete's training-impact decision for an external calendar event."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.errors import AppError

IMPACTS = frozenset({"block", "short", "easy", "none"})
_MAX_UID_LENGTH = 500
_MAX_START_LENGTH = 40


class ExternalCalendarDecisionService:
    """Store or remove a decision, then refresh the adaptive preview."""

    def __init__(
        self,
        database_manager: Any,
        preview_followup: Any,
        state_event_buffer: Any,
        utc_now: Callable[[], str],
    ) -> None:
        self._database_manager = database_manager
        self._preview_followup = preview_followup
        self._state_event_buffer = state_event_buffer
        self._utc_now = utc_now

    def decide(self, uid: Any, occurrence_start: Any, impact: Any) -> dict[str, Any]:
        """Set the impact of one occurrence, or of every occurrence when no start is given.

        A series decision replaces the occurrence decisions of its UID; ``None``
        as impact removes the decision. Only stored events can be decided.
        """
        uid = uid if isinstance(uid, str) else ""
        start = "" if occurrence_start is None else occurrence_start
        if not 0 < len(uid) <= _MAX_UID_LENGTH or not isinstance(start, str):
            raise AppError(400, "Ungültiger Termin.")
        if len(start) > _MAX_START_LENGTH:
            raise AppError(400, "Ungültiger Termin.")
        if impact is not None and impact not in IMPACTS:
            raise AppError(400, "Ungültige Einordnung.")
        with self._database_manager.unit_of_work() as db:
            if not db.execute(
                "SELECT 1 FROM external_calendar_events "
                "WHERE uid = ? AND (? = '' OR start_local = ?) LIMIT 1",
                (uid, start, start),
            ).fetchone():
                raise AppError(404, "Termin nicht gefunden.")
            if not start:
                db.execute(
                    "DELETE FROM external_calendar_decisions WHERE uid = ?", (uid,)
                )
            if impact is None:
                db.execute(
                    "DELETE FROM external_calendar_decisions "
                    "WHERE uid = ? AND occurrence_start = ?",
                    (uid, start),
                )
            else:
                db.execute(
                    "INSERT INTO external_calendar_decisions"
                    "(uid, occurrence_start, impact, decided_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(uid, occurrence_start) DO UPDATE SET "
                    "impact = excluded.impact, decided_at = excluded.decided_at",
                    (uid, start, impact, self._utc_now()),
                )
        self._state_event_buffer.publish("coach", {"status": "changed"})
        return {
            "uid": uid,
            "occurrence_start": start or None,
            "impact": impact,
            **self._preview_followup.check("external calendar decision"),
        }
