"""Intervals.icu workout vocabulary and event payload mapping.

Provider-owned: maps stored planned-workout sport text onto Intervals.icu
activity types, renders a provider-neutral ``PlannedWorkoutExport`` as the
Intervals.icu event payload, maps the start and duration fields of Intervals.icu
events and workouts onto the provider-neutral names of local planning records,
and reads remote event identity, category, and pairing fields. Planning owns
validation and the export model; date-aware predicates live in the sync-layer
export adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.canonical.planned_workout import PlannedWorkoutExport
from backend.canonical.planning_fields import PLANNED_INTENSITY, PLANNED_LOAD
from backend.canonical.stored_sports import (
    DEFAULT_WORKOUT_SPORT_TOKEN,
    LEGACY_COMPETITION_TOKENS,
    PRIMARY_WORKOUT_TOKENS,
    WORKOUT_SPORT_ALIASES,
    WORKOUT_SPORT_TOKENS,
    StoredSport,
    resolve_workout_sport,
    workout_sport_from_record,
)
from backend.canonical.vocabulary import Environment
from backend.providers.intervals_activity_fields import REMOTE_EVENT_METRIC_KEYS
from backend.providers.intervals_performance_fields import INTENSITY, TRAINING_LOAD

INTERVALS_EVENT_CATEGORY = "WORKOUT"
# Workout payload field holding structured interval text.
WORKOUT_INTERVALS_FIELD = "intervals"
# Remote-derived fields that stop being valid once a local workout is edited.
DERIVED_WORKOUT_KEYS = ("workout_doc", PLANNED_LOAD, PLANNED_INTENSITY)
INTERVALS_DEFAULT_WORKOUT_TYPE = DEFAULT_WORKOUT_SPORT_TOKEN
INTERVALS_TEMPLATE_WORKOUT_TYPES = frozenset(
    {"Ride", "VirtualRide", "Run", "Swim", "WeightTraining"}
)

# Intervals.icu event and workout field -> the provider-neutral field of a local
# planning record (planned unit, library entry, competition). The wire names
# exist only on the wire: every planning record crossing the provider boundary
# passes through planning_fields_from_intervals or intervals_fields_from_planning.
PLANNING_START_FIELD = "starts_at_local"
PLANNING_DURATION_FIELD = "planned_duration_s"
_PLANNING_WIRE_FIELDS = (
    ("start_date_local", PLANNING_START_FIELD),
    ("moving_time", PLANNING_DURATION_FIELD),
    (TRAINING_LOAD, PLANNED_LOAD),
    (INTENSITY, PLANNED_INTENSITY),
)
_PLANNING_FIELD_BY_WIRE = dict(_PLANNING_WIRE_FIELDS)
# Planned-unit metrics a synced remote event carries back, by planning name.
REMOTE_PLANNED_METRIC_KEYS = tuple(
    _PLANNING_FIELD_BY_WIRE.get(key, key) for key in REMOTE_EVENT_METRIC_KEYS
)


def _renamed_fields(
    record: Mapping[str, Any], renames: tuple[tuple[str, str], ...]
) -> dict[str, Any]:
    result = dict(record)
    for source, target in renames:
        if source not in result:
            continue
        value = result.pop(source)
        if target not in result:
            result[target] = value
    return result


def planning_fields_from_intervals(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return an Intervals.icu event or workout with planning-record field names."""
    return _renamed_fields(record, _PLANNING_WIRE_FIELDS)


def intervals_fields_from_planning(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a planning-record payload with the Intervals.icu wire field names."""
    return _renamed_fields(
        record, tuple((neutral, wire) for wire, neutral in _PLANNING_WIRE_FIELDS)
    )


def intervals_event_payload(
    local_id: str, export: PlannedWorkoutExport
) -> dict[str, Any]:
    """Render one planned-workout export model as an Intervals.icu event payload."""
    return {
        "category": INTERVALS_EVENT_CATEGORY,
        "start_date_local": export.starts_at_local,
        "type": intervals_workout_type(
            StoredSport(export.sport, export.environment, export.sport_token or None)
        ),
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
    """Return the provider's activity type for canonical values, tokens or aliases."""
    resolved = resolve_workout_sport(value)
    return "Other" if resolved is None else intervals_workout_type(resolved)


def intervals_workout_type(stored: StoredSport) -> str:
    """Return the Intervals.icu activity type of a canonical stored sport.

    A kept original token is used again when it still names the stored pair, so
    ``GravelRide`` round-trips; otherwise the pair's primary type applies. Sports
    without an Intervals.icu type are ``Other``.
    """
    pair = (stored.sport, stored.environment)
    if stored.environment is Environment.INDOOR:
        # Intervals.icu has no indoor type; indoor sessions use the virtual one,
        # as competitions do.
        pair = (stored.sport, Environment.VIRTUAL)
    if stored.detail and WORKOUT_SPORT_TOKENS.get(stored.detail) == pair:
        return stored.detail
    return (
        PRIMARY_WORKOUT_TOKENS.get(pair)
        or PRIMARY_WORKOUT_TOKENS.get((stored.sport, Environment.UNKNOWN))
        or "Other"
    )


def intervals_record_type(record: Mapping[str, Any]) -> str:
    """Return the Intervals.icu activity type of a stored workout record."""
    return intervals_workout_type(workout_sport_from_record(record))


def intervals_competition_type(stored: StoredSport) -> str | None:
    """Return the Intervals.icu race type of a canonical sport, or None."""
    pair = (stored.sport, stored.environment)
    if stored.environment is Environment.INDOOR:
        pair = (stored.sport, Environment.VIRTUAL)
    for wanted in (pair, (stored.sport, Environment.UNKNOWN)):
        for token, entry in LEGACY_COMPETITION_TOKENS.items():
            if entry == wanted:
                return token
    return None


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
