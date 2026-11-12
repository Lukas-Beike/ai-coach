"""Diagnostic projection of the last sync and plan sync of each active provider."""

from __future__ import annotations

from typing import Any, Final

from backend.canonical.vocabulary import GARMIN_ID, INTERVALS_ID, WAHOO_ID

_INPUT_PROVIDERS: Final = (GARMIN_ID, WAHOO_ID)
_PLAN_PUSH: Final = "plan_push"


def summarize_provider_sync(db: Any) -> dict[str, dict[str, str | None]]:
    """Report timestamps only, never provider text.

    ``last_sync_at`` is the last successful refresh of Garmin and Wahoo. For
    Intervals.icu, which is an output target and is never read, it is the last
    completed push job of any type. ``last_plan_sync_at`` is the last completed
    ``plan_push`` job of each provider.
    """
    refreshes = {
        row["provider"]: row["finished_at"]
        for row in db.execute(
            "SELECT provider, MAX(finished_at) AS finished_at "
            "FROM provider_refresh_history "
            "WHERE status IN ('success', 'partial') GROUP BY provider"
        ).fetchall()
    }
    pushes: dict[str, dict[str, str]] = {}
    for row in db.execute(
        "SELECT provider, type, MAX(finished_at) AS finished_at FROM sync_jobs "
        "WHERE status = 'completed' AND finished_at IS NOT NULL "
        "GROUP BY provider, type"
    ).fetchall():
        pushes.setdefault(row["provider"], {})[row["type"]] = row["finished_at"]
    report: dict[str, dict[str, str | None]] = {}
    for provider in (*_INPUT_PROVIDERS, INTERVALS_ID):
        jobs = pushes.get(provider, {})
        report[provider] = {
            "last_sync_at": (
                refreshes.get(provider)
                if provider in _INPUT_PROVIDERS
                else max(jobs.values(), default=None)
            ),
            "last_plan_sync_at": jobs.get(_PLAN_PUSH),
        }
    return report
