"""Intervals.icu workout vocabulary and event payload mapping.

Provider-owned: maps stored planned-workout sport text onto Intervals.icu
activity types, renders a provider-neutral ``PlannedWorkoutExport`` as the
Intervals.icu event payload, and reads remote event identity, category, and
pairing fields. Planning owns validation and the export model; date-aware
predicates live in the sync-layer export adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.canonical.planned_workout import PlannedWorkoutExport
from backend.canonical.stored_sports import (
    DEFAULT_WORKOUT_SPORT_TOKEN,
    WORKOUT_SPORT_ALIASES,
    WORKOUT_SPORT_TOKENS,
    workout_stored_token,
)

INTERVALS_EVENT_CATEGORY = "WORKOUT"
INTERVALS_DEFAULT_WORKOUT_TYPE = DEFAULT_WORKOUT_SPORT_TOKEN
INTERVALS_TEMPLATE_WORKOUT_TYPES = frozenset(
    {"Ride", "VirtualRide", "Run", "Swim", "WeightTraining"}
)


def intervals_event_payload(
    local_id: str, export: PlannedWorkoutExport
) -> dict[str, Any]:
    """Render one planned-workout export model as an Intervals.icu event payload."""
    return {
        "category": INTERVALS_EVENT_CATEGORY,
        "start_date_local": export.start_date_local,
        "type": intervals_workout_sport(export.sport_token),
        "name": export.name,
        "description": export.description,
        "moving_time": export.duration_seconds,
        "target": export.target,
        "external_id": intervals_external_id(local_id),
    }


COACH_EVENT_EXTERNAL_PREFIX = "intervals-coach-"
# The stored workout sport vocabulary is the Intervals.icu activity-type
# vocabulary, so the wire type of a stored token is the token itself. Aliases and
# the token set derive from the canonical stored-sport tables.
INTERVALS_WORKOUT_SPORTS: Mapping[str, str] = WORKOUT_SPORT_ALIASES
INTERVALS_WORKOUT_TYPES: frozenset[str] = frozenset(WORKOUT_SPORT_TOKENS)

# These sport families have duration/distance and intensity prescriptions.
# Other supported activities retain free-text instructions (e.g. Yoga/Golf).
INTERVALS_ENDURANCE_WORKOUT_TYPES = {
    "Ride",
    "VirtualRide",
    "EBikeRide",
    "EMountainBikeRide",
    "GravelRide",
    "MountainBikeRide",
    "Velomobile",
    "Handcycle",
    "Run",
    "TrailRun",
    "VirtualRun",
    "Walk",
    "Hike",
    "Wheelchair",
    "Swim",
    "OpenWaterSwim",
    "Rowing",
    "VirtualRow",
    "Canoeing",
    "Kayaking",
    "StandUpPaddling",
    "NordicSki",
    "RollerSki",
    "Snowshoe",
    "IceSkate",
    "InlineSkate",
    "Elliptical",
    "StairStepper",
}


def intervals_workout_sport(value: Any) -> str:
    """Return the provider's canonical activity type for workout payloads."""
    return workout_stored_token(value) or "Other"


def intervals_external_id(local_id: str) -> str:
    """Return the external id that marks one local planned unit as coach-owned."""
    return f"{COACH_EVENT_EXTERNAL_PREFIX}{local_id}"


def intervals_event_identity(event: Any) -> str:
    """Return the Intervals.icu event id as text, or "" when the event has none."""
    return str(event.get("id") or "")


def intervals_event_external_id(event: Any) -> str:
    """Return the external id carried by an Intervals.icu event, or ""."""
    return str(event.get("external_id") or "")


def intervals_event_start_date(event: Any) -> str:
    """Return the raw local start value of an Intervals.icu event, or ""."""
    return str(event.get("start_date_local") or "")


def intervals_event_is_planned(event: Any) -> bool:
    """Return whether an Intervals.icu event is a planned workout."""
    return event.get("category") == INTERVALS_EVENT_CATEGORY


def intervals_event_is_paired(event: Any) -> bool:
    """Return whether an Intervals.icu event is linked to an activity or event."""
    return bool(event.get("paired_activity_id") or event.get("paired_event_id"))


def intervals_event_is_namesake(event: Any, *, day: str, name: Any) -> bool:
    """Return whether a planned event on ``day`` shares ``name`` (case and edge spaces ignored)."""
    return (
        intervals_event_is_planned(event)
        and intervals_event_start_date(event).startswith(day)
        and str(event.get("name") or "").strip().casefold()
        == str(name or "").strip().casefold()
    )


def intervals_event_confirms_schedule(event: Any, *, day: str, name: Any) -> bool:
    """Return whether a saved event starts on ``day`` and carries exactly ``name``."""
    return intervals_event_start_date(event).startswith(day) and (
        event.get("name") == name
    )
