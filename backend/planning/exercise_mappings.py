"""Garmin exercises the athlete confirmed, remembered per exercise name.

A structure exercise that names its Garmin catalogue exercise explicitly
(``garmin_exercise``, set by the Coach after asking or picked in the unit
editor) stores the resolved pair. That confirmation also applies to the same
exercise name in other units, so it is asked once. Nothing extra is stored: the
mappings are read from the local planned units and library templates, newest
first; deleted units do not count. Read-only.
"""

from __future__ import annotations

import json
from typing import Any

from backend.canonical.planning_fields import STRENGTH_STRUCTURE
from backend.providers.garmin_strength_workout import (
    GarminExercise,
    name_key,
    stored_pair,
)

_ROWS_SQL = (
    "SELECT payload, updated_at FROM planned_units "
    "WHERE tombstone=0 AND payload LIKE '%garmin_exercise%' "
    "UNION ALL SELECT payload, updated_at FROM workout_library "
    "WHERE payload LIKE '%garmin_exercise%' "
    "ORDER BY updated_at"
)


def remembered_exercises(db: Any) -> dict[str, GarminExercise]:
    """Confirmed Garmin exercise per exercise-name key; the newest wins."""
    remembered: dict[str, GarminExercise] = {}
    for row in db.execute(_ROWS_SQL).fetchall():
        try:
            payload = json.loads(row["payload"] or "{}")
        except TypeError, ValueError:
            continue
        structure = (
            payload.get(STRENGTH_STRUCTURE) if isinstance(payload, dict) else None
        )
        for item in structure if isinstance(structure, list) else []:
            if not isinstance(item, dict):
                continue
            pair = stored_pair(item)
            key = name_key(item.get("name"))
            if pair is not None and key:
                remembered[key] = pair
    return remembered
