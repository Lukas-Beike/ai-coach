"""Coordinate the two bounded provider reads used by an Analyse view."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from backend.errors import AppError

_SOURCE_NAMES = {
    "load": ("Intervals.icu-Belastungsdaten", "Garmin-Belastungswerte"),
    "performance": ("Intervals.icu-Leistungsdaten", "Garmin-Leistungswerte"),
    "recovery": ("Intervals.icu-Erholungsdaten", "Garmin-Erholungswerte"),
    "sessions": ("Intervals.icu-Aktivitätsübersicht", "Garmin-Aktivitätsübersicht"),
}


class AnalysisRefreshService:
    """Refresh the selected view and report each provider's outcome separately."""

    def __init__(
        self,
        performance_refresh: Callable[[], Any],
        sessions_refresh: Callable[[], Any],
        garmin_refresh: Callable[[], Any],
        local_today: Callable[[], date],
    ) -> None:
        self._performance_refresh = performance_refresh
        self._sessions_refresh = sessions_refresh
        self._garmin_refresh = garmin_refresh
        self._local_today = local_today

    def refresh(self, area: str, *, days: int | None = None) -> dict[str, Any]:
        if area not in _SOURCE_NAMES:
            raise AppError(400, "Ungültiger Analysebereich.")
        if days is not None and (
            area not in {"load", "recovery"} or days not in {14, 84}
        ):
            raise AppError(400, "Ungültiger Analysezeitraum.")
        names = _SOURCE_NAMES[area]
        outcomes: dict[str, dict[str, Any]] = {}
        if area == "sessions":
            intervals_refresh = lambda: self._sessions_refresh().refresh()
        else:
            intervals_refresh = lambda: self._performance_refresh().refresh(
                include_power_profile=area == "performance"
            )
        for name, action in (
            (names[0], intervals_refresh),
            (names[1], lambda: self._refresh_garmin(area, days)),
        ):
            try:
                outcomes[name] = action()
            except Exception:  # noqa: BLE001 - keep optional provider failures scoped.
                outcomes[name] = {"status": "failed"}

        refreshed = [
            name
            for name, result in outcomes.items()
            if result.get("status") in {"ok", "partial"}
            and (name != names[1] or any(result.get("sources", {}).values()))
        ]
        incomplete = [
            name for name in refreshed if outcomes[name].get("status") == "partial"
        ]
        pending = [
            name
            for name, result in outcomes.items()
            if result.get("status") == "already_running"
        ]
        missing = [
            name for name in names if name not in refreshed and name not in pending
        ]
        intervals = outcomes[names[0]]
        if intervals.get("truncated") and names[0] not in incomplete:
            incomplete.append(names[0])
        if intervals.get("reconciliation_pending") and names[0] not in incomplete:
            incomplete.append(names[0])
        status = (
            "ok"
            if len(refreshed) == len(names) and not incomplete
            else "partial"
            if refreshed
            else "already_running"
            if pending
            else "failed"
        )
        return {
            "area": area,
            "status": status,
            "refreshed_sources": refreshed,
            "incomplete_sources": incomplete,
            "pending_sources": pending,
            "not_refreshed_sources": missing,
            "truncated_sources": [names[0]] if intervals.get("truncated") else [],
            "source_status": {
                name: result.get("status", "failed")
                for name, result in outcomes.items()
            },
        }

    def _refresh_garmin(self, area: str, days: int | None) -> dict[str, Any]:
        end = self._local_today()
        window_days = (
            42
            if area == "sessions"
            else 90
            if area == "performance"
            else days or (14 if area == "recovery" else 84)
        )
        start = end - timedelta(days=window_days - 1)
        return self._garmin_refresh().refresh(area, start, end)
