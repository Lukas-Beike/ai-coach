"""Authenticated local analysis reads and targeted refresh."""

from __future__ import annotations

from typing import Any

from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class AnalysisRoutes:
    def __init__(
        self,
        reports: Any,
        refresh: Any = None,
    ):
        self._reports = reports
        self._refresh = refresh

    def routes(self) -> list[Route]:
        return [
            Route("GET", "/api/analysis/power-profiles", Access.SESSION, self._report),
            Route(
                "GET", "/api/analysis/training-records", Access.SESSION, self._report
            ),
        ]

    def _report(self, handler: Any, request: RouteRequest) -> None:
        path = request.path
        values = {key: value[0] for key, value in request.query.items()}
        reports = self._reports()
        if path.endswith("/training-records"):
            payload = reports.records.training_records(values)
        else:
            payload = reports.profiles.power_profiles()
        handler.send_json(200, payload)

    def handle_post(self, handler: Any, path: str) -> bool:
        if path == "/api/analysis/refresh":
            payload = handler.read_json()
            area = payload.get("area") if isinstance(payload, dict) else None
            if not isinstance(area, str) or area not in {
                "load",
                "performance",
                "recovery",
                "sessions",
            }:
                raise AppError(400, "Ungültiger Analysebereich.")
            days = payload.get("days")
            if days is not None and (
                area not in {"load", "recovery"} or days not in {14, 84}
            ):
                raise AppError(400, "Ungültiger Analysezeitraum.")
            if self._refresh is None:
                raise AppError(
                    503,
                    "Die gezielte Aktualisierung ist nicht verfügbar.",
                    reason="analysis_refresh_unavailable",
                )
            handler.send_json(200, self._refresh().refresh(area, days=days))
            return True
        return False
