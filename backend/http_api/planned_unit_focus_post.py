"""Authenticated POST routes that set the focus or a Garmin exercise of a unit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.canonical.planning_fields import FOCUS_ONLY_KEYS
from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class PlannedUnitFocusPostRoutes:
    """Set the focus fields of one unit, or the Garmin exercise of one exercise."""

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
                "/api/planned-units/{id}/garmin-exercise",
                Access.SESSION_CSRF,
                self._exercise,
            ),
        ]

    def _exercise(self, handler: Any, request: RouteRequest) -> None:
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
