"""Counts-only summary of canonical provider coverage for diagnostics.

The summary carries provider identifiers, counts, reason identifiers and a
boolean for whether a sync time is stored. It never carries dates, record
content, values or mapping detail.
"""

from __future__ import annotations

from typing import Any

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.mapping import IssueReason
from backend.runtime.ports import ProviderCoverageReader


def summarize_canonical_coverage(
    reader: ProviderCoverageReader, db: Any
) -> dict[str, Any]:
    """Summarize provider coverage, or return an unavailable marker.

    A failing projection must not break the diagnostics report, so any failure
    yields ``{"status": "unavailable"}`` and nothing about the failure is kept.
    """
    try:
        providers = [_provider_summary(item) for item in reader.coverage(db)]
    except Exception:  # noqa: BLE001 - a failing projection must not break diagnostics.
        return {"status": "unavailable"}
    return {"status": "available", "providers": providers}


def _provider_summary(item: ProviderCoverage) -> dict[str, Any]:
    return {
        "provider": str(item.provider),
        "sync_time_stored": item.retrieved_at is not None,
        "activities": item.activity_count,
        "observations": item.observation_count,
        # Every reason is reported, so an absent reason is an explicit zero.
        "issues": {
            str(reason): item.issue_counts.get(reason, 0) for reason in IssueReason
        },
    }
