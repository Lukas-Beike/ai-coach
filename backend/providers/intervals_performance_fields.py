"""Intervals.icu wire field names that the workout output side reads back.

``TRAINING_LOAD`` and ``INTENSITY`` are also keys of the app's own planned-unit
JSON, which the PWA consumes, so they must not change.
"""

from typing import Final

TRAINING_LOAD: Final = "icu_training_load"
INTENSITY: Final = "icu_intensity"
