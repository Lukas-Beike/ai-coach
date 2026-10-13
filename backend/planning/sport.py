"""Read boundary for the sport of a stored or drafted planned workout.

Planning stores the canonical ``Sport`` and ``Environment`` (schema version 9).
Drafts and older API input may still carry a legacy token (``VirtualRide``); this
translator reads either representation through the canonical stored-sport table.
Unknown or generic tokens (for example ``Workout``) map to ``Sport.OTHER``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.canonical.stored_sports import StoredSport, workout_sport_from_record
from backend.canonical.vocabulary import Environment, Sport
from backend.providers.intervals_workouts import intervals_record_type


def planned_stored_sport(record: Mapping[str, Any]) -> StoredSport:
    """Return the canonical stored sport of a workout record or draft."""
    return workout_sport_from_record(record)


def planned_sport_environment(record: Mapping[str, Any]) -> tuple[Sport, Environment]:
    """Return the canonical sport and environment of a workout record or draft."""
    stored = workout_sport_from_record(record)
    return stored.sport, stored.environment


def apply_sport_update(candidate: dict[str, Any], values: Mapping[str, Any]) -> None:
    """Apply a requested sport change (canonical value or legacy token) to a record.

    The previous environment and kept detail belong to the previous sport, so they
    are dropped unless the request carries its own.
    """
    if "type" not in values and "sport" not in values:
        if values.get("environment"):
            candidate["environment"] = values["environment"]
        return
    for key in ("type", "environment", "sport_detail"):
        candidate.pop(key, None)
    candidate["sport"] = values.get("sport") or values.get("type")
    for key in ("environment", "sport_detail"):
        if values.get(key):
            candidate[key] = values[key]


def planned_activity_type(record: Mapping[str, Any]) -> str:
    """Return the familiar activity type (``VirtualRide``) of a workout record."""
    return intervals_record_type(record)


def with_activity_type(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the derived provider-facing activity type to a stored workout payload.

    Stored workouts keep only the canonical sport and environment. Read models
    still show the familiar activity type (for example ``VirtualRide``), derived
    through the Intervals.icu adapter and never written back.
    """
    payload["type"] = planned_activity_type(payload)
    return payload
