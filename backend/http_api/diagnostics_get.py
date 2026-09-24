"""Authenticated GET routes for logs and diagnostic state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportService
from backend.http_api.auth import SessionAuthService
from backend.observability import DiagnosticCapture


class DiagnosticsGetRoutes:
    """Dispatch authenticated diagnostic reads through their state owners."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        recent_log_entries_service: Callable[[], RecentLogEntriesService],
        diagnostic_report_service: Callable[[], DiagnosticReportService],
        diagnostic_capture: DiagnosticCapture,
    ) -> None:
        self._session_auth_service = session_auth_service
        self._recent_log_entries_service = recent_log_entries_service
        self._diagnostic_report_service = diagnostic_report_service
        self._diagnostic_capture = diagnostic_capture

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {"/api/logs", "/api/diagnostics", "/api/diagnostics/capture"}:
            return False

        self._session_auth_service().require_auth(handler)
        if path == "/api/logs":
            raw_limit = parse_qs(urlparse(handler.path).query).get("limit", ["200"])[0]
            try:
                limit = max(1, min(int(raw_limit), 500))
            except ValueError:
                limit = 200
            payload = {"entries": self._recent_log_entries_service().list(limit)}
        elif path == "/api/diagnostics":
            payload = self._diagnostic_report_service().report()
        else:
            payload = self._diagnostic_capture.status()

        handler.send_json(200, payload)
        return True
