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
            Route(
                "POST", "/api/analysis/refresh", Access.SESSION_CSRF, self._refresh_area
            ),
        ]

    def _report(self, handler: Any, request: RouteRequest) -> None:
        """Analysis projection: power profiles or training records.

        Request: `power-profiles` takes no query and no body. `training-records`
        takes the optional query `record_type` (only `equipment`) and `record_id`
        (a UUID, required with `record_type`); no body.

        Response: 200. `power-profiles`: `status` (`ok` or `insufficient_data`),
        `best`, `critical_power`, `power_meter_changes`, `activities`, `windows`
        (keys `28` and `90`), `running`, `method`, `method_version`,
        `input_fingerprint`, `scope` and `all_time` (the window of every stored
        session, for the analysis cards only). `training-records`: `{"equipment": object}`
        without query, `{"record_type": "equipment", "record": object}` for one
        record.

        Errors: `training-records` only: 400 "Unbekannte Datensatzart."; 400
        "Ungültige Datensatz-ID."; 503 "Einzelne Trainingsdatensätze sind nicht
        verfügbar.". `power-profiles`: none beyond the common ones.
        """
        path = request.path
        values = {key: value[0] for key, value in request.query.items()}
        reports = self._reports()
        if path.endswith("/training-records"):
            payload = reports.records.training_records(values)
        else:
            payload = reports.profiles.power_profiles(all_time=True)
        handler.send_json(200, payload)

    def _refresh_area(self, handler: Any, _request: RouteRequest) -> None:
        """Run a targeted refresh of one analysis area.

        Request: JSON body `{"area": string, "days": integer}`. `area` is required:
        `load`, `performance`, `recovery` or `sessions`. `days` is optional, `14` or
        `84`, and only for `load` and `recovery` (default 84 for `load`, 14 for
        `recovery`); the other areas use fixed windows.

        Response: 200 with `area`, `status` (`ok`, `partial`, `already_running` or
        `failed`), `refreshed_sources`, `incomplete_sources`, `pending_sources`,
        `not_refreshed_sources` (source names) and `source_status` (per source name
        its status string). Garmin is read for every area, Wahoo also for
        `sessions` and `performance`; a source that is not configured is left out.

        Errors: 400 "Ungültiger Analysebereich."; 400 "Ungültiger Analysezeitraum.";
        503 `analysis_refresh_unavailable` "Die gezielte Aktualisierung ist nicht
        verfügbar.".
        """
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
