"""Authenticated HTTP routes for clearing logs and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportService
from backend.errors import AppError


class DiagnosticsDeletePostRoutes:
    """Dispatch log and diagnostic deletion requests to their services."""

    def __init__(
        self,
        recent_log_entries_service: Callable[[], RecentLogEntriesService],
        diagnostic_report_service: Callable[[], DiagnosticReportService],
    ) -> None:
        self._recent_log_entries_service = recent_log_entries_service
        self._diagnostic_report_service = diagnostic_report_service

    def handle(self, handler: Any, path: str) -> bool:
        if path == "/api/logs/delete":
            try:
                result = self._recent_log_entries_service().clear()
            except OSError as exc:
                raise AppError(500, "Logs konnten nicht gelöscht werden.") from exc
            handler.send_json(200, result)
            return True
        if path == "/api/diagnostics/delete":
            try:
                result = self._diagnostic_report_service().clear()
            except Exception as exc:
                raise AppError(500, "Diagnose konnte nicht gelöscht werden.") from exc
            handler.send_json(200, result)
            return True
        return False
