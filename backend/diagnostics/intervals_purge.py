"""State of the Intervals.icu ingest purge (#1728) for diagnostics.

It carries a state word (``pending``, ``waiting_for_rating_backfill`` or
``done``), the purge version and, once done, the purge counts; never ids, dates,
names or values.
"""

from __future__ import annotations

from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.sync.intervals_purge import purge_status


def summarize_intervals_purge(
    key_values: KeyValueRepository, db: Any
) -> dict[str, Any]:
    """Summarize the purge; a failing read yields ``{"status": "unavailable"}``."""
    try:
        return purge_status(db, key_values)
    except Exception:  # noqa: BLE001 - a failing read must not break diagnostics.
        return {"status": "unavailable"}
