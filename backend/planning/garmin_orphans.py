"""Garmin workouts this app sent for planned units that no longer exist.

Read-only projection over ``remote_links`` (provider ``garmin``, entity
``planned_unit``) and the stored units. A link is an orphan when its unit is
missing, tombstoned, archived, deleted or no longer a strength unit, so the
workout and schedule it names would stay in Garmin Connect for good. Only
linked ids are ever listed; a Garmin workout without a link is never a
candidate. The explicit Garmin sync removes the listed orphans.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.canonical.vocabulary import ProviderId, RemoteEntityKind, Sport
from backend.db.remote_links import RemoteLinkRepository
from backend.planning.sport import planned_sport_environment

# One sync job takes at most 28 entries; the rest waits for the next sync.
MAX_CLEANUP: Final = 20
_REMOTE_LINKS = RemoteLinkRepository()
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


def _is_orphan(row: Any, payload: Any) -> bool:
    if row is None or row["tombstone"] or not isinstance(payload, dict):
        return True
    if payload.get("local_deleted") or payload.get("archived"):
        return True
    sport, _environment = planned_sport_environment(payload)
    return sport is not Sport.STRENGTH


def find_orphans(
    db: Any, *, limit: int | None = MAX_CLEANUP
) -> tuple[list[GarminOrphan], int]:
    """Return up to ``limit`` orphans, latest day first, and the total count."""
    orphans: list[GarminOrphan] = []
    for link in _REMOTE_LINKS.list_for_provider(
        db, ProviderId.GARMIN.value, RemoteEntityKind.PLANNED_UNIT
    ):
        row = db.execute(
            "SELECT payload, tombstone FROM planned_units WHERE local_id=?",
            (link.local_id,),
        ).fetchone()
        try:
            payload = json.loads(row["payload"] or "{}") if row else None
        except TypeError, ValueError:
            payload = None
        if _is_orphan(row, payload):
            name, day = _label(payload)
            orphans.append(GarminOrphan(link.local_id, name, day))
    # Latest day first, so upcoming duplicates go before old history.
    ordered = sorted(orphans, key=lambda item: item.date, reverse=True)
    return (ordered if limit is None else ordered[:limit]), len(ordered)


def removal_entries(orphans: list[GarminOrphan]) -> list[dict[str, Any]]:
    """The ``remove`` entries of a Garmin plan_push job for these orphans."""
    return [{"library_workout_id": item.local_id, "remove": True} for item in orphans]
