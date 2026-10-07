"""Local and external calendar conflict use case."""

from __future__ import annotations

from typing import Any

from backend.errors import AppError
from backend.planning import calendar, context


class CalendarConflictService:
    """Collect conflict candidates and project them in source order."""

    def __init__(self, database_manager: Any, external_calendar_reader: Any) -> None:
        self._database_manager = database_manager
        self._external_calendar_reader = external_calendar_reader

    def constraints(
        self, workout: dict[str, Any], events: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Return current marker decisions with source and freshness evidence."""
        self._require_current_calendar_constraints()
        conflicts = []
        source_events = (
            self._external_calendar_reader.list_events(
                1000, training_relevant_only=True
            )
            if events is None
            else events
        )
        for event in source_events:
            decision = calendar.calendar_constraint_decision(workout, event)
            matches = calendar._calendar_items_share_local_day(workout, event)
            if not matches or not decision:
                continue
            event_date = str(event.get("event_date") or event.get("start_local") or "")[
                :10
            ]
            conflicts.append(
                {
                    "id": event.get("id"),
                    "name": event.get("name") or "Kalendereintrag",
                    "date": event_date,
                    "source": "external_calendar",
                    "match": "calendar_constraint",
                    "constraint": decision["marker"],
                    "reason": decision["reason"],
                    "updated_at": event.get("updated_at"),
                }
            )
        return conflicts

    def _require_current_calendar_constraints(self) -> None:
        with self._database_manager.unit_of_work() as db:
            # Some lightweight domain test fixtures omit unrelated durable tables.
            has_kv = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kv'"
            ).fetchone()
            if not has_kv:
                return
            required = db.execute(
                "SELECT value FROM kv WHERE key='external_calendar_constraints_refresh_required'"
            ).fetchone()
        if required and required["value"] == "1":
            raise AppError(
                409,
                "Bitte den Kalender synchronisieren, bevor Kalenderbeschränkungen geprüft werden können.",
                reason="calendar_refresh_required",
            )

    def conflicts(
        self,
        workout: dict[str, Any],
        exclude_library_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._database_manager.unit_of_work() as db:
            library_rows = [
                dict(row)
                for row in db.execute(
                    "SELECT local_id, payload FROM planned_units "
                    "WHERE COALESCE(json_extract(payload, '$.local_deleted'), 0) = 0 "
                    "AND COALESCE(json_extract(payload, '$.archived'), 0) = 0"
                ).fetchall()
            ]
            competitions = [
                dict(row)
                for row in db.execute(
                    "SELECT id, name, event_date, start_date_local, moving_time "
                    "FROM competitions"
                ).fetchall()
            ]

        library_entries = context.local_calendar_library_entries(
            library_rows, exclude_library_ids or set()
        )
        external_events = self._external_calendar_reader.list_events(
            1000, training_relevant_only=True
        )
        constraint_conflicts = self.constraints(workout, external_events)
        ordinary_events = []
        for event in external_events:
            marker_text = str(event.get("name") or "").casefold()
            is_marked = bool(
                event.get("no_training")
                or event.get("no_intensity")
                or event.get("short_only")
                or "[no_training]" in marker_text
                or "[no_intensity]" in marker_text
                or "[short_only]" in marker_text
            )
            event_matches, _match = calendar._calendar_items_conflict(workout, event)
            if not event_matches or not is_marked:
                ordinary_events.append(event)
        return (
            constraint_conflicts
            + calendar.calendar_conflicts_for_items(
                workout, library_entries, "local_library"
            )
            + calendar.calendar_conflicts_for_items(
                workout, competitions, "local_competition"
            )
            + calendar.calendar_conflicts_for_items(
                workout, ordinary_events, "external_calendar"
            )
        )
