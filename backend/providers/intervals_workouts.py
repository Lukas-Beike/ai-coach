"""Intervals.icu workout vocabulary and event payload mapping.

Provider-owned: maps stored planned-workout sport text onto Intervals.icu
activity types and renders a provider-neutral ``PlannedWorkoutExport`` as the
Intervals.icu event payload. Planning owns validation and the export model.
"""

from __future__ import annotations

import re
from typing import Any

from backend.canonical.planned_workout import PlannedWorkoutExport

INTERVALS_EVENT_CATEGORY = "WORKOUT"
INTERVALS_DEFAULT_WORKOUT_TYPE = "Ride"
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
        "external_id": f"{COACH_EVENT_EXTERNAL_PREFIX}{local_id}",
    }


COACH_EVENT_EXTERNAL_PREFIX = "intervals-coach-"
INTERVALS_WORKOUT_SPORTS = {
    "cycling": "Ride",
    "rad": "Ride",
    "rad outdoor": "Ride",
    "radfahren": "Ride",
    "ride": "Ride",
    "virtualride": "VirtualRide",
    "virtual ride": "VirtualRide",
    "rad indoor": "VirtualRide",
    "indoor cycling": "VirtualRide",
    "virtual cycling": "VirtualRide",
    "running": "Run",
    "lauf": "Run",
    "laufen": "Run",
    "run": "Run",
    "strength": "WeightTraining",
    "kraft": "WeightTraining",
    "krafttraining": "WeightTraining",
    "weighttraining": "WeightTraining",
    "bike": "Ride",
    "biking": "Ride",
    "bicycle": "Ride",
    "bike workout": "Ride",
    "cycling workout": "Ride",
    "swim": "Swim",
    "swimming": "Swim",
    "schwimmen": "Swim",
    "run workout": "Run",
    "jogging": "Run",
    "jog": "Run",
    "gym": "WeightTraining",
    "weights": "WeightTraining",
    "weight training": "WeightTraining",
    "hiking": "Hike",
    "walking": "Walk",
    "row": "Rowing",
    "rowing": "Rowing",
    "yoga": "Yoga",
}

INTERVALS_WORKOUT_TYPES = {
    "Ride",
    "Run",
    "Swim",
    "WeightTraining",
    "Hike",
    "Walk",
    "AlpineSki",
    "BackcountrySki",
    "Badminton",
    "Canoeing",
    "Crossfit",
    "EBikeRide",
    "EMountainBikeRide",
    "Elliptical",
    "Golf",
    "GravelRide",
    "Handcycle",
    "HighIntensityIntervalTraining",
    "IceSkate",
    "InlineSkate",
    "Kayaking",
    "Kitesurf",
    "MountainBikeRide",
    "NordicSki",
    "OpenWaterSwim",
    "Padel",
    "Pilates",
    "Pickleball",
    "Racquetball",
    "Rugby",
    "RockClimbing",
    "RollerSki",
    "Rowing",
    "Sail",
    "Skateboard",
    "Snowboard",
    "Snowshoe",
    "Soccer",
    "Squash",
    "StairStepper",
    "StandUpPaddling",
    "Surfing",
    "TableTennis",
    "Tennis",
    "TrailRun",
    "Transition",
    "Velomobile",
    "VirtualRide",
    "VirtualRow",
    "VirtualRun",
    "WaterSport",
    "Wheelchair",
    "Windsurf",
    "Workout",
    "Yoga",
    "Other",
}

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
    raw = str(value or "Ride").strip()
    normalized = re.sub(r"[\s_-]+", " ", raw.casefold())
    canonical = INTERVALS_WORKOUT_SPORTS.get(
        raw.casefold()
    ) or INTERVALS_WORKOUT_SPORTS.get(normalized)
    if canonical:
        return canonical
    for activity_type in INTERVALS_WORKOUT_TYPES:
        if activity_type.casefold() == raw.casefold():
            return activity_type
    return "Other"
