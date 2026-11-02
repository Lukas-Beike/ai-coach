"""Intensity, 3-zone time and load of a planned unit, derived at read time."""

from collections.abc import Mapping
from typing import Any

from backend.activities.workout_load import (
    AthleteThresholds,
    WorkoutEstimate,
    estimate_workout,
)
from backend.athlete.measurements import number
from backend.planning.sport import planned_sport_environment


def estimate_planned_unit(
    unit: Mapping[str, Any], thresholds: AthleteThresholds
) -> WorkoutEstimate:
    """Estimate a planned unit from its ``description`` workout text.

    The unit's own planned duration is only used when its steps cannot be parsed.
    """
    seconds = number(unit.get("planned_duration_s"))
    minutes = number(unit.get("duration_minutes"))
    if seconds is None and minutes is not None:
        seconds = minutes * 60
    return estimate_workout(
        str(unit.get("description") or ""),
        planned_sport_environment(unit)[0],
        thresholds,
        fallback_duration_s=seconds,
    )
