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
        """Download the privacy export archive.

        Request: no body.

        Response: 200 `application/zip` attachment `pacecraft-export.zip`, built
        from one database snapshot: `profile.json`, `application_state.json`,
        `provider_settings.json`, `planning.json`, `garmin_snapshot.json`,
        `weather_cache.json`, one `.jsonl` file per exported table and
        `manifest.json`.

        Errors: 503 "Der Export-Speicher ist nicht verfügbar."; 507 "Für den
        Export ist nicht ausreichend freier Speicher verfügbar."; 408 "Der Export
        überschreitet das Zeitlimit."; 413 "Der Export überschreitet das
        Größenlimit."
        """
        self._export_stream_transport().stream_privacy_export(handler)

    def _preview(self, handler: Any, _request: RouteRequest) -> None:
        """Preview of the local data deletion.

        Request: no body.

        Response: 200 with `status` (`"preview"`), `confirmation_text` (the text
        `POST /api/privacy/delete` requires), `categories` (list of `id`, `label`
        and `records`, including the recovery copies and the server log files),
        `remote_untouched` (list of statements about data at providers that stays
        unchanged) and `openai_conversation` (statement about the OpenAI
        conversation).

        Errors: none beyond the common ones.
        """
        handler.send_json(200, self._privacy_delete_service().preview())

    def _gps(self, handler: Any, _request: RouteRequest) -> None:
        """GPS-track setting and stored-track count.

        Request: no body.

        Response: 200 with `enabled` (whether new GPS tracks are stored),
        `stored_tracks` (number of activities holding a track) and
        `confirmation_text` (`GPS-SPUREN LÖSCHEN`, required by
        `POST /api/privacy/gps/delete`).

        Errors: none beyond the common ones.
        """
        handler.send_json(200, self._privacy_delete_service().gps_state())

    def _backup(self, handler: Any, _request: RouteRequest) -> None:
        """Download the encrypted database backup.

        Request: no body.

        Response: 200 `application/octet-stream` attachment
        `pacecraft-database.backup`, a consistent snapshot of the database file
        that `POST /api/privacy/restore` accepts.

        Errors: 503 "Der Backup-Speicher ist nicht verfügbar." or "Die Datenbank
        konnte nicht konsistent als Backup vorbereitet werden."; 413 "Das
        Datenbank-Backup überschreitet das Größenlimit."; 507 "Für den
        Backup-Download ist nicht ausreichend freier Speicher verfügbar."
        """
        self._export_stream_transport().stream_database_backup(handler)
