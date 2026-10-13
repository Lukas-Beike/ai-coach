"""Counts-only summary of the canonical read switch for diagnostics.

The summary names the serving source, the reason word (``backfill_complete`` while
the tables serve, ``backfill_pending`` while legacy serves before the first
completed backfill) and whether the tables are projected with the current mappers
and time zone. It never carries ids, dates, names, values, digests or exception
text.
"""

from __future__ import annotations

from typing import Any, Protocol


class CanonicalReadStatusReader(Protocol):
    def summary(self, db: Any) -> dict[str, Any]: ...


def summarize_canonical_read(
    reader: CanonicalReadStatusReader | None, db: Any
) -> dict[str, Any]:
    """Summarize the read switch, or return an unavailable marker.

    A failing status read must not break the diagnostics report, so any failure
    yields ``{"status": "unavailable"}`` and nothing about the failure is kept.
    """
    if reader is None:
        return {"status": "unavailable"}
    try:
        summary = reader.summary(db)
        return {
            "serving": str(summary["serving"]),
            "reason": str(summary["reason"]),
            "digest_current": bool(summary["digest_current"]),
        }
    except Exception:  # noqa: BLE001 - a failing status read must not break diagnostics.
        return {"status": "unavailable"}
