"""Read boundary for stored planned-workout sport text.

Planning keeps stored sport tokens exactly as saved. This translator gives the
canonical ``Sport`` and ``Environment`` used by planning decisions, through the
canonical stored-sport table. Unknown or generic tokens (for example ``Workout``)
map to ``Sport.OTHER`` with an unknown environment.
"""

from __future__ import annotations

from typing import Any

from backend.canonical.stored_sports import workout_sport_environment
from backend.canonical.vocabulary import Environment, Sport


def planned_sport_environment(stored_sport: Any) -> tuple[Sport, Environment]:
    """Return the canonical sport and environment for a stored sport token."""
    return workout_sport_environment(stored_sport) or (
        Sport.OTHER,
        Environment.UNKNOWN,
    )
