"""Freshness of the stored activities, read from canonical provider coverage."""

from __future__ import annotations

from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.runtime.ports import ProviderCoverageReader


def activities_synced_at(
    coverage: ProviderCoverageReader | None, db: Any
) -> str | None:
    """Return when the Intervals.icu activities were last fetched, or None if unknown.

    The time is the one persisted with the canonical coverage at ingest; the stored
    snapshot's own timestamp is never consulted.
    """
    if coverage is None:
        return None
    for summary in coverage.coverage(db):
        if (
            summary.provider is ProviderId.INTERVALS
            and summary.activities_retrieved_at is not None
        ):
            return summary.activities_retrieved_at.isoformat()
    return None
