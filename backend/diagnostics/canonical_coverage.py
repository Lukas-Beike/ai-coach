"""Counts-only summary of canonical provider coverage for diagnostics.

The summary carries provider identifiers, counts, reason identifiers, metric
identifiers, day lags and booleans: whether a sync time is stored and whether a
metric has stalled. A day lag is the number of days between a metric's newest
observation and its provider's newest observation, so it is relative, not a
date. The summary never carries dates, record content, values or mapping detail.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from backend.canonical.coverage import MetricWindow, ProviderCoverage
from backend.canonical.mapping import IssueReason
from backend.canonical.vocabulary import ProviderId
from backend.runtime.ports import ProviderCoverageReader

# A metric stalls when it has enough history to judge and its newest observation
# trails its provider's newest observation by at least a week.
STALL_MIN_OBSERVATIONS: Final = 5
STALL_LAG_DAYS: Final = 7


def summarize_canonical_coverage(
    reader: ProviderCoverageReader, db: Any
) -> dict[str, Any]:
    """Summarize provider coverage, or return an unavailable marker.

    A failing projection must not break the diagnostics report, so any failure
    yields ``{"status": "unavailable"}`` and nothing about the failure is kept.
    """
    try:
        coverage = reader.coverage(db)
        # Metrics are only attached to reported providers, so no providers, no query.
        windows = _windows_by_provider(reader.metric_windows(db)) if coverage else {}
        providers = [
            _provider_summary(item, windows.get(item.provider, [])) for item in coverage
        ]
    except Exception:  # noqa: BLE001 - a failing projection must not break diagnostics.
        return {"status": "unavailable"}
    return {"status": "available", "providers": providers}


def _windows_by_provider(
    windows: Sequence[MetricWindow],
) -> dict[ProviderId, list[MetricWindow]]:
    grouped: dict[ProviderId, list[MetricWindow]] = {}
    for window in windows:
        grouped.setdefault(window.provider, []).append(window)
    return grouped


def _provider_summary(
    item: ProviderCoverage, windows: Sequence[MetricWindow]
) -> dict[str, Any]:
    metrics = _metric_summaries(windows)
    return {
        "provider": str(item.provider),
        "sync_time_stored": item.retrieved_at is not None,
        "activities": item.activity_count,
        "observations": item.observation_count,
        # Every reason is reported, so an absent reason is an explicit zero.
        "issues": {
            str(reason): item.issue_counts.get(reason, 0) for reason in IssueReason
        },
        "metrics": metrics,
        "stalled_metrics": sum(1 for metric in metrics if metric["stalled"]),
    }


def _metric_summaries(windows: Sequence[MetricWindow]) -> list[dict[str, Any]]:
    """Return one entry per metric, sorted by metric, with its lag behind the provider."""
    if not windows:
        return []
    newest = max(window.newest_observed_on for window in windows)
    summaries: list[dict[str, Any]] = []
    for window in sorted(windows, key=lambda item: item.metric):
        lag_days = (newest - window.newest_observed_on).days
        summaries.append(
            {
                "metric": window.metric,
                "observations": window.observations,
                "lag_days": lag_days,
                "stalled": window.observations >= STALL_MIN_OBSERVATIONS
                and lag_days >= STALL_LAG_DAYS,
            }
        )
    return summaries
