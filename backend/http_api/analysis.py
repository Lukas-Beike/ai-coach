"""Authenticated local analysis reads and explicit report archival."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse


class AnalysisRoutes:
    def __init__(self, auth: Any, reports: Any):
        self._auth = auth
        self._reports = reports

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {
            "/api/analysis/report",
            "/api/analysis/reports",
            "/api/analysis/endurance",
            "/api/analysis/power-profiles",
            "/api/analysis/season",
            "/api/analysis/impact",
            "/api/analysis/training-records",
            "/api/analysis/comparisons",
        }:
            return False
        self._auth().require_auth(handler)
        values = {
            key: value[0]
            for key, value in parse_qs(urlparse(handler.path).query).items()
        }
        reports = self._reports()
        if path.endswith("/comparisons"):
            payload = reports.records.comparisons()
        elif path.endswith("/training-records"):
            payload = reports.records.training_records(values)
        elif path.endswith("/impact"):
            payload = reports.derived.impact(reports.timezone())
        elif path.endswith("/season"):
            payload = reports.season.season(reports.timezone())
        elif path.endswith("/power-profiles"):
            payload = reports.profiles.power_profiles(reports.records.observations())
        elif path.endswith("/endurance"):
            payload = reports.records.endurance()
        elif path.endswith("/reports"):
            payload = reports.archive.archives()
        else:
            payload = reports.report.read(values, reports.timezone())
        handler.send_json(200, payload)
        return True

    def handle_post(self, handler: Any, path: str) -> bool:
        if path == "/api/analysis/scenarios":
            reports = self._reports()
            handler.send_json(
                200, reports.report.scenarios(handler.read_json(), reports.timezone())
            )
            return True
        if path != "/api/analysis/reports":
            return False
        handler.send_json(200, self._reports().archive.archive(handler.read_json()))
        return True
