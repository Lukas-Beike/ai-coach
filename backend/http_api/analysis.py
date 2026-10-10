"""Authenticated local analysis reads and scenario projection."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse


class AnalysisRoutes:
    def __init__(self, auth: Any, reports: Any):
        self._auth = auth
        self._reports = reports

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
        if path == "/api/analysis/scenarios":
            reports = self._reports()
            handler.send_json(
                200, reports.report.scenarios(handler.read_json(), reports.timezone())
            )
            return True
        return False
