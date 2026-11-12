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
        """Restore a database backup; ends every session.

        Request: the raw bytes of a backup from `GET /api/privacy/backup` as the
        body (no JSON), streamed to a staging file; 1 000 000 000 bytes at most.
        Runs outside the maintenance gate and takes it for validation and swap.

        Response: 200 with `status` (`"ok"`), `restored` (`true`) and
        `previous_database_backup` (file name of the pre-restore copy of the live
        database, or null); `Set-Cookie` clears the `ic_session` and `ic_csrf`
        cookies, since the restored sessions are deleted.

        Errors: 413 "Das Datenbank-Backup ist leer oder zu groß."; 400 "Das
        Datenbank-Backup konnte nicht validiert werden: ..." (redacted detail of
        at most 300 characters), "Das Backup entspricht keinem unterstützten
        Datenbankschema.", "Das Backup entspricht nicht exakt dem aktuellen
        Datenbankschema.", "Das Backup enthält ungültige Fremdschlüssel." or
        "Die Integritätsprüfung des Backups ist fehlgeschlagen."; 400 for a
        schema older than 26 ("Das Backup stammt aus einem Release vor 2.0.5
        ..."); 503 "SQLCipher ist für die Wiederherstellung nicht verfügbar.";
        507 `restore_storage_full`; 500 `restore_storage_failed`; 500
        `restored_resume_failed` when the restore succeeded but the background
        work could not resume; 409 "Eine Datenbankwiederherstellung läuft
        bereits."; 409 `maintenance_drain_timeout`, nothing changed.
        """
        auth = self._session_auth_service()
        # The upload is streamed; the restore service stages it to a file in chunks.
        payload = handler.read_body_stream(self._max_backup_bytes)
        result = self._database_restore_service().restore(payload)
        clear_headers = auth.session_cookie_headers(clear=True)
        handler.send_json(
            200, result, {"Set-Cookie": [clear_headers[0], clear_headers[1]]}
        )
