"""Authenticated HTTP routes for local privacy downloads and previews."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.auth import SessionAuthService
from backend.http_api.export_streams import ExportStreamTransport
from backend.privacy import PrivacyDeleteService


class PrivacyGetRoutes:
    """Dispatch privacy GET requests through their existing service owners."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        export_stream_transport: Callable[[], ExportStreamTransport],
        privacy_delete_service: Callable[[], PrivacyDeleteService],
    ) -> None:
        self._session_auth_service = session_auth_service
        self._export_stream_transport = export_stream_transport
        self._privacy_delete_service = privacy_delete_service

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {
            "/api/privacy/export",
            "/api/privacy/delete/preview",
            "/api/privacy/backup",
        }:
            return False

        self._session_auth_service().require_auth(handler)
        if path == "/api/privacy/export":
            self._export_stream_transport().stream_privacy_export(handler)
        elif path == "/api/privacy/delete/preview":
            handler.send_json(200, self._privacy_delete_service().preview())
        else:
            self._export_stream_transport().stream_database_backup(handler)
        return True
