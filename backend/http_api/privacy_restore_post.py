"""Authenticated database backup restore POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.backup.restore import DatabaseRestoreService
from backend.http_api.auth import SessionAuthService
from backend.http_api.route_table import Access, Route, RouteRequest


class PrivacyRestorePostRoutes:
    """Dispatch database restore payload through validation and import."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        database_restore_service: Callable[[], DatabaseRestoreService],
        max_backup_bytes: int,
    ) -> None:
        self._session_auth_service = session_auth_service
        self._database_restore_service = database_restore_service
        self._max_backup_bytes = max_backup_bytes

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST",
                "/api/privacy/restore",
                Access.SESSION_CSRF,
                self._restore,
                gated=False,
            )
        ]

    def _restore(self, handler: Any, _request: RouteRequest) -> None:
        """Restore a database backup; ends every session."""
        auth = self._session_auth_service()
        # The upload is streamed; the restore service stages it to a file in chunks.
        payload = handler.read_body_stream(self._max_backup_bytes)
        result = self._database_restore_service().restore(payload)
        clear_headers = auth.session_cookie_headers(clear=True)
        handler.send_json(
            200, result, {"Set-Cookie": [clear_headers[0], clear_headers[1]]}
        )
