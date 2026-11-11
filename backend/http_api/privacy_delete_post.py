"""HTTP route for explicitly confirmed local privacy deletion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.privacy import PrivacyDeleteService


class PrivacyDeletePostRoutes:
    """Dispatch the privacy deletion POST to its domain service."""

    def __init__(
        self,
        privacy_delete_service: Callable[[], PrivacyDeleteService],
    ) -> None:
        self._privacy_delete_service = privacy_delete_service

    def routes(self) -> list[Route]:
        return [
            Route("POST", path, Access.SESSION_CSRF, self._handle)
            for path in (
                "/api/privacy/delete",
                "/api/privacy/gps",
                "/api/privacy/gps/delete",
            )
        ]

    def _handle(self, handler: Any, request: RouteRequest) -> None:
        payload = handler.read_json()
        service = self._privacy_delete_service()
        if request.path == "/api/privacy/gps":
            result = service.set_gps_tracks(payload.get("enabled"))
        elif request.path == "/api/privacy/gps/delete":
            result = service.delete_gps_tracks(payload.get("confirm"))
        else:
            result = service.delete(payload.get("confirm"))
        handler.send_json(200, result)
