"""Coordinate the bounded provider read used by an Analyse view."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend.errors import AppError

_SOURCE_NAMES = {
    "load": "Garmin-Belastungswerte",
    "performance": "Garmin-Leistungswerte",
    "recovery": "Garmin-Erholungswerte",
    "sessions": "Garmin-Aktivitätsübersicht",
}


class AnalysisRefreshService:
    """Refresh the selected view and report the provider's outcome."""

    def __init__(
        self,
        garmin_refresh: Callable[[], Any],
        local_today: Callable[[], date],
    ) -> None:
        self._garmin_refresh = garmin_refresh
        self._local_today = local_today

    def refresh(self, area: str, *, days: int | None = None) -> dict[str, Any]:
        _validate_request(area, days)
        name = _SOURCE_NAMES[area]
        try:
            outcome = self._refresh_garmin(area, days)
        except Exception:  # noqa: BLE001 - keep optional provider failures scoped.
            outcome = {"status": "failed"}
        status = outcome.get("status")
        refreshed = status in {"ok", "partial"} and any(
            outcome.get("sources", {}).values()
        )
        incomplete = refreshed and status == "partial"
        pending = status == "already_running"
        return {
            "area": area,
            "status": _overall_status(refreshed, incomplete, pending),
            "refreshed_sources": [name] if refreshed else [],
            "incomplete_sources": [name] if incomplete else [],
            "pending_sources": [name] if pending else [],
            "not_refreshed_sources": [] if refreshed or pending else [name],
            "truncated_sources": [],
            "source_status": {name: status or "failed"},
        }

    def _refresh_garmin(self, area: str, days: int | None) -> dict[str, Any]:
        end = self._local_today()
        if area == "sessions":
            window_days = 42
        elif area == "performance":
            window_days = 90
        elif area == "recovery":
            window_days = days or 14
        else:
            window_days = days or 84
        start = end - timedelta(days=window_days - 1)
        return self._garmin_refresh().refresh(area, start, end)


def _validate_request(area: str, days: int | None) -> None:
    if area not in _SOURCE_NAMES:
        raise AppError(400, "Ungültiger Analysebereich.")
    if days is not None and (area not in {"load", "recovery"} or days not in {14, 84}):
        raise AppError(400, "Ungültiger Analysezeitraum.")


def _overall_status(refreshed: bool, incomplete: bool, pending: bool) -> str:
    if refreshed and not incomplete:
        return "ok"
    if refreshed:
        return "partial"
    if pending:
        return "already_running"
    return "failed"
