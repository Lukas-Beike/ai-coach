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
        _validate_request(area, days)
        names = _SOURCE_NAMES[area]
        outcomes = self._run_refreshes(area, days, names)
        refreshed, incomplete, pending, missing = _classify_outcomes(names, outcomes)
        intervals = outcomes[names[0]]
        return {
            "area": area,
            "status": _overall_status(len(names), refreshed, incomplete, pending),
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

    def _run_refreshes(
        self, area: str, days: int | None, names: tuple[str, str]
    ) -> dict[str, dict[str, Any]]:
        outcomes: dict[str, dict[str, Any]] = {}
        for name, action in (
            (names[0], lambda: self._refresh_intervals(area)),
            (names[1], lambda: self._refresh_garmin(area, days)),
        ):
            try:
                outcomes[name] = action()
            except Exception:  # noqa: BLE001 - keep optional provider failures scoped.
                outcomes[name] = {"status": "failed"}
        return outcomes

    def _refresh_intervals(self, area: str) -> dict[str, Any]:
        if area == "sessions":
            return self._sessions_refresh().refresh()
        return self._performance_refresh().refresh(
            include_power_profile=area == "performance"
        )

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


def _validate_request(area: str, days: int | None) -> None:
    if area not in _SOURCE_NAMES:
        raise AppError(400, "Ung\u00fcltiger Analysebereich.")
    if days is not None and (area not in {"load", "recovery"} or days not in {14, 84}):
        raise AppError(400, "Ung\u00fcltiger Analysezeitraum.")


def _classify_outcomes(
    names: tuple[str, str], outcomes: dict[str, dict[str, Any]]
) -> tuple[list[str], list[str], list[str], list[str]]:
    refreshed = [
        name
        for name, result in outcomes.items()
        if result.get("status") in {"ok", "partial"}
        and (name == names[0] or any(result.get("sources", {}).values()))
    ]
    incomplete = [
        name for name in refreshed if outcomes[name].get("status") == "partial"
    ]
    intervals = outcomes[names[0]]
    if (
        intervals.get("truncated") or intervals.get("reconciliation_pending")
    ) and names[0] not in incomplete:
        incomplete.append(names[0])
    pending = [
        name
        for name, result in outcomes.items()
        if result.get("status") == "already_running"
    ]
    missing = [name for name in names if name not in refreshed and name not in pending]
    return refreshed, incomplete, pending, missing


def _overall_status(
    source_count: int,
    refreshed: list[str],
    incomplete: list[str],
    pending: list[str],
) -> str:
    if len(refreshed) == source_count and not incomplete:
        return "ok"
    if refreshed:
        return "partial"
    if pending:
        return "already_running"
    return "failed"
