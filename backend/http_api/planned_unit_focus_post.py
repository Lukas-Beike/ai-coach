"""Authenticated POST routes that set the focus, the day or a Garmin exercise of a unit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend import change_history
from backend.canonical.planning_fields import FOCUS_ONLY_KEYS
from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class PlannedUnitFocusPostRoutes:
    """Set the focus fields or the day of one unit, or the Garmin exercise of one exercise."""

    def __init__(self, planned_unit_service: Callable[[], Any], database_lock: Any):
        self._planned_unit_service = planned_unit_service
        self._database_lock = database_lock

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST",
                "/api/planned-units/{id}/focus",
                Access.SESSION_CSRF,
                self._focus,
            ),
            Route(
                "POST",
                "/api/planned-units/{id}/date",
                Access.SESSION_CSRF,
                self._date,
            ),
            Route(
                "POST",
                "/api/planned-units/{id}/garmin-exercise",
                Access.SESSION_CSRF,
                self._exercise,
            ),
        ]

    def _date(self, handler: Any, request: RouteRequest) -> None:
        """Move a planned unit to another day without a remote write.

        Request: path `{id}`, the local unit id; JSON body `{"date": "YYYY-MM-DD",
        "expected_payload_hash": string}`. The date is today or later in the
        athlete's time zone; the start time keeps its time of day. The hash is the
        unit's content hash from the read the move was made on.

        Response: 200 `{"status": "local", "local_id", "library_entry", "change"}`
        with the moved unit and the undo reference (`change` is missing when the
        date did not change; the unit is then left as it is). A unit already sent
        to a provider shows its pending sync; nothing is written remotely.

        Errors: 400 "Ungültige lokale Planungs-ID." for an id that is no UUID; 404
        "Einheit nicht gefunden." for an unknown, archived or deleted unit; 409
        `planning_revision_conflict` "Die Einheit wurde inzwischen geändert." for a
        missing or outdated `expected_payload_hash`; 400 "Das Planungsdatum muss das
        Format JJJJ-MM-TT haben."; 400 "Eine Einheit in der Vergangenheit wird nicht
        geplant." for a day before today; 409 `plan_date_conflict` when an external
        calendar marker rules out the day; 409 "Die lokale Einheit kann wegen einer
        bestehenden Kalendereinheit nicht verschoben werden." for an overlapping
        calendar entry.
        """
        payload = _read_object(handler)
        with change_history.collect_changes() as changes, self._database_lock:
            result = self._planned_unit_service().move(
                request.params["id"],
                payload.get("date"),
                payload.get("expected_payload_hash"),
            )
        moved = [item for item in changes if item["entity_type"] == "planned_unit"]
        handler.send_json(200, {**result, **({"change": moved[-1]} if moved else {})})

    def _exercise(self, handler: Any, request: RouteRequest) -> None:
        """Assign the Garmin catalogue exercise of one strength exercise of a unit.

        Request: path `{id}`, the local unit id; JSON body `{"exercise_index":
        integer, "garmin_exercise": string, "expected_payload_hash": string}`. The
        index counts into the unit's strength structure from 0; the hash is the
        unit's content hash from the read the pick was made on. A name is trimmed,
        cut to 80 characters and checked against the Garmin catalogue; the pair is
        derived from it. An empty name removes the pick.

        Response: 200 `{"status": "local", "local_id", "library_entry"}` with the
        updated unit. The unit's Intervals.icu sync state is kept and nothing is
        written remotely.

        Errors: 404 "Einheit nicht gefunden." for an unknown or deleted unit; 409
        `planning_revision_conflict` "Die Einheit wurde inzwischen geändert." for a
        missing or outdated `expected_payload_hash`; 400 `invalid_exercise_index`
        "Unbekannte Übung." when the unit has no strength structure or the index is
        not an integer within it; 400 `invalid_strength_structure` "Unbekannte
        Garmin-Übung: ..." with suggestions for a name the catalogue does not know.
        """
        payload = _read_object(handler)
        with self._database_lock:
            result = self._planned_unit_service().assign_garmin_exercise(
                request.params["id"],
                payload.get("exercise_index"),
                payload.get("garmin_exercise"),
                payload.get("expected_payload_hash"),
            )
        handler.send_json(200, result)

    def _focus(self, handler: Any, request: RouteRequest) -> None:
        """Set or clear the focus of a planned unit without a remote write.

        Request: path `{id}`, the local unit UUID; JSON body `{"session_focus":
        string|null, "strength_intensity": string|null}`. Both fields are always
        applied: an omitted or `null` field is cleared. `session_focus` must be a
        focus of the unit's sport; `strength_intensity` is `light`, `moderate` or
        `heavy` and only for strength units.

        Response: 200 `{"status": "local", "local_id", "library_entry"}` with the
        updated unit. A focus-only change keeps the Intervals.icu sync state.

        Errors: 400 "Ungültige lokale Planungs-ID." for an id that is no UUID; 404
        "Lokale Planung nicht gefunden."; 403 "Nur lokale geplante Einheiten können
        bearbeitet werden." for a record without a date; 400 `invalid_session_focus`
        "Ungültige Art der Einheit für diese Sportart." or "Ungültige
        Krafteinheit-Intensität."; 409 `plan_date_conflict` when an external
        calendar marker rules out the unit's day.
        """
        payload = _read_object(handler)
        values = {key: payload.get(key) for key in FOCUS_ONLY_KEYS}
        with self._database_lock:
            result = self._planned_unit_service().update(request.params["id"], values)
        handler.send_json(200, result)


def _read_object(handler: Any) -> dict[str, Any]:
    payload = handler.read_json()
    if not isinstance(payload, dict):
        raise AppError(400, "Die Anfrage muss ein Objekt sein.")
    return payload
