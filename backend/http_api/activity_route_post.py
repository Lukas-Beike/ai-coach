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
        payload = handler.read_json()
        if not isinstance(payload, dict):
            raise AppError(400, "Die Anfrage muss ein Objekt sein.")
        handler.send_json(
            200,
            self._route_service().rename(payload.get("route_id"), payload.get("name")),
        )
