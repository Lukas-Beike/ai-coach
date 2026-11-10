"""Wahoo plans this app sent for library entries that no longer exist.

Read-only projection over ``remote_links`` (provider ``wahoo``, entity
``library_workout``). Deleting a library entry, or undoing its creation, keeps
the Wahoo link because it is the only record of the plan id. A link whose
library entry is gone is an orphan: the plan stays in the Wahoo account until
the athlete's explicit Wahoo sync removes it. Only linked ids are ever listed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from backend.canonical.vocabulary import RemoteEntityKind
from backend.planning.leftovers import MAX_CLEANUP, cap
from backend.providers.descriptors import WAHOO_ID

# The plan's name is not stored once the entry is deleted.
_UNKNOWN_NAME: Final = "Gelöschter Wahoo-Plan"


@dataclass(frozen=True)
class WahooOrphan:
    local_id: str
    name: str = _UNKNOWN_NAME
    date: str = ""


def find_wahoo_orphans(
    db: Any, *, limit: int | None = MAX_CLEANUP
) -> tuple[list[WahooOrphan], int]:
    """Return up to ``limit`` orphans and the total count."""
    orphans = [
        WahooOrphan(row["local_id"])
        for row in db.execute(
            "SELECT l.local_id FROM remote_links l "
            "LEFT JOIN workout_library w ON w.local_id = l.local_id "
            "WHERE l.provider=? AND l.entity_kind=? AND w.local_id IS NULL "
            "ORDER BY l.local_id",
            (WAHOO_ID, RemoteEntityKind.LIBRARY_WORKOUT.value),
        ).fetchall()
    ]
    return cap(orphans, limit), len(orphans)
