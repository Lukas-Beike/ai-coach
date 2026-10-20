"""Authenticated local analysis reads and scenario projection."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.errors import AppError


class AnalysisRoutes:
    def __init__(
        self,
        auth: Any,
        reports: Any,
        refresh: Any = None,
    ):
        self._auth = auth
        self._reports = reports
        self._refresh = refresh

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {
            "/api/analysis/endurance",
            "/api/analysis/power-profiles",
            "/api/analysis/season",
            "/api/analysis/training-records",
        }:
            return False
        self._auth().require_auth(handler)
        values = {
            key: value[0]
            for key, value in parse_qs(urlparse(handler.path).query).items()
        }
        reports = self._reports()
        if path.endswith("/training-records"):
            payload = reports.records.training_records(values)
        elif path.endswith("/season"):
            payload = reports.season.season(reports.timezone())
        elif path.endswith("/power-profiles"):
            payload = reports.profiles.power_profiles(reports.records.observations())
        else:
            payload = reports.records.endurance()
        handler.send_json(200, payload)
        return True

    def handle_post(self, handler: Any, path: str) -> bool:
        if path == "/api/analysis/refresh":
            self._auth().require_auth(handler)
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
        if path == "/api/analysis/scenarios":
            reports = self._reports()
            handler.send_json(
                200, reports.report.scenarios(handler.read_json(), reports.timezone())
            )
            return True
        return False
