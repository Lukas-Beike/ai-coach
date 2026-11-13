"""Authenticated POST route that renames a recognised activity route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest

_PATH = "/api/routes/rename"


class ActivityRoutePostRoutes:
    """Rename one route through the route service; nothing is written remotely."""

    def __init__(self, route_service: Callable[[], Any]) -> None:
        self._route_service = route_service

    def routes(self) -> list[Route]:
        return [Route("POST", _PATH, Access.SESSION_CSRF, self._rename)]

    def _rename(self, handler: Any, _request: RouteRequest) -> None:
        """Rename one recognised activity route; nothing is written remotely.

        Request: JSON body `{"route_id": string, "name": string}`; `name` is trimmed
        and must be 1 to 60 printable characters without control characters.

        Response: 200 `{"status": "ok", "route_id", "label"}` with the trimmed name
        as `label`.

        Errors: 400 "Der Name muss aus 1 bis 60 Zeichen ohne Steuerzeichen
        bestehen." for an invalid `name`; 404 "Nicht gefunden." when `route_id`
        names no stored route.
        """
        payload = handler.read_json()
        if not isinstance(payload, dict):
            raise AppError(400, "Die Anfrage muss ein Objekt sein.")
        handler.send_json(
            200,
            self._route_service().rename(payload.get("route_id"), payload.get("name")),
        )
