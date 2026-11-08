"""Counts-only summary of the stream backfill (#1763) for diagnostics.

It carries counts and a state word per provider, never ids, dates or names.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.canonical.vocabulary import ProviderId
from backend.db.repositories import KeyValueRepository
from backend.sync.stream_backfill import stream_backfill_counts

_PROVIDERS = (ProviderId.GARMIN.value, ProviderId.WAHOO.value)


def summarize_stream_backfill(
    key_values: KeyValueRepository, db: Any, earliest: date | None = None
) -> dict[str, Any]:
    """Summarize both providers; a failing read yields ``{"status": "unavailable"}``.

    ``earliest`` is the history floor the job applies.
    """
    try:
        return {
            provider: stream_backfill_counts(db, key_values, provider, earliest)
            for provider in _PROVIDERS
        }
    except Exception:  # noqa: BLE001 - a failing read must not break diagnostics.
        return {"status": "unavailable"}
