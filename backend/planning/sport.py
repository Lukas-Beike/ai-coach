"""Read boundary for stored planned-workout sport text.

Planning keeps stored sport tokens exactly as saved. This translator gives the
canonical ``Sport`` and ``Environment`` used by planning decisions, through the
provider's activity table. Unknown or generic tokens (for example ``Workout``)
map to ``Sport.OTHER`` with an unknown environment.
"""

from __future__ import annotations

from typing import Any

from backend.canonical.vocabulary import Environment, Sport
from backend.providers.intervals_activity_mapping import INTERVALS_ACTIVITY_TYPES
from backend.providers.intervals_workouts import intervals_workout_sport


def planned_sport_environment(stored_sport: Any) -> tuple[Sport, Environment]:
    """Return the canonical sport and environment for a stored sport token."""
    activity_type = intervals_workout_sport(stored_sport)
    return INTERVALS_ACTIVITY_TYPES.get(
        activity_type, (Sport.OTHER, Environment.UNKNOWN)
    )
