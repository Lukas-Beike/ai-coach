"""Provider-neutral keys stored in local planning records."""

from typing import Final

PLANNED_LOAD: Final = "planned_load"
PLANNED_INTENSITY: Final = "planned_intensity"
SESSION_FOCUS: Final = "session_focus"
STRENGTH_INTENSITY: Final = "strength_intensity"
STRENGTH_STRUCTURE: Final = "strength_structure"
# The two classification keys; the structure is a third local key of strength.
FOCUS_ONLY_KEYS: Final = (SESSION_FOCUS, STRENGTH_INTENSITY)
SESSION_FOCUS_KEYS: Final = (*FOCUS_ONLY_KEYS, STRENGTH_STRUCTURE)

ENDURANCE_FOCI: Final = (
    "recovery",
    "easy",
    "endurance",
    "long",
    "tempo",
    "threshold",
    "vo2max",
    "anaerobic",
    "race",
    "test",
)
RIDE_FOCI: Final = (*ENDURANCE_FOCI[:6], "sweet_spot", *ENDURANCE_FOCI[6:])
STRENGTH_FOCI: Final = (
    "legs",
    "upper",
    "full_body",
    "core",
    "plyometrics",
    "mobility",
)
