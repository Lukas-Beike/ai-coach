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
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.runtime.ports import ProviderCoverageReader

# A metric stalls when it has enough history to judge and its newest observation
# trails its provider's newest observation by at least a week and by three times
# the mean spacing of its own observations, so metrics recorded on purpose only
# weekly or monthly are not reported as stalled.
STALL_MIN_OBSERVATIONS: Final = 5
STALL_LAG_DAYS: Final = 7
STALL_CADENCE_FACTOR: Final = 3
# Event-driven metrics update only after a test or qualifying activity, so their
# irregular gaps are never judged as stalls.
EVENT_DRIVEN_METRICS: Final = frozenset(
    kind.value
    for kind in (
        MetricKind.FTP,
        MetricKind.EFTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.MAX_HR,
        MetricKind.VO2MAX,
        MetricKind.THRESHOLD_PACE,
        MetricKind.RUN_THRESHOLD_POWER,
        MetricKind.RACE_PREDICTION_5K,
        MetricKind.RACE_PREDICTION_10K,
        MetricKind.RACE_PREDICTION_HALF,
        MetricKind.RACE_PREDICTION_FULL,
        MetricKind.ENDURANCE_SCORE,
    )
)


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
        "activity_sync_time_stored": item.activities_retrieved_at is not None,
        "observation_sync_time_stored": item.observations_retrieved_at is not None,
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
                "stalled": _is_stalled(window, lag_days),
            }
        )
    return summaries


def _is_stalled(window: MetricWindow, lag_days: int) -> bool:
    """Judge the lag against the metric's own cadence, never against a daily one."""
    if (
        window.metric in EVENT_DRIVEN_METRICS
        or window.observations < STALL_MIN_OBSERVATIONS
    ):
        return False
    # At least STALL_MIN_OBSERVATIONS observations, so the divisor is never zero.
    gap_days = (window.newest_observed_on - window.oldest_observed_on).days / (
        window.observations - 1
    )
    return lag_days >= max(STALL_LAG_DAYS, STALL_CADENCE_FACTOR * gap_days)
