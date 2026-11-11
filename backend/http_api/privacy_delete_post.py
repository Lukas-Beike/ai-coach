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
            Route("POST", "/api/privacy/delete", Access.SESSION_CSRF, self._delete),
            Route("POST", "/api/privacy/gps", Access.SESSION_CSRF, self._gps),
            Route(
                "POST", "/api/privacy/gps/delete", Access.SESSION_CSRF, self._delete_gps
            ),
        ]

    def _delete(self, handler: Any, _request: RouteRequest) -> None:
        """Delete the local athlete data after the typed confirmation (`confirm`)."""
        payload = handler.read_json()
        handler.send_json(
            200, self._privacy_delete_service().delete(payload.get("confirm"))
        )

    def _gps(self, handler: Any, _request: RouteRequest) -> None:
        """Turn GPS-track storage on or off (`enabled`)."""
        payload = handler.read_json()
        handler.send_json(
            200, self._privacy_delete_service().set_gps_tracks(payload.get("enabled"))
        )

    def _delete_gps(self, handler: Any, _request: RouteRequest) -> None:
        """Delete every stored GPS track and the routes derived from them after the typed confirmation (`confirm`)."""
        payload = handler.read_json()
        handler.send_json(
            200,
            self._privacy_delete_service().delete_gps_tracks(payload.get("confirm")),
        )
