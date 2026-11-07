"""State of the Intervals.icu ingest purge (#1728) for diagnostics.

It carries a state word (``pending``, ``waiting_for_rating_backfill``,
``done`` or ``done_restored``), the purge version and, once done, the purge counts; never ids, dates,
names or values.
"""

from __future__ import annotations

from typing import Any

from backend.db.repositories import KeyValueRepository
from backend.sync.intervals_purge import purge_status


def summarize_intervals_purge(
    key_values: KeyValueRepository, db: Any, *, marker_exists: bool = False
) -> dict[str, Any]:
    """Summarize the purge; a failing read yields ``{"status": "unavailable"}``.

    ``marker_exists`` tells whether the data directory holds the purge marker.
    """
    try:
        return purge_status(db, key_values, marker_exists=marker_exists)
    except Exception:  # noqa: BLE001 - a failing read must not break diagnostics.
        return {"status": "unavailable"}
