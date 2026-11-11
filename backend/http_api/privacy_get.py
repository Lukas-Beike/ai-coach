"""Authenticated HTTP routes for local privacy downloads and previews."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.export_streams import ExportStreamTransport
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.privacy import PrivacyDeleteService


class PrivacyGetRoutes:
    """Dispatch privacy GET requests through their existing service owners."""

    def __init__(
        self,
        export_stream_transport: Callable[[], ExportStreamTransport],
        privacy_delete_service: Callable[[], PrivacyDeleteService],
    ) -> None:
        self._export_stream_transport = export_stream_transport
        self._privacy_delete_service = privacy_delete_service

    def routes(self) -> list[Route]:
        return [
            Route("GET", "/api/privacy/export", Access.SESSION, self._export),
            Route("GET", "/api/privacy/delete/preview", Access.SESSION, self._preview),
            Route("GET", "/api/privacy/backup", Access.SESSION, self._backup),
            Route("GET", "/api/privacy/gps", Access.SESSION, self._gps),
        ]

    def _export(self, handler: Any, _request: RouteRequest) -> None:
        self._export_stream_transport().stream_privacy_export(handler)

    def _preview(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(200, self._privacy_delete_service().preview())

    def _gps(self, handler: Any, _request: RouteRequest) -> None:
        handler.send_json(200, self._privacy_delete_service().gps_state())

    def _backup(self, handler: Any, _request: RouteRequest) -> None:
        self._export_stream_transport().stream_database_backup(handler)
