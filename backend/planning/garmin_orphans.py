"""Garmin workouts this app sent for planned units that no longer exist.

Read-only projection over ``remote_links`` (provider ``garmin``, entity
``planned_unit``) joined to the stored units. A link is an orphan when its unit is
missing, tombstoned, archived, deleted, no longer a strength unit or a strength
unit that cannot be pushed any more (no valid structure, or an exercise without
a Garmin match; a unit with an unreadable payload is damaged, not an orphan), so
the workout and schedule it names would stay in Garmin Connect for good. Only
linked ids are ever listed; a Garmin workout without a link is never a
candidate. The explicit Garmin sync removes the listed orphans.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.canonical.vocabulary import ProviderId, RemoteEntityKind, Sport
from backend.planning.exercise_mappings import remembered_exercises
from backend.planning.leftovers import MAX_CLEANUP, cap, nearest_first
from backend.planning.push_state import pushable_fingerprint
from backend.planning.sport import planned_sport_environment
from backend.providers.garmin_strength_workout import GarminExercise

_UNKNOWN_NAME: Final = "Gelöschte Einheit"


@dataclass(frozen=True)
class GarminOrphan:
    local_id: str
    name: str
    date: str


def _label(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return _UNKNOWN_NAME, ""
    name = str(payload.get("name") or "").strip()[:120] or _UNKNOWN_NAME
    day = str(payload.get("date") or "")[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        day = ""
    return name, day


def _is_orphan(
    row: Any, payload: Any, remembered: Mapping[str, GarminExercise]
) -> bool:
    if row["unit_id"] is None or row["tombstone"]:
        return True
    if not isinstance(payload, dict):
        # An unreadable payload is a damaged unit, not a deleted one.
        return False
    if payload.get("local_deleted") or payload.get("archived"):
        return True
    sport, _environment = planned_sport_environment(payload)
    if sport is not Sport.STRENGTH:
        return True
    # A live strength unit that is blocked (empty or unmappable structure) can no
    # longer replace its pushed workout, which would stay on the watch.
    return pushable_fingerprint(payload, remembered)[0] is None


def find_orphans(
    db: Any, today: date, *, limit: int | None = MAX_CLEANUP
) -> tuple[list[GarminOrphan], int]:
    """Return up to ``limit`` orphans, nearest day first, and the total count."""
    orphans: list[GarminOrphan] = []
    remembered = remembered_exercises(db)
    for row in db.execute(
        "SELECT l.local_id AS link_id, p.local_id AS unit_id, p.payload, p.tombstone "
        "FROM remote_links l LEFT JOIN planned_units p ON p.local_id = l.local_id "
        "WHERE l.provider=? AND l.entity_kind=?",
        (ProviderId.GARMIN.value, RemoteEntityKind.PLANNED_UNIT.value),
    ).fetchall():
        try:
            payload = json.loads(row["payload"] or "{}")
        except TypeError, ValueError:
            payload = None
        if _is_orphan(row, payload, remembered):
            name, day = _label(payload)
            orphans.append(GarminOrphan(row["link_id"], name, day))
    ordered = nearest_first(orphans, today, lambda item: item.date)
    return cap(ordered, limit), len(ordered)


def removal_entries(orphans: list[GarminOrphan]) -> list[dict[str, Any]]:
    """The ``remove`` entries of a Garmin plan_push job for these orphans."""
    return [{"library_workout_id": item.local_id, "remove": True} for item in orphans]
