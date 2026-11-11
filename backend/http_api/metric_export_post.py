"""Authenticated automatic metric export configuration route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.sync.metric_export import MetricExportService


class MetricExportPostRoutes:
    """Switch the automatic metric export on explicit, confirmed consent."""

    def __init__(self, metric_export: Callable[[], MetricExportService]) -> None:
        self._metric_export = metric_export

    def handle(self, handler: Any, path: str) -> bool:
        if path == "/api/metric-export/automatic":
            handler.send_json(
                200, self._metric_export().configure_automatic(handler.read_json())
            )
            return True
        return False
