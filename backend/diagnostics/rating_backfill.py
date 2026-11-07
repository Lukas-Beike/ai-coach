"""Counts-only summary of the Garmin rating backfill (#1728) for diagnostics.

It carries counts and a state word, never ids, dates, names or rating values.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.sync.garmin_rating_backfill import rating_backfill_counts


def summarize_rating_backfill(
    key_values: KeyValueRepository, db: Any, earliest: date | None = None
) -> dict[str, Any]:
    """Summarize the backfill; a failing read yields ``{"status": "unavailable"}``.

    ``earliest`` is the history floor the job applies.
    """
    try:
        return rating_backfill_counts(db, key_values, earliest)
    except Exception:  # noqa: BLE001 - a failing read must not break diagnostics.
        return {"status": "unavailable"}
