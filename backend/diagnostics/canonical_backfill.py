"""Counts-only summary of the canonical backfill for diagnostics.

The summary carries a status word, batch count, per-provider counters and the
number of unresolved feedback rows. It never carries ids, dates, names or values.
"""

from __future__ import annotations

from typing import Any, Protocol


class CanonicalBackfillStatusReader(Protocol):
    def summary(self, db: Any) -> dict[str, Any]: ...


def summarize_canonical_backfill(
    reader: CanonicalBackfillStatusReader | None, db: Any
) -> dict[str, Any]:
    """Summarize the backfill, or return an unavailable marker.

    A failing status read must not break the diagnostics report, so any failure
    yields ``{"status": "unavailable"}`` and nothing about the failure is kept.
    """
    if reader is None:
        return {"status": "unavailable"}
    try:
        summary = reader.summary(db)
        providers = {
            str(name): {str(counter): int(value) for counter, value in counters.items()}
            for name, counters in summary["providers"].items()
        }
        return {
            "status": str(summary["status"]),
            "batches": int(summary["batches"]),
            "unresolved_feedback": int(summary["unresolved_feedback"]),
            "providers": providers,
        }
    except Exception:  # noqa: BLE001 - a failing status read must not break diagnostics.
        return {"status": "unavailable"}
