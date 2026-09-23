"""Local and external calendar conflict use case."""

from __future__ import annotations

from typing import Any

from backend.planning import calendar, context


class CalendarConflictService:
    """Collect conflict candidates and project them in source order."""

    def __init__(self, database_manager: Any, external_calendar_reader: Any) -> None:
        self._database_manager = database_manager
        self._external_calendar_reader = external_calendar_reader

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
        return (
            calendar.calendar_conflicts_for_items(
                workout, library_entries, "local_library"
            )
            + calendar.calendar_conflicts_for_items(
                workout, competitions, "local_competition"
            )
            + calendar.calendar_conflicts_for_items(
                workout, external_events, "external_calendar"
            )
        )
