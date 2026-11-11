"""Authenticated HTTP routes for clearing logs and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportService
from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class DiagnosticsDeletePostRoutes:
    """Dispatch log and diagnostic deletion requests to their services."""

    def __init__(
        self,
        recent_log_entries_service: Callable[[], RecentLogEntriesService],
        diagnostic_report_service: Callable[[], DiagnosticReportService],
    ) -> None:
        self._recent_log_entries_service = recent_log_entries_service
        self._diagnostic_report_service = diagnostic_report_service

    def routes(self) -> list[Route]:
        return [
            Route("POST", "/api/logs/delete", Access.SESSION_CSRF, self._delete_logs),
            Route(
                "POST",
                "/api/diagnostics/delete",
                Access.SESSION_CSRF,
                self._delete_diagnostics,
            ),
        ]

    def _delete_logs(self, handler: Any, _request: RouteRequest) -> None:
        """Clear the server log."""
        try:
            result = self._recent_log_entries_service().clear()
        except OSError as exc:
            raise AppError(500, "Logs konnten nicht gelöscht werden.") from exc
        handler.send_json(200, result)

    def _delete_diagnostics(self, handler: Any, _request: RouteRequest) -> None:
        """Clear the stored diagnostics."""
        try:
            result = self._diagnostic_report_service().clear()
        except Exception as exc:
            raise AppError(500, "Diagnose konnte nicht gelöscht werden.") from exc
        handler.send_json(200, result)
