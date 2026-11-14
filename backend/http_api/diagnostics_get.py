"""Authenticated GET routes for logs and diagnostic state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.diagnostics.logs import RecentLogEntriesService
from backend.diagnostics.report import DiagnosticReportService
from backend.http_api.route_table import Access, Route, RouteRequest


class DiagnosticsGetRoutes:
    """Dispatch authenticated diagnostic reads through their state owners."""

    def __init__(
        self,
        recent_log_entries_service: Callable[[], RecentLogEntriesService],
        diagnostic_report_service: Callable[[], DiagnosticReportService],
    ) -> None:
        self._recent_log_entries_service = recent_log_entries_service
        self._diagnostic_report_service = diagnostic_report_service

    def routes(self) -> list[Route]:
        return [
            Route("GET", "/api/logs", Access.SESSION, self._logs),
            Route("GET", "/api/logs/download", Access.SESSION, self._download),
            Route("GET", "/api/diagnostics", Access.SESSION, self._report),
        ]

    def _download(self, handler: Any, _request: RouteRequest) -> None:
        """Download the redacted server log as JSON lines.

        Request: no body.

        Response: 200 `application/x-ndjson` attachment
        `pacecraft-server-logs.jsonl`: every entry of the rotated and the active
        log file, oldest first, one redacted JSON object per line.

        Errors: none beyond the common ones.
        """
        handler.send_bytes(
            200,
            self._recent_log_entries_service().download(),
            "application/x-ndjson; charset=utf-8",
            {
                "Content-Disposition": 'attachment; filename="pacecraft-server-logs.jsonl"'
            },
        )

    def _logs(self, handler: Any, request: RouteRequest) -> None:
        """Recent redacted log entries.

        Request: query `limit` (1 to 500, default 200; a non-integer value gives
        200).

        Response: 200 with `entries`, the last `limit` redacted entries of the
        active log file in log order (objects such as `timestamp`, `level`,
        `event`, `message`).

        Errors: none beyond the common ones.
        """
        raw_limit = request.query.get("limit", ["200"])[0]
        try:
            limit = max(1, min(int(raw_limit), 500))
        except ValueError:
            limit = 200
        handler.send_json(
            200, {"entries": self._recent_log_entries_service().list(limit)}
        )

    def _report(self, handler: Any, _request: RouteRequest) -> None:
        """Diagnostic report.

        Request: no body.

        Response: 200 with the redacted report of `DiagnosticReportService.report`,
        read from one database snapshot. Top-level keys include `generated_at`,
        `app`, `runtime`, `configuration`, `openai`, `coach_commands`, `sync`,
        `garmin`, `wahoo`, `provider_freshness`, `external_calendar`, `database`,
        `recovery_copies`, `plan_sync`, the `canonical_*` sections, `logs` (recent warnings, errors
        and INFO entries), `debug_capture` (status and captured request and
        response shapes) and `note`. A section that cannot be built is
        `{"status": "unavailable"}`.

        Errors: none beyond the common ones.
        """
        handler.send_json(200, self._diagnostic_report_service().report())
