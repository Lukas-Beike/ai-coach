"""Counts-only summary of the canonical read switch for diagnostics.

The summary names the serving source, the reason word, whether the stored check is
for the current digest, and the parity counts. It never carries ids, dates, names,
values, digests or exception text.
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
        parity = summary.get("parity")
        return {
            "serving": str(summary["serving"]),
            "reason": str(summary["reason"]),
            "digest_current": bool(summary["digest_current"]),
            "parity": None if parity is None else _parity_counts(parity),
        }
    except Exception:  # noqa: BLE001 - a failing status read must not break diagnostics.
        return {"status": "unavailable"}


def _parity_counts(parity: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": bool(parity["passed"]),
        "ordering_equal": bool(parity["ordering_equal"]),
        "fingerprint_mismatches": int(parity["fingerprint"]["mismatches"]),
        "activities": _counter_groups(parity["activities"]),
        "observations": _counter_groups(parity["observations"]),
    }


def _counter_groups(groups: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        str(name): {str(counter): int(value) for counter, value in counts.items()}
        for name, counts in groups.items()
    }
