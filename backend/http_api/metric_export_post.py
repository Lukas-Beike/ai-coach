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
        """Intervals.icu write: switch the automatic metric export (consent per field).

        Request: JSON body `{"confirmed": true, "enabled": boolean, "source":
        "garmin", "provider": "intervals"}`, all four required. Optional `fields`:
        non-empty list of export field keys (`weight`, `body_fat`, `resting_hr`,
        `threshold_pace`, `threshold_hr`, `max_hr`, `ftp`, `run_ftp`), or `field`
        with a boolean `field_enabled` to change one field against the stored
        consent (not together with `fields`). Without either, enabling keeps the
        stored fields or starts with `threshold_pace`, `threshold_hr` and `max_hr`;
        `enabled: false` revokes every field.

        Response: 200 `{"enabled", "fields", "changes"}`; `fields` lists every
        export field as `{"key", "label", "enabled"}`, `changes` the entries whose
        consent changed.

        Errors: 400 `confirmation_required` "Der automatische Abgleich mit
        Intervals.icu muss ausdrücklich bestätigt werden." when `confirmed`,
        `provider`, `source` or `enabled` is missing or wrong; 400
        `invalid_metric_export` "Die Auswahl der Werte ist ungültig." for an invalid
        `fields`, `field` or `field_enabled`.
        """
        handler.send_json(
            200, self._metric_export().configure_automatic(handler.read_json())
        )
