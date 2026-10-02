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
            payload = reports.comparisons()
        elif path.endswith("/training-records"):
            payload = reports.training_records(values)
        elif path.endswith("/impact"):
            payload = reports.impact()
        elif path.endswith("/season"):
            payload = reports.season()
        elif path.endswith("/power-profiles"):
            payload = reports.power_profiles()
        elif path.endswith("/endurance"):
            payload = reports.endurance()
        elif path.endswith("/reports"):
            payload = reports.archives()
        else:
            payload = reports.read(values)
        handler.send_json(200, payload)
        return True

    def handle_post(self, handler: Any, path: str) -> bool:
        if path == "/api/analysis/scenarios":
            handler.send_json(200, self._reports().scenarios(handler.read_json()))
            return True
        if path != "/api/analysis/reports":
            return False
        handler.send_json(200, self._reports().archive(handler.read_json()))
        return True
