"""Coordinate the bounded provider reads used by an Analyse view."""

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


# Names of the Wahoo read per Analyse area; the other areas have no Wahoo data.
_WAHOO_SOURCE_NAMES = {
    "sessions": "Wahoo-Aktivitätsübersicht",
    "performance": "Wahoo-Leistungswerte",
}
_WAHOO_WINDOW_DAYS = {"sessions": 42, "performance": 90}


class AnalysisRefreshService:
    """Refresh the selected view and report each configured source separately.

    Garmin reads the area's endpoints; Wahoo adds its workout read for the
    activity and performance areas. A source that is not configured is neither
    refreshed nor reported as missing.
    """

    def __init__(
        self,
        garmin_refresh: Callable[[], Any],
        local_today: Callable[[], date],
        wahoo_sync: Callable[[], Any] | None = None,
    ) -> None:
        self._garmin_refresh = garmin_refresh
        self._local_today = local_today
        self._wahoo_sync = wahoo_sync

    def refresh(self, area: str, *, days: int | None = None) -> dict[str, Any]:
        _validate_request(area, days)
        outcomes = self._run_refreshes(area, days)
        refreshed, incomplete, pending, missing = [], [], [], []
        for name, outcome in outcomes.items():
            status = outcome.get("status")
            if status in {"ok", "partial"} and outcome.get("read"):
                refreshed.append(name)
                if status == "partial":
                    incomplete.append(name)
            elif status == "already_running":
                pending.append(name)
            else:
                missing.append(name)
        return {
            "area": area,
            "status": _overall_status(
                bool(refreshed), bool(incomplete or missing), bool(pending)
            ),
            "refreshed_sources": refreshed,
            "incomplete_sources": incomplete,
            "pending_sources": pending,
            "not_refreshed_sources": missing,
            "truncated_sources": [],
            "source_status": {
                name: outcome.get("status") or "failed"
                for name, outcome in outcomes.items()
            },
        }

    def _run_refreshes(self, area: str, days: int | None) -> dict[str, dict[str, Any]]:
        outcomes: dict[str, dict[str, Any]] = {}
        garmin = self._guarded(lambda: self._refresh_garmin(area, days))
        if garmin.get("reason") != "not_configured":
            outcomes[_SOURCE_NAMES[area]] = {
                **garmin,
                "read": any(garmin.get("sources", {}).values()),
            }
        wahoo = self._wahoo_sync() if self._wahoo_sync is not None else None
        if (
            wahoo is not None
            and area in _WAHOO_SOURCE_NAMES
            and self._guarded(wahoo.configured) is True
        ):
            result = self._guarded(
                lambda: wahoo.sync(_WAHOO_WINDOW_DAYS[area], "Analyse-Aktualisierung")
            )
            outcomes[_WAHOO_SOURCE_NAMES[area]] = {**result, "read": True}
        return outcomes

    @staticmethod
    def _guarded(action: Callable[[], Any]) -> Any:
        try:
            return action()
        except Exception:  # noqa: BLE001 - keep optional provider failures scoped.
            return {"status": "failed"}

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
