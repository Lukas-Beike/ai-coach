"""Intervals.icu events this app created for planned units that no longer exist.

Read-only projection over the stored units. A unit that was archived or deleted
(a Coach replan archives the replaced unit) still holds the id of its calendar
event until an explicit Intervals.icu sync removes it, and the athlete cannot
select a hidden unit in the calendar. Intervals.icu keeps forwarding such an
event to Garmin. Only events linked to a stored unit are listed, never foreign
ones; past events are skipped, because the sync refuses to delete them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.planning.leftovers import MAX_CLEANUP, cap, nearest_first
from backend.planning.library import library_payload_hash

_OPEN_STATES: Final = ("local", "sync_error", "remote_missing")


@dataclass(frozen=True)
class IntervalsOrphan:
    local_id: str
    name: str
    date: str
    payload_hash: str


def find_intervals_orphans(
    db: Any, today: date, *, limit: int | None = MAX_CLEANUP
) -> tuple[list[IntervalsOrphan], int]:
    """Return up to ``limit`` orphans, nearest day first, and the total count."""
    orphans: list[IntervalsOrphan] = []
    marks = ", ".join("?" for _ in _OPEN_STATES)
    for row in db.execute(
        "SELECT local_id, payload FROM planned_units "
        f"WHERE tombstone=0 AND sync_state IN ({marks})",
        _OPEN_STATES,
    ).fetchall():
        try:
            payload = json.loads(row["payload"] or "{}")
        except TypeError, ValueError:
            continue
        if not isinstance(payload, dict) or not (
            payload.get("local_deleted") or payload.get("archived")
        ):
            continue
        remote_id = payload.get("remote_event_id")
        if isinstance(remote_id, bool) or not str(remote_id or "").strip():
            continue
        try:
            day = date.fromisoformat(str(payload.get("date") or "")[:10])
        except ValueError:
            continue
        if day >= today:
            orphans.append(
                IntervalsOrphan(
                    row["local_id"],
                    str(payload.get("name") or "").strip()[:120] or "Einheit",
                    day.isoformat(),
                    library_payload_hash(row["payload"]),
                )
            )
    ordered = nearest_first(orphans, today, lambda item: item.date)
    return cap(ordered, limit), len(ordered)


def sync_entries(orphans: list[IntervalsOrphan]) -> list[dict[str, Any]]:
    """The entries of an Intervals.icu ``plan_push`` job that remove these events."""
    return [
        {
            "library_workout_id": item.local_id,
            "expected_payload_hash": item.payload_hash,
            "entity": "planned_unit",
        }
        for item in orphans
    ]
