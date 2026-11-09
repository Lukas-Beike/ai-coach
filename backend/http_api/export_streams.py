"""HTTP transport for database backups and privacy archive downloads."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.backup.database import DatabaseBackupService
from backend.backup.export import PrivacyArchiveExportService


class ExportStreamTransport:
    """Stream files produced by the concrete backup and export services."""

    def __init__(
        self,
        database_backup_factory: Callable[[], DatabaseBackupService],
        privacy_export_factory: Callable[[], PrivacyArchiveExportService],
    ) -> None:
        self._database_backup_factory = database_backup_factory
        self._privacy_export_factory = privacy_export_factory

    def stream_database_backup(self, handler: Any) -> None:
        with self._database_backup_factory().stream_file() as path:
            handler.send_file_stream(
                path,
                "application/octet-stream",
                "pacecraft-database.backup",
            )

    def stream_privacy_export(self, handler: Any) -> None:
        temporary = self._privacy_export_factory().create_file()
        handler.send_file_stream(
            temporary,
            "application/zip",
            "pacecraft-export.zip",
            cleanup=True,
        )
