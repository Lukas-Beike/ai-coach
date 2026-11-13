"""Garmin exercises the athlete confirmed, remembered per exercise name.

A structure exercise that names its Garmin catalogue exercise explicitly
(``garmin_exercise``, set by the Coach after asking or picked in the unit
editor) stores the resolved pair. That confirmation also applies to the same
exercise name in other units, so it is asked once. Nothing extra is stored: the
mappings are read from the local planned units and library templates, newest
wins; deleted or archived ones do not count. Read-only.
"""

from __future__ import annotations

from typing import Any

from backend.canonical.planning_fields import STRENGTH_STRUCTURE
from backend.db import planning_store
from backend.planning.repository import parse_payload
from backend.providers.garmin_strength_workout import (
    GarminExercise,
    name_key,
    stored_pair,
)


def _structure(raw: Any) -> list[Any]:
    """The stored exercises of one payload; anything unreadable gives none."""
    structure = (parse_payload(raw) or {}).get(STRENGTH_STRUCTURE)
    return structure if isinstance(structure, list) else []


def remembered_exercises(db: Any) -> dict[str, GarminExercise]:
    """Confirmed Garmin exercise per exercise-name key; the newest wins."""
    remembered: dict[str, GarminExercise] = {}
    for row in planning_store.garmin_exercise_rows(db):
        for item in _structure(row["payload"]):
            if not isinstance(item, dict):
                continue
            pair = stored_pair(item)
            key = name_key(item.get("name"))
            if pair is not None and key:
                remembered[key] = pair
    return remembered
