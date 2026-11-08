"""Freshness of stored provider data, read from canonical provider coverage."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

from backend.canonical.vocabulary import ProviderId
from backend.runtime.ports import ProviderCoverageReader


def intervals_synced_at(coverage: ProviderCoverageReader | None, db: Any) -> str | None:
    """Return when Intervals.icu data was last fetched, or None if unknown.

    The time is the newest fetch persisted with the canonical coverage at ingest;
    the stored snapshot's own timestamp is never consulted.
    """
    if coverage is None:
        return None
    for summary in coverage.coverage(db):
        if (
            summary.provider is ProviderId.INTERVALS
            and summary.retrieved_at is not None
        ):
            return summary.retrieved_at.isoformat()
    return None


# Providers whose activity fetch bounds the days that may still lack sessions.
# Intervals.icu is an output target; its stored copies never bound them.
ACTIVITY_PROVIDERS: Final = (ProviderId.GARMIN, ProviderId.WAHOO)
# A provider whose last current fetch is this much older than the newest one has
# stopped syncing (disconnected, or never used again) and no longer holds the
# boundary back.
STALLED_AFTER: Final = timedelta(days=14)


def activities_synced_at(
    coverage: ProviderCoverageReader | None, db: Any
) -> str | None:
    """Return the oldest current activity fetch of the active providers, or None.

    Each provider's time is its newest complete activity read that reached today,
    persisted with its canonical coverage. Days after the returned time may still
    lack sessions of some provider. A provider fetched more than ``STALLED_AFTER``
    before the newest one is left out.
    """
    if coverage is None:
        return None
    fetched = [
        summary.activities_retrieved_at
        for summary in coverage.coverage(db)
        if summary.provider in ACTIVITY_PROVIDERS
        and summary.activities_retrieved_at is not None
    ]
    if not fetched:
        return None
    newest = max(fetched)
    return min(time for time in fetched if newest - time <= STALLED_AFTER).isoformat()
