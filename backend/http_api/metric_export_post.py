"""Authenticated automatic metric export configuration route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.sync.metric_export import MetricExportService


class MetricExportPostRoutes:
    """Switch the automatic metric export on explicit, confirmed consent."""

    def __init__(self, metric_export: Callable[[], MetricExportService]) -> None:
        self._metric_export = metric_export

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST",
                "/api/metric-export/automatic",
                Access.SESSION_CSRF,
                self._automatic,
            )
        ]

    def _automatic(self, handler: Any, _request: RouteRequest) -> None:
        """Intervals.icu write: switch the automatic metric export (consent per field); needs `confirmed: true`, a boolean `enabled`, `source: "garmin"` and `provider: "intervals"`."""
        handler.send_json(
            200, self._metric_export().configure_automatic(handler.read_json())
        )
