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

from backend.db import planning_store
from backend.planning.leftovers import MAX_CLEANUP, cap, nearest_first
from backend.planning.library import library_payload_hash

_OPEN_STATES: Final = ("local", "sync_error", "remote_missing")


@dataclass(frozen=True)
class IntervalsOrphan:
    local_id: str
    name: str
    date: str
    payload_hash: str


def _orphan(row: Any, today: date) -> IntervalsOrphan | None:
    """The orphan a stored unit makes, or None for a live, past or unlinked one."""
    try:
        payload = json.loads(row["payload"] or "{}")
    except TypeError, ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    hidden = payload.get("local_deleted") or payload.get("archived")
    remote_id = payload.get("remote_event_id")
    if not hidden or isinstance(remote_id, bool) or not str(remote_id or "").strip():
        return None
    try:
        day = date.fromisoformat(str(payload.get("date") or "")[:10])
    except ValueError:
        return None
    if day < today:
        return None
    name = str(payload.get("name") or "").strip()[:120] or "Einheit"
    return IntervalsOrphan(
        row["local_id"], name, day.isoformat(), library_payload_hash(row["payload"])
    )


def find_intervals_orphans(
    db: Any, today: date, *, limit: int | None = MAX_CLEANUP
) -> tuple[list[IntervalsOrphan], int]:
    """Return up to ``limit`` orphans, nearest day first, and the total count."""
    rows = planning_store.planned_unit_rows_in_states(db, _OPEN_STATES)
    orphans = [
        item for row in rows if not row["tombstone"] and (item := _orphan(row, today))
    ]
    ordered = nearest_first(orphans, today, lambda item: item.date)
    return cap(ordered, limit), len(ordered)


def leftover_ids(db: Any, local_ids: set[str]) -> set[str]:
    """The given ids that are leftovers: hidden units still holding their event.

    Any day counts: the plan selection checks entries the Coach proposal added,
    which ``find_intervals_orphans`` already limited to upcoming days (#2373).
    """
    if not local_ids:
        return set()
    rows = planning_store.planned_unit_rows_by_ids(db, sorted(local_ids))
    return {
        row["local_id"]
        for row in rows
        if not row["tombstone"] and _orphan(row, date.min)
    }


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
